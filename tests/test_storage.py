"""Image pipeline + signed URLs. The storage BACKEND is a mock (FakeStorage): these tests prove OUR logic
(validation, authorization, caching, failure handling), not Supabase Storage itself."""
import io
import logging

import pytest
from PIL import Image

from wishlist import storage
from wishlist.security import PermissionDenied
from wishlist.storage import PATH_RE, UploadError, process_image


def make_image(fmt="PNG", size=(300, 200), mode="RGB", exif=False, color=(200, 80, 120)):
    img = Image.new(mode, size, color)
    buf = io.BytesIO()
    kwargs = {}
    if exif:
        ex = Image.Exif()
        ex[0x010F] = "SecretCameraMaker"          # Make
        ex[0x8825] = {1: "N", 2: (17.0, 22.0, 0.0)}  # pretend GPS block
        kwargs["exif"] = ex
    img.save(buf, fmt, **kwargs)
    return buf.getvalue()


# ------------------------------------------------------------- validation (pure)
@pytest.mark.parametrize("fmt", ["PNG", "JPEG", "WEBP"])
def test_accepts_allowed_formats_and_returns_jpeg(fmt):
    out = Image.open(io.BytesIO(process_image(make_image(fmt))))
    assert out.format == "JPEG" and out.size == (300, 200)


def test_transparent_png_is_flattened_on_white():
    out = Image.open(io.BytesIO(process_image(make_image("PNG", mode="RGBA", color=(0, 0, 0, 0))))).convert("RGB")
    assert out.getpixel((5, 5)) == (255, 255, 255) or min(out.getpixel((5, 5))) > 245


def test_exif_metadata_including_gps_is_stripped():
    original = make_image("JPEG", exif=True)
    assert Image.open(io.BytesIO(original)).getexif().get(0x010F) == "SecretCameraMaker"   # precondition
    cleaned = Image.open(io.BytesIO(process_image(original)))
    assert dict(cleaned.getexif()) == {} and b"SecretCameraMaker" not in process_image(original)


def test_large_images_are_downscaled():
    out = Image.open(io.BytesIO(process_image(make_image("PNG", size=(3200, 2400)))))
    assert max(out.size) == storage.MAX_SIDE


@pytest.mark.parametrize("data,reason", [
    (b"", "empty"), (b"not an image at all", "garbage"), (b"<svg xmlns='http://www.w3.org/2000/svg'/>", "svg"),
    (make_image("GIF"), "gif"), (b"%PDF-1.4 fake", "pdf"), (make_image("PNG")[:40], "truncated"),
])
def test_rejects_non_photos(data, reason):
    with pytest.raises(UploadError):
        process_image(data)


def test_rejects_files_over_the_size_limit(monkeypatch):
    monkeypatch.setattr(storage, "MAX_UPLOAD_BYTES", 1000)
    with pytest.raises(UploadError, match="too large"):
        process_image(make_image("PNG", size=(400, 400)) + b"0" * 2000)


def test_rejects_absurd_pixel_counts(monkeypatch):
    monkeypatch.setattr(storage, "MAX_PIXELS", 100)
    with pytest.raises(UploadError, match="pixels"):
        process_image(make_image("PNG", size=(50, 50)))


# ------------------------------------------------------------- upload authorization + failures
def test_only_admin_can_upload(pg, tokens, fake_storage):
    for tok in (tokens.mom, tokens.dad, None, "forged"):
        with pytest.raises(PermissionDenied):
            storage.upload_image(tok, make_image(), "product")
    assert fake_storage.uploads == []                       # nothing reached storage


def test_admin_upload_stores_a_clean_jpeg_under_a_random_path(pg, tokens, fake_storage):
    p1 = storage.upload_image(tokens.admin, make_image("PNG"), "portrait")
    p2 = storage.upload_image(tokens.admin, make_image("PNG"), "product")
    assert PATH_RE.match(p1) and p1.startswith("portrait/") and p2.startswith("product/") and p1 != p2
    assert fake_storage.uploads[0] == (p1, "image/jpeg")
    assert Image.open(io.BytesIO(fake_storage.files[p1])).format == "JPEG"


def test_bad_kind_and_bad_file_are_rejected_before_storage(pg, tokens, fake_storage):
    with pytest.raises(UploadError):
        storage.upload_image(tokens.admin, make_image(), "../../evil")
    with pytest.raises(UploadError):
        storage.upload_image(tokens.admin, b"junk", "product")
    assert fake_storage.uploads == []


def test_backend_failure_gives_a_safe_message_and_no_leak(pg, tokens, fake_storage, caplog):
    fake_storage.fail_upload = True
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(UploadError) as err:
            storage.upload_image(tokens.admin, make_image(), "product")
    assert "secret-details" not in str(err.value) and "couldn't be saved" in str(err.value)
    assert "secret-details" not in caplog.text and "RuntimeError" in caplog.text     # class name only


def test_only_admin_can_delete_and_only_well_formed_paths(pg, tokens, fake_storage):
    path = "product/" + "a" * 32 + ".jpg"
    with pytest.raises(PermissionDenied):
        storage.delete_image(tokens.mom, path)
    storage.delete_image(tokens.admin, "../../etc/passwd")
    storage.delete_image(tokens.admin, path)
    assert fake_storage.removed == [path]


# ------------------------------------------------------------- signed URLs
P1, P2 = "product/" + "a" * 32 + ".jpg", "product/" + "b" * 32 + ".jpg"


def test_signed_urls_require_a_signed_in_member(pg, creds, fake_storage):
    from wishlist import auth
    nameless = auth.login("Gift Giver", creds.family).token
    for tok in (None, "forged", nameless):
        with pytest.raises(PermissionDenied):
            storage.signed_urls(tok, [P1])
    assert fake_storage.sign_calls == []


def test_signed_urls_are_cached_until_near_expiry(pg, tokens, fake_storage):
    cache = {}
    first = storage.signed_urls(tokens.mom, [P1, P2], cache, now=1000)
    again = storage.signed_urls(tokens.mom, [P1, P2], cache, now=1100)
    assert first == again and len(fake_storage.sign_calls) == 1                 # no second API call
    later = storage.signed_urls(tokens.mom, [P1], cache, now=1000 + storage.SIGNED_URL_SECONDS)
    assert len(fake_storage.sign_calls) == 2 and later[P1] != first[P1]         # re-signed after expiry window


def test_unexpected_paths_are_never_signed(pg, tokens, fake_storage):
    out = storage.signed_urls(tokens.mom, ["../secret.jpg", "product/short.jpg", "other/" + "a" * 32 + ".jpg", None, P1])
    assert list(out) == [P1] and fake_storage.sign_calls == [[P1]]


def test_signing_failure_degrades_gracefully(pg, tokens, fake_storage):
    fake_storage.fail_sign = True
    assert storage.signed_urls(tokens.mom, [P1]) == {}        # page renders placeholders instead of crashing


def test_supabase_adapter_normalises_relative_and_absolute_urls():
    class B:
        def create_signed_urls(self, paths, ttl):
            return [{"path": paths[0], "signedURL": "/object/sign/b/x?token=1", "error": None},
                    {"path": paths[1], "signedURL": "https://h/x?token=2", "error": None},
                    {"path": paths[2], "signedURL": None, "error": "not found"}]

    class C:
        class storage:
            @staticmethod
            def from_(name): return B()

    out = storage.SupabaseStorage(C, "bucket", "https://proj.supabase.co/").sign(["a", "b", "c"], 600)
    assert out == {"a": "https://proj.supabase.co/storage/v1/object/sign/b/x?token=1", "b": "https://h/x?token=2"}
