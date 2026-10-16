"""Image flows of the admin layer. Storage backend is a MOCK (FakeStorage); database is real local PostgreSQL."""
import io

import pytest
from PIL import Image

from wishlist import admin, content, storage
from wishlist.security import ValidationError
from wishlist.storage import UploadError


def png(size=(200, 150)):
    buf = io.BytesIO(); Image.new("RGB", size, (200, 90, 130)).save(buf, "PNG"); return buf.getvalue()


def test_product_image_upload_replace_and_cleanup(pg, tokens, fake_storage):
    pid = admin.save_product(tokens.admin, name="Bag", image=png())
    first = pg.sql("select image_path from products where id=%s", [pid])[0][0]
    assert first in fake_storage.files and first.startswith("product/")
    admin.save_product(tokens.admin, product_id=pid, name="Bag", image=png((300, 300)))
    second = pg.sql("select image_path from products where id=%s", [pid])[0][0]
    assert second != first and first in fake_storage.removed and second in fake_storage.files   # old photo removed after DB success


def test_upload_rejection_saves_nothing(pg, tokens, fake_storage):
    with pytest.raises(UploadError):
        admin.save_product(tokens.admin, name="Bad photo", image=b"not an image")
    assert pg.sql("select count(*) from products")[0][0] == 0 and fake_storage.uploads == []


def test_storage_outage_on_upload_saves_nothing(pg, tokens, fake_storage):
    fake_storage.fail_upload = True
    with pytest.raises(UploadError):
        admin.save_product(tokens.admin, name="Outage", image=png())
    assert pg.sql("select count(*) from products")[0][0] == 0


def test_db_rejection_after_upload_removes_the_orphaned_photo(pg, tokens, fake_storage):
    with pytest.raises(ValidationError):
        admin.save_product(tokens.admin, name="x", category_id="11111111-1111-1111-1111-111111111111", image=png())
    assert len(fake_storage.uploads) == 1 and fake_storage.removed == [fake_storage.uploads[0][0]]   # cleaned up


def test_portrait_set_replace_and_remove(pg, creds, tokens, fake_storage):
    admin.set_portrait(tokens.admin, png((400, 500)))
    p1 = content.get_settings(tokens.mom)["homepage"]["portrait_path"]
    assert p1.startswith("portrait/") and p1 in fake_storage.files
    admin.set_portrait(tokens.admin, png((400, 500)))
    p2 = content.get_settings(tokens.mom)["homepage"]["portrait_path"]
    assert p2 != p1 and fake_storage.removed == [p1]
    admin.set_portrait(tokens.admin, None)
    assert content.get_settings(tokens.mom)["homepage"]["portrait_path"] is None and fake_storage.removed == [p1, p2]
    assert content.get_settings(tokens.mom)["homepage"]["heading"] == "Happy 21st Birthday!"       # text untouched (merge, not replace)


def test_failed_portrait_upload_keeps_the_old_one(pg, creds, tokens, fake_storage):
    admin.set_portrait(tokens.admin, png())
    old = content.get_settings(tokens.mom)["homepage"]["portrait_path"]
    with pytest.raises(UploadError):
        admin.set_portrait(tokens.admin, b"junk")
    assert content.get_settings(tokens.mom)["homepage"]["portrait_path"] == old and fake_storage.removed == []


def test_db_failure_after_portrait_upload_cleans_up(pg, tokens, fake_storage, monkeypatch):
    def refuse(*a, **k): raise ValidationError("refused")
    monkeypatch.setattr(admin, "_call", refuse)
    with pytest.raises(ValidationError):
        admin.set_portrait(tokens.admin, png())
    assert fake_storage.removed == [fake_storage.uploads[0][0]]
