"""The HTTP surface: threads, turns, the caseworker queue, and the corpus alarm.

`create_app` is exported lazily so that importing anything else in this package
does not drag in FastAPI. That matters for exactly one thing today, and it is
not hypothetical: `wayfinder caseworker-token` mints a credential using nothing
but `hashlib` and `secrets`, and an eager import here made it fail with a
FastAPI `ModuleNotFoundError` on a default `uv sync`. Setting up a caseworker is
something you do before deciding how to serve the thing, so it should not
require the web framework.
"""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from wayfinder.api.app import create_app

__all__ = ["create_app"]


def __getattr__(name: str) -> Any:
    if name == "create_app":
        from wayfinder.api.app import create_app

        return create_app
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
