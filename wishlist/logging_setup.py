"""Server-side logging that cannot leak secrets.

Rules followed across the code base:
  1. Never pass PINs, passwords, tokens or request bodies to a logger.
  2. As a safety net, every record also goes through `redact()` before it is written.
"""
from __future__ import annotations

import logging
import re

_PATTERNS = [
    (re.compile(r"(?i)\b(bearer|basic)\s+\S+"), r"\1 [REDACTED]"),            # Authorization headers
    # key=value / key: value / "key": "value" for sensitive-looking keys
    (re.compile(r"""(?ix)\b(pin|pass(?:word)?|secret|token|authorization|api[_-]?key|service[_-]?key)\b
                    (["']?\s*[=:]\s*)("[^"]*"|'[^']*'|\S+)"""), r"\1\2[REDACTED]"),
    (re.compile(r"\beyJ[\w-]{10,}\.[\w-]{10,}\.[\w-]{5,}"), "[REDACTED-JWT]"),   # JWTs (Supabase keys)
    (re.compile(r"\b[A-Za-z0-9_-]{40,}\b"), "[REDACTED-LONG]"),                 # session tokens / hashes
]


def redact(text: str) -> str:
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    return text


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = ()
        return True


_CONFIGURED = False


def setup_logging(level: str = "INFO") -> None:
    """Idempotent: Streamlit re-runs the script constantly, so never add handlers twice."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.addFilter(RedactingFilter())
    root = logging.getLogger("wishlist")
    root.setLevel(level)
    root.addHandler(handler)
    root.propagate = False
    logging.getLogger("httpx").setLevel(logging.WARNING)   # request lines are noise
    _CONFIGURED = True
