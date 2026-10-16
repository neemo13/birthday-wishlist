"""Private image storage: validate -> re-encode -> upload (admin only); sign URLs (signed-in only).

Why re-encode with Pillow? (1) proves the bytes really are an image, (2) strips EXIF metadata such as
GPS location from personal photos, (3) caps dimensions so pages stay fast, (4) means we never serve a
file whose type a user merely *claimed*.
"""
from __future__ import annotations

import io
import logging
import re
import time
import uuid
from typing import MutableMapping, Protocol

from PIL import Image, ImageOps, UnidentifiedImageError

from . import auth, db
from .config import MAX_UPLOAD_BYTES, SIGNED_URL_SECONDS, load_config
from .security import PermissionDenied

log = logging.getLogger("wishlist.storage")

KINDS = ("portrait", "product")
PATH_RE = re.compile(r"^(portrait|product)/[0-9a-f]{32}\.jpg$")
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
MAX_PIXELS = 40_000_000
MAX_SIDE = 1600


class UploadError(Exception):
    """Safe-to-show message for a failed or rejected upload."""


class StorageBackend(Protocol):
    def upload(self, path: str, data: bytes, content_type: str) -> None: ...
    def sign(self, paths: list[str], ttl: int) -> dict[str, str]: ...
    def remove(self, paths: list[str]) -> None: ...


class SupabaseStorage:
    """Talks to the PRIVATE bucket with the server-side service-role key."""

    def __init__(self, client, bucket: str, base_url: str):
        self._client, self._bucket_name, self._base = client, bucket, base_url.rstrip("/")

    def _bucket(self):
        return self._client.storage.from_(self._bucket_name)

    def upload(self, path, data, content_type):
        self._bucket().upload(path, data, {"content-type": content_type, "upsert": "false"})

    def sign(self, paths, ttl):
        out = {}
        for item in self._bucket().create_signed_urls(paths, ttl) or []:
            url = item.get("signedURL") or item.get("signedUrl")
            if url and not item.get("error"):
                # Some client versions return a relative URL; make it absolute either way.
                out[item["path"]] = url if url.startswith("http") else f"{self._base}/storage/v1{url}"
        return out

    def remove(self, paths):
        self._bucket().remove(paths)


_backend: StorageBackend | None = None


def set_backend(backend: StorageBackend | None) -> None:
    global _backend
    _backend = backend


def get_backend() -> StorageBackend:
    global _backend
    if _backend is None:
        cfg = load_config()
        _backend = SupabaseStorage(db.get_client(), cfg.bucket, cfg.supabase_url)
    return _backend


# ---------------------------------------------------------------- validation
def process_image(data: bytes) -> bytes:
    """Return clean JPEG bytes, or raise UploadError with a friendly message."""
    if not data:
        raise UploadError("That file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise UploadError(f"That photo is too large (max {MAX_UPLOAD_BYTES // (1024 * 1024)} MB).")
    try:
        probe = Image.open(io.BytesIO(data))
        if probe.format not in ALLOWED_FORMATS:
            raise UploadError("Please upload a JPG, PNG or WebP photo.")
        if probe.width * probe.height > MAX_PIXELS:
            raise UploadError("That photo has too many pixels - please use a smaller one.")
        probe.verify()                                   # structural check
        img = Image.open(io.BytesIO(data))               # verify() invalidates the object
        img = ImageOps.exif_transpose(img)               # honour phone rotation, then drop metadata
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGBA")
            flat = Image.new("RGB", img.size, (255, 255, 255))
            flat.paste(img, mask=img.getchannel("A"))
            img = flat
        else:
            img = img.convert("RGB")
        img.thumbnail((MAX_SIDE, MAX_SIDE))
        out = io.BytesIO()
        img.save(out, "JPEG", quality=88, optimize=True)  # no exif= argument -> metadata stripped
        return out.getvalue()
    except UploadError:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError, SyntaxError):
        raise UploadError("We couldn't read that file as a photo. Please try a different one.") from None


# ---------------------------------------------------------------- operations
def upload_image(token: str | None, data: bytes, kind: str) -> str:
    """Admin only. Returns the stored object path (save it on the product/homepage)."""
    auth.require_admin(token)
    if kind not in KINDS:
        raise UploadError("Unknown image type.")
    jpeg = process_image(data)
    path = f"{kind}/{uuid.uuid4().hex}.jpg"
    try:
        get_backend().upload(path, jpeg, "image/jpeg")
    except Exception as exc:  # noqa: BLE001 - never show provider details to users
        log.error("image upload failed (%s)", type(exc).__name__)
        raise UploadError("The photo couldn't be saved just now. Please try again.") from exc
    return path


def delete_image(token: str | None, path: str | None) -> None:
    """Admin only, best effort: an orphaned file is harmless, a crashed page is not."""
    auth.require_admin(token)
    if not path or not PATH_RE.match(path):
        return
    try:
        get_backend().remove([path])
    except Exception as exc:  # noqa: BLE001
        log.warning("image delete failed (%s)", type(exc).__name__)


def signed_urls(token: str | None, paths, cache: MutableMapping | None = None,
                *, now: float | None = None) -> dict[str, str]:
    """Short-lived URLs for signed-in sessions only. Missing/failed images degrade to placeholders."""
    auth.require_member(token)
    now = time.time() if now is None else now
    cache = {} if cache is None else cache
    wanted = []
    for p in dict.fromkeys(p for p in paths if p):
        if PATH_RE.match(p):
            wanted.append(p)
        else:
            log.warning("ignored image path with unexpected shape")
    result, missing = {}, []
    for p in wanted:
        hit = cache.get(p)
        if hit and hit[1] - 60 > now:                      # reuse until 1 minute before expiry
            result[p] = hit[0]
        else:
            missing.append(p)
    if missing:
        try:
            for p, url in get_backend().sign(missing, SIGNED_URL_SECONDS).items():
                cache[p] = (url, now + SIGNED_URL_SECONDS)
                result[p] = url
        except PermissionDenied:
            raise
        except Exception as exc:  # noqa: BLE001
            log.error("signing image urls failed (%s)", type(exc).__name__)
    return result
