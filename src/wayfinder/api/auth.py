"""Who is allowed at the caseworker queue, and who a determination belongs to.

The queue carries what people have said about their own circumstances, so it
needs a lock. That is the obvious half.

The half that matters more is attribution. `answered_by` used to be a free-text
field in the request body, so the audit trail was only as good as the honesty of
whoever posted: anybody who could reach the endpoint could sign a determination
with any name. ADR-0004 rests on a determination being traceable to a named
human, and a name somebody typed about themselves is not that.

So **the name comes from the credential, not from the body**. A caseworker
authenticates as themselves and the determination is signed with the name their
token is registered to. There is no way to answer as somebody else short of
using their token, which is the same as impersonating them anywhere.

Three more choices worth stating.

**It fails closed.** With no caseworkers configured the queue endpoints return
503 rather than opening. A misconfiguration that silently disables a lock is
worse than one that stops the service, because only one of them gets noticed.

**Tokens are stored as hashes.** The configuration holds SHA-256 digests, so a
leaked config file does not hand over working credentials. Comparison is
constant-time.

**Nothing here logs a token.** Not on success, not on failure, not in an error
message. A 401 says a token was rejected and nothing about which one.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
from pathlib import Path
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, ValidationError

# Long enough that guessing is not a strategy. `secrets.token_urlsafe(32)`
# produces 43 characters, so this rejects anything obviously hand-typed.
MINIMUM_TOKEN_LENGTH: Final = 32

ENV_VAR: Final = "WAYFINDER_CASEWORKERS"


class AuthError(Exception):
    """The caseworker configuration could not be read. Startup fails on it."""


class Caseworker(BaseModel):
    """One person who may answer determinations, and the name they sign with."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    token_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def mint_token() -> tuple[str, str]:
    """A new token and its digest. The token is shown once and never stored."""
    token = secrets.token_urlsafe(32)
    return token, hash_token(token)


class Caseworkers:
    """The registry. Empty means the queue is closed, not open."""

    __slots__ = ("_people",)

    def __init__(self, people: list[Caseworker]) -> None:
        digests = [person.token_sha256 for person in people]
        if len(set(digests)) != len(digests):
            msg = (
                "two caseworkers share a token digest. A shared token makes the "
                "attribution on a determination meaningless, which is the one "
                "thing this is for."
            )
            raise AuthError(msg)
        self._people = tuple(people)

    def __len__(self) -> int:
        return len(self._people)

    @property
    def configured(self) -> bool:
        return bool(self._people)

    def authenticate(self, token: str | None) -> Caseworker | None:
        """The caseworker this token belongs to, or None.

        Every entry is compared even after a match. The token is the secret
        rather than the name, so the timing signal is small either way, but
        early-exit comparison is the kind of thing that is free to avoid and
        awkward to explain later.
        """
        if not token or len(token) < MINIMUM_TOKEN_LENGTH:
            return None

        digest = hash_token(token)
        found: Caseworker | None = None
        for person in self._people:
            if secrets.compare_digest(person.token_sha256, digest):
                found = person
        return found


def _parse(raw: str, source: str) -> Caseworkers:
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError as exc:
        msg = f"{source} is not valid JSON: {exc}"
        raise AuthError(msg) from exc

    if not isinstance(loaded, list):
        msg = (
            f"{source} must be a JSON list of caseworkers, got {type(loaded).__name__}"
        )
        raise AuthError(msg)

    people = []
    for position, entry in enumerate(loaded):
        try:
            people.append(Caseworker.model_validate(entry))
        except ValidationError as exc:
            # Only which field and why, never what was in it. Pydantic's own
            # message quotes the offending value, and the likeliest mistake
            # here is a real token pasted where its digest belongs, so passing
            # that message through would put a live credential in a log.
            problems = ", ".join(
                f"{'.'.join(str(p) for p in error['loc']) or 'entry'} ({error['type']})"
                for error in exc.errors()
            )
            msg = (
                f"{source} holds an invalid caseworker entry at position "
                f"{position}: {problems}. Values are not echoed here because a "
                "malformed entry often holds a token where its digest belongs."
            )
            raise AuthError(msg) from None
    return Caseworkers(people)


def load_caseworkers(
    *,
    env_var: str = ENV_VAR,
    path: Path | None = None,
) -> Caseworkers:
    """Read the registry from a file or the environment.

    A missing configuration is not an error here, because the deterministic
    build and every test that does not touch the queue runs without one. It
    becomes an error at the door: the endpoints return 503 rather than opening.
    """
    if path is not None:
        if not path.is_file():
            msg = f"no caseworker file at {path}"
            raise AuthError(msg)
        return _parse(path.read_text(encoding="utf-8"), str(path))

    raw = os.environ.get(env_var, "").strip()
    if not raw:
        return Caseworkers([])
    return _parse(raw, f"${env_var}")
