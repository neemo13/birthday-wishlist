"""Set or rotate a credential from your own computer (the secret never touches a file or the shell history).

    python scripts/set_credential.py admin       # the Birthday Girl password (min 12 chars)
    python scripts/set_credential.py family      # shared family PIN (min 6 chars)
    python scripts/set_credential.py dad_only    # Dad Only PIN (min 6 chars)
    python scripts/set_credential.py admin --rotate   # overwrite an existing one (also signs everyone out)

Reads SUPABASE_URL / SUPABASE_SERVICE_KEY from .streamlit/secrets.toml or environment variables.
"""
from __future__ import annotations

import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wishlist import db  # noqa: E402
from wishlist.config import ConfigError  # noqa: E402
from wishlist.security import ValidationError, validate_new_secret  # noqa: E402


def _load_secrets_file() -> None:
    import os
    import tomllib

    path = Path(__file__).resolve().parent.parent / ".streamlit" / "secrets.toml"
    if path.exists():
        for k, v in tomllib.loads(path.read_text()).items():
            os.environ.setdefault(k, str(v))


def main(argv: list[str]) -> int:
    kinds = {"admin", "family", "dad_only"}
    args = [a for a in argv if not a.startswith("--")]
    if len(args) != 1 or args[0] not in kinds:
        print(__doc__)
        return 2
    kind, force = args[0], "--rotate" in argv
    _load_secrets_file()
    secret = getpass.getpass(f"New {kind} secret (hidden): ")
    try:
        validate_new_secret(kind, secret, getpass.getpass("Type it again: "))
    except ValidationError as exc:
        print(f"Not saved: {exc}")
        return 1
    try:
        res = db.rpc("credential_bootstrap", {"p_kind": kind, "p_secret": secret, "p_force": force})
    except (ConfigError, db.BackendError) as exc:
        print(f"Could not reach Supabase: {exc}")
        return 1
    if res and res.get("ok"):
        print(f"Done - the {kind} credential is set (stored only as a bcrypt hash).")
        return 0
    if (res or {}).get("code") == "already_set":
        print(f"A {kind} credential already exists. Re-run with --rotate to replace it.")
    else:
        print(f"Not saved ({(res or {}).get('code', 'error')}).")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
