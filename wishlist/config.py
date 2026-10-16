"""Configuration from Streamlit secrets or environment variables. Never hard-code secrets.

Environments (APP_ENV, default "dev"):
  dev  - local development; http://localhost URLs and placeholder-free keys accepted.
  prod - deployed; stricter checks so a half-configured deployment fails loudly instead of running insecurely.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


class ConfigError(RuntimeError):
    """Raised when configuration is missing/invalid. The message never contains secret values."""


SIGNED_URL_SECONDS = 600            # private image links live 10 minutes
MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # matches the bucket's file_size_limit
ENVIRONMENTS = ("dev", "prod")
_PLACEHOLDERS = ("YOUR-", "YOUR_", "REPLACE", "CHANGEME", "<", "xxxx")


@dataclass(frozen=True)
class Config:
    supabase_url: str
    service_key: str
    bucket: str = "wishlist-images"
    app_env: str = "dev"

    @property
    def is_prod(self) -> bool:
        return self.app_env == "prod"



def _read(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value is not None:
        return value

    try:
        import streamlit as st

        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:  # no secrets file / not running under Streamlit
        pass

    return default



def log_level() -> str:
    """Readable without Supabase settings (logging starts before the first database call)."""
    level = (_read("LOG_LEVEL", "INFO") or "INFO").upper()
    return level if level in ("DEBUG", "INFO", "WARNING", "ERROR") else "INFO"


def validate(url: str | None, key: str | None, env: str | None) -> str:
    """Pure check (unit-tested). Returns the normalised environment name or raises ConfigError."""
    env = (env or "dev").strip().lower()
    if env not in ENVIRONMENTS:
        raise ConfigError(f"APP_ENV must be one of {', '.join(ENVIRONMENTS)}.")
    missing = [n for n, v in (("SUPABASE_URL", url), ("SUPABASE_SERVICE_KEY", key)) if not v]
    if missing:
        raise ConfigError("Missing configuration: " + ", ".join(missing)
                          + ". Add them to .streamlit/secrets.toml (see secrets.toml.example).")
    for name, value in (("SUPABASE_URL", url), ("SUPABASE_SERVICE_KEY", key)):
        if any(p.lower() in value.lower() for p in _PLACEHOLDERS):
            raise ConfigError(f"{name} still contains a placeholder - paste your real value.")
    if env == "prod":
        if not url.strip().lower().startswith("https://") or "localhost" in url.lower() or "127.0.0.1" in url:
            raise ConfigError("In production SUPABASE_URL must be your https://<project>.supabase.co address.")
    return env


def load_config() -> Config:
    url, key = _read("SUPABASE_URL"), _read("SUPABASE_SERVICE_KEY")
    env = validate(url, key, _read("APP_ENV"))
    return Config(supabase_url=url.strip(), service_key=key.strip(),
                  bucket=_read("SUPABASE_BUCKET", "wishlist-images") or "wishlist-images", app_env=env)
