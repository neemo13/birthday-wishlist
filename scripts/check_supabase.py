"""Verify a REAL Supabase project is set up correctly. Run this yourself after the SQL setup and before sharing the site:

    python scripts/check_supabase.py                      # uses .streamlit/secrets.toml (or environment variables)
    python scripts/check_supabase.py --anon-key <anon key>   # also proves the public key can read/call nothing

It never prints keys or passwords. It creates and deletes ONE tiny test image in your private bucket. Exit code 0 = all
checks passed, 1 = something needs fixing (the message says what).
"""
from __future__ import annotations

import io
import json
import sys
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

FAKE_TOKEN = "0" * 64
PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"


@dataclass(frozen=True)
class Result:
    name: str
    status: str
    detail: str = ""


def _safe(exc: Exception) -> str:
    return type(exc).__name__          # class only: provider messages may contain URLs or keys


# ----------------------------------------------------------------------------- database checks
def _rpc(client, fn, params):
    return client.rpc(fn, params).execute().data


REFUSE = {"ok": False, "code": "forbidden"}
RPC_CHECKS = [   # (function, params, expected, migration that creates it)
    ("session_get", {"p_token_hash": FAKE_TOKEN}, {"valid": False}, "003_auth_functions.sql"),
    ("catalog_list", {"p_token_hash": FAKE_TOKEN}, REFUSE, "004_content_functions.sql"),
    ("settings_get", {"p_token_hash": FAKE_TOKEN}, REFUSE, "004_content_functions.sql"),
    ("admin_snapshot", {"p_token_hash": FAKE_TOKEN}, REFUSE, "005_admin_functions.sql"),
    ("product_save", {"p_token_hash": FAKE_TOKEN, "p_product": {"name": "x"}}, REFUSE, "005_admin_functions.sql"),
    ("claim_create", {"p_token_hash": FAKE_TOKEN, "p_product_id": str(uuid.uuid4()), "p_family_slug": "mom", "p_pin": "1234"},
     REFUSE, "006_claims_and_dad.sql"),
    ("claim_release", {"p_token_hash": FAKE_TOKEN, "p_product_id": str(uuid.uuid4()), "p_name": "Mom", "p_pin": "1234"},
     REFUSE, "006_claims_and_dad.sql"),
    ("dad_page_get", {"p_token_hash": FAKE_TOKEN}, REFUSE, "006_claims_and_dad.sql"),
]


def check_functions(client) -> list[Result]:
    out = []
    for fn, params, expected, migration in RPC_CHECKS:
        try:
            got = _rpc(client, fn, params)
        except Exception as exc:  # noqa: BLE001
            out.append(Result(f"function {fn}", FAIL, f"call failed ({_safe(exc)}) - run sql/{migration}, then sql/999_storage_and_lockdown.sql"))
            continue
        ok = got == expected
        out.append(Result(f"function {fn} refuses a fake session", PASS if ok else FAIL,
                          "" if ok else "unexpected answer - was the SQL file edited or only partly applied?"))
    return out


def check_seed_and_credentials(client) -> list[Result]:
    out = []
    try:
        fam = client.table("family_members").select("slug").execute().data
        out.append(Result("four family names exist", PASS if len(fam) == 4 else FAIL, f"found {len(fam)}"))
        cats = client.table("categories").select("kind").execute().data
        dad = [c for c in cats if c.get("kind") == "dad_only"]
        out.append(Result("exactly one protected Dad Only category", PASS if len(dad) == 1 else FAIL, f"found {len(dad)}"))
        keys = {r["key"] for r in client.table("app_settings").select("key").execute().data}
        need = {"homepage", "wishlist", "sections", "dad_page", "security"}
        out.append(Result("default website settings exist", PASS if need <= keys else FAIL, "missing: " + ", ".join(sorted(need - keys)) if need - keys else ""))
        creds = {r["kind"]: r for r in client.table("app_credentials").select("kind,enabled,secret_hash").execute().data}
        for kind in ("admin", "family"):
            ok = bool(creds.get(kind, {}).get("secret_hash"))
            out.append(Result(f"{kind} credential is set", PASS if ok else FAIL,
                              "" if ok else f"run: python scripts/set_credential.py {kind}"))
        dad_ok = bool(creds.get("dad_only", {}).get("secret_hash"))
        out.append(Result("Dad Only PIN is set", PASS if dad_ok else SKIP, "" if dad_ok else "optional - set it in Admin Studio -> Dad Only"))
        hashed = all(str(r.get("secret_hash") or "$2").startswith("$2") for r in creds.values())
        out.append(Result("stored secrets are bcrypt hashes", PASS if hashed else FAIL))
    except Exception as exc:  # noqa: BLE001
        out.append(Result("read tables with the service key", FAIL, f"failed ({_safe(exc)}) - is SUPABASE_SERVICE_KEY the service_role key?"))
    return out


