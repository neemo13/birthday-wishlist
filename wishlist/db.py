"""Thin Supabase wrapper. All errors become BackendError with a safe, generic message."""
from __future__ import annotations

import logging
from typing import Any

from .config import load_config

log = logging.getLogger("wishlist.db")
_client: Any = None


class BackendError(Exception):
    """Database/storage problem. str(exc) is safe to show users; details go to the server log."""

    USER_MESSAGE = "We couldn't reach the gift server just now. Please try again in a moment."

    def __init__(self, message: str | None = None):
        super().__init__(message or self.USER_MESSAGE)


def set_client(client: Any) -> None:
    """Inject a client (used by tests)."""
    global _client
    _client = client


def get_client() -> Any:
    global _client
    if _client is None:
        from supabase import create_client

        cfg = load_config()
        _client = create_client(cfg.supabase_url, cfg.service_key)
    return _client


def _log_failure(what: str, exc: Exception) -> None:
    # Class name only: never log parameters (they can contain PINs) or exception text.
    log.error("%s failed (%s)", what, type(exc).__name__, exc)


def rpc(name: str, params: dict | None = None) -> Any:
    client = get_client()  # ConfigError propagates so the app can show a setup message
    try:
        return client.rpc(name, params or {}).execute().data
    except Exception as exc:  # noqa: BLE001 - converted to a safe error below
        _log_failure(f"rpc {name}", exc)
        raise BackendError() from exc


def table(name: str) -> Any:
    return get_client().table(name)


def run(what: str, fn):
    """Run a query callable, converting any failure to BackendError."""
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001
        _log_failure(what, exc)
        raise BackendError() from exc
