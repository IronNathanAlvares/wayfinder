"""The caseworker registry.

Two things are being protected. The queue carries what people have said about
their own circumstances, and the name on a determination is the audit trail
ADR-0004 rests on. The second is the one that is easy to get subtly wrong: a
lock on the door does nothing if the signature is still whatever the caller
typed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from wayfinder.api.auth import (
    ENV_VAR,
    MINIMUM_TOKEN_LENGTH,
    AuthError,
    Caseworker,
    Caseworkers,
    hash_token,
    load_caseworkers,
    mint_token,
)

CLARE = "Clare Nolan, Irish Refugee Council"


def signed_in_as(people: Caseworkers, token: str) -> str:
    """The name behind a token, failing the test rather than the type check if
    the token turns out not to authenticate."""
    person = people.authenticate(token)
    assert person is not None, "the token did not authenticate"
    return person.name


def registry(*pairs: tuple[str, str]) -> Caseworkers:
    return Caseworkers(
        [Caseworker(name=name, token_sha256=hash_token(token)) for name, token in pairs]
    )


# --- minting ------------------------------------------------------------------


def test_a_minted_token_is_long_enough_to_be_worth_having() -> None:
    token, digest = mint_token()
    assert len(token) >= MINIMUM_TOKEN_LENGTH
    assert digest == hash_token(token)
    assert len(digest) == 64


def test_every_minted_token_is_different() -> None:
    tokens = {mint_token()[0] for _ in range(50)}
    assert len(tokens) == 50


def test_the_digest_does_not_reveal_the_token() -> None:
    """Stating the obvious property the storage model depends on: the config
    holds digests, so a leaked config must not hand over credentials."""
    token, digest = mint_token()
    assert token not in digest


# --- authenticating -----------------------------------------------------------


def test_the_right_token_returns_the_person_it_belongs_to() -> None:
    people = registry((CLARE, "a" * 40), ("Aoife Byrne", "b" * 40))
    assert signed_in_as(people, "a" * 40) == CLARE
    assert signed_in_as(people, "b" * 40) == "Aoife Byrne"


def test_a_wrong_token_returns_nobody() -> None:
    people = registry((CLARE, "a" * 40))
    assert people.authenticate("c" * 40) is None


def test_an_empty_or_missing_token_returns_nobody() -> None:
    people = registry((CLARE, "a" * 40))
    for candidate in ("", None, "   "):
        assert people.authenticate(candidate) is None


def test_a_short_token_is_refused_before_it_is_hashed() -> None:
    """A short token cannot be a minted one, and refusing it early keeps a
    hand-typed password from ever being treated as a credential."""
    short = "a" * (MINIMUM_TOKEN_LENGTH - 1)
    people = registry((CLARE, short))
    assert people.authenticate(short) is None


def test_a_digest_offered_as_a_token_does_not_authenticate() -> None:
    """The config is not the credential. Somebody who reads the deployment
    environment must not be able to replay what they find in it."""
    token = "a" * 40
    people = registry((CLARE, token))
    assert people.authenticate(hash_token(token)) is None


def test_an_empty_registry_authenticates_nobody() -> None:
    assert Caseworkers([]).authenticate("a" * 40) is None
    assert not Caseworkers([]).configured


def test_two_people_cannot_share_a_token() -> None:
    """A shared token makes the name on a determination meaningless, which is
    the one thing this exists for."""
    with pytest.raises(AuthError, match="share a token digest"):
        registry((CLARE, "a" * 40), ("Aoife Byrne", "a" * 40))


# --- loading configuration ----------------------------------------------------


def test_no_configuration_is_an_empty_registry_rather_than_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """It becomes an error at the door, where the endpoints return 503. Failing
    at import would stop every deployment that never touches the queue."""
    monkeypatch.delenv(ENV_VAR, raising=False)
    assert not load_caseworkers().configured


def test_the_environment_variable_is_read(monkeypatch: pytest.MonkeyPatch) -> None:
    token, digest = mint_token()
    monkeypatch.setenv(ENV_VAR, json.dumps([{"name": CLARE, "token_sha256": digest}]))
    people = load_caseworkers()
    assert len(people) == 1
    assert signed_in_as(people, token) == CLARE


def test_a_file_is_read(tmp_path: Path) -> None:
    token, digest = mint_token()
    path = tmp_path / "caseworkers.json"
    path.write_text(
        json.dumps([{"name": CLARE, "token_sha256": digest}]), encoding="utf-8"
    )
    assert signed_in_as(load_caseworkers(path=path), token) == CLARE


def test_a_missing_file_is_an_error_rather_than_an_empty_registry(
    tmp_path: Path,
) -> None:
    """A path that was named and does not exist is a mistake, not a decision to
    run without caseworkers. Silently opening nothing would look identical to
    working until somebody tried the queue."""
    with pytest.raises(AuthError, match="no caseworker file"):
        load_caseworkers(path=tmp_path / "nope.json")


def test_malformed_json_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_VAR, "{not json")
    with pytest.raises(AuthError, match="not valid JSON"):
        load_caseworkers()


def test_the_wrong_shape_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_VAR, json.dumps({"name": CLARE}))
    with pytest.raises(AuthError, match="must be a JSON list"):
        load_caseworkers()


def test_a_plaintext_token_in_the_digest_field_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The likeliest configuration mistake, and the most dangerous: it would
    otherwise store a working credential and authenticate its own hash."""
    monkeypatch.setenv(
        ENV_VAR, json.dumps([{"name": CLARE, "token_sha256": "not-a-digest"}])
    )
    with pytest.raises(AuthError, match="invalid caseworker entry"):
        load_caseworkers()


def test_a_configuration_error_never_echoes_what_it_was_given(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A malformed entry may hold a real token pasted where the digest goes.
    Putting it in an exception puts it in a log."""
    secret = "super-secret-token-pasted-in-the-wrong-field"
    monkeypatch.setenv(ENV_VAR, json.dumps([{"name": CLARE, "token_sha256": secret}]))
    with pytest.raises(AuthError) as caught:
        load_caseworkers()
    assert secret not in str(caught.value)


def test_an_unknown_field_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """`extra="forbid"`, so a typo like `token` instead of `token_sha256` fails
    rather than producing a caseworker nobody can authenticate as."""
    monkeypatch.setenv(
        ENV_VAR,
        json.dumps([{"name": CLARE, "token_sha256": "0" * 64, "token": "oops"}]),
    )
    with pytest.raises(AuthError, match="invalid caseworker entry"):
        load_caseworkers()


# --- what minting is allowed to need ------------------------------------------


def test_minting_a_token_does_not_need_the_web_framework() -> None:
    """Setting a caseworker up happens before deciding how to serve the thing.

    `wayfinder caseworker-token` needs `hashlib` and `secrets` and nothing else,
    but an eager `from wayfinder.api.app import create_app` in the package
    `__init__` made it die on a FastAPI import under a default `uv sync`. This
    asserts the import stays lazy.
    """
    import subprocess
    import sys

    probe = (
        "import sys; import wayfinder.api.auth; "
        "sys.exit(1 if 'fastapi' in sys.modules else 0)"
    )
    assert subprocess.run([sys.executable, "-c", probe], check=False).returncode == 0


def test_the_lazy_export_still_raises_for_an_unknown_name() -> None:
    """A module `__getattr__` that returns something for every name turns a typo
    into a silent `None` at the import site."""
    import wayfinder.api

    assert wayfinder.api.create_app is not None
    with pytest.raises(AttributeError, match="no attribute"):
        _ = wayfinder.api.nonesuch