# ----------------------------------------------------------------------------- public-key checks
def check_anon_blocked(http, base_url: str, anon_key: str | None) -> list[Result]:
    if not anon_key:
        return [Result("public (anon) key can access nothing", SKIP, "pass --anon-key to test this")]
    headers = {"apikey": anon_key, "Authorization": f"Bearer {anon_key}"}
    out = []
    for table in ("app_credentials", "products", "claims", "sessions"):
        status, body = http("GET", f"{base_url}/rest/v1/{table}?select=*&limit=1", headers, None)
        leaked = status == 200 and body.strip() not in ("[]", "")
        out.append(Result(f"anon cannot read {table}", FAIL if leaked else PASS, f"HTTP {status}"))
    for fn in ("auth_login", "catalog_list", "dad_page_get"):
        status, _ = http("POST", f"{base_url}/rest/v1/rpc/{fn}", {**headers, "Content-Type": "application/json"}, json.dumps({}))
        out.append(Result(f"anon cannot call {fn}", PASS if status in (401, 403, 404) else FAIL, f"HTTP {status}"))
    return out


# ----------------------------------------------------------------------------- storage checks
def _bucket_public(bucket_obj):
    return bucket_obj.get("public") if isinstance(bucket_obj, dict) else getattr(bucket_obj, "public", None)


def check_bucket(client, bucket: str) -> list[Result]:
    try:
        info = client.storage.get_bucket(bucket)
    except Exception as exc:  # noqa: BLE001
        return [Result(f"bucket '{bucket}' exists", FAIL, f"lookup failed ({_safe(exc)}) - run sql/999_storage_and_lockdown.sql")]
    public = _bucket_public(info)
    return [Result(f"bucket '{bucket}' exists", PASS), Result("bucket is PRIVATE", PASS if public is False else FAIL,
                                                             "" if public is False else "set the bucket to private in Supabase -> Storage")]


def _tiny_jpeg() -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (164, 78, 112)).save(buf, "JPEG")
    return buf.getvalue()


def check_storage_roundtrip(backend, http, base_url: str, bucket: str, ttl: int = 60) -> list[Result]:
    path = f"product/{uuid.uuid4().hex}.jpg"
    out, uploaded = [], False
    try:
        backend.upload(path, _tiny_jpeg(), "image/jpeg")
        uploaded = True
        out.append(Result("upload a test image", PASS))
        url = backend.sign([path], ttl).get(path)
        out.append(Result("create a signed URL", PASS if url else FAIL))
        if url:
            status, body = http("GET", url, None, None)
            out.append(Result("signed URL serves the image", PASS if status == 200 else FAIL, f"HTTP {status}"))
        status, _ = http("GET", f"{base_url}/storage/v1/object/public/{bucket}/{path}", None, None)
        out.append(Result("plain public URL does NOT serve it", PASS if status != 200 else FAIL,
                          f"HTTP {status}" + ("" if status != 200 else " - the bucket is public!")))
    except Exception as exc:  # noqa: BLE001
        out.append(Result("storage upload / sign / fetch", FAIL, f"failed ({_safe(exc)})"))
    finally:
        if uploaded:
            try:
                backend.remove([path])
                out.append(Result("delete the test image", PASS))
            except Exception as exc:  # noqa: BLE001
                out.append(Result("delete the test image", FAIL, f"failed ({_safe(exc)}) - remove {path} by hand"))
    return out


# ----------------------------------------------------------------------------- orchestration
def run_all(client, backend, http, base_url: str, bucket: str, anon_key: str | None = None) -> list[Result]:
    return [*check_functions(client), *check_seed_and_credentials(client), *check_anon_blocked(http, base_url, anon_key),
            *check_bucket(client, bucket), *check_storage_roundtrip(backend, http, base_url, bucket)]


def urllib_http(method, url, headers=None, body=None):
    req = urllib.request.Request(url, data=body.encode() if isinstance(body, str) else body, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status, resp.read(2000).decode("latin-1")
    except urllib.error.HTTPError as err:
        return err.code, ""
    except Exception:  # noqa: BLE001 - network problems count as "not served"
        return 0, ""


def render(results: list[Result]) -> str:
    icon = {PASS: "  ok ", FAIL: " FAIL", SKIP: " skip"}
    lines = [f"[{icon[r.status]}] {r.name}" + (f"  - {r.detail}" if r.detail else "") for r in results]
    failed = sum(r.status == FAIL for r in results)
    lines.append(f"\n{sum(r.status == PASS for r in results)} passed, {failed} failed, {sum(r.status == SKIP for r in results)} skipped")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    anon = argv[argv.index("--anon-key") + 1] if "--anon-key" in argv else None
    try:
        import tomllib, os
        secrets = Path(__file__).resolve().parent.parent / ".streamlit" / "secrets.toml"
        if secrets.exists():
            for k, v in tomllib.loads(secrets.read_text()).items():
                os.environ.setdefault(k, str(v))
        from supabase import create_client
        from wishlist.config import ConfigError, load_config
        from wishlist.storage import SupabaseStorage
        cfg = load_config()
        client = create_client(cfg.supabase_url, cfg.service_key)
    except Exception as exc:  # noqa: BLE001
        print(f"Cannot start: {type(exc).__name__}: {exc if type(exc).__name__ == 'ConfigError' else 'check your secrets'}")
        return 1
    backend = SupabaseStorage(client, cfg.bucket, cfg.supabase_url)
    results = run_all(client, backend, urllib_http, cfg.supabase_url.rstrip("/"), cfg.bucket, anon)
    print(render(results))
    return 1 if any(r.status == FAIL for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
