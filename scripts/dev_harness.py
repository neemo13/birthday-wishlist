"""DEV/TEST ONLY: run the real app against a local Postgres (no Supabase needed).

    TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres \
      streamlit run scripts/dev_harness.py

Requires the schema to be loaded in database `wishlist_test` (the pytest run does this).
Not used in production - production uses Supabase via app.py directly.
"""
import os
import pathlib
import runpy
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tests.conftest import PgClient  # noqa: E402
from wishlist import db, storage  # noqa: E402
from tests.fakes import DevStorage  # noqa: E402

if os.environ.get("APP_ENV", "dev").lower() == "prod":
    raise SystemExit("dev_harness.py must never run with APP_ENV=prod")
base = os.environ["TEST_DATABASE_URL"]
db.set_client(PgClient(base.rsplit("/", 1)[0] + "/wishlist_test"))
storage.set_backend(DevStorage())
runpy.run_path(str(ROOT / "app.py"), run_name="__main__")
