"""Test/dev doubles. NOT used in production."""
from __future__ import annotations

import base64
import io
from PIL import Image, ImageDraw


class FakeStorage:
    """In-memory StorageBackend: records calls, can be told to fail. Tests that use it are MOCKED tests."""

    def __init__(self, fail_upload=False, fail_sign=False):
        self.files, self.uploads, self.sign_calls, self.removed = {}, [], [], []
        self.fail_upload, self.fail_sign = fail_upload, fail_sign

    def upload(self, path, data, content_type):
        if self.fail_upload:
            raise RuntimeError("boom: secret-details-from-provider")
        self.files[path] = data
        self.uploads.append((path, content_type))

    def sign(self, paths, ttl):
        if self.fail_sign:
            raise RuntimeError("sign failed")
        self.sign_calls.append(list(paths))
        return {p: f"https://signed.invalid/{p}?token=t{len(self.sign_calls)}" for p in paths}

    def remove(self, paths):
        self.removed += paths


class DevStorage(FakeStorage):
    """Dev harness only: 'signs' to data-URI pastel pictures so the UI can be inspected without Supabase."""

    COLORS = [("#F3D9DE", "#A44E70"), ("#F8E9EB", "#713B50"), ("#FBD5E0", "#B8668A"), ("#EBD3D9", "#8B5A6D")]

    def sign(self, paths, ttl):
        out = {}
        for p in paths:
            idx = sum(map(ord, p)) % len(self.COLORS)
            bg, fg = self.COLORS[idx]
            w, h = (400, 500) if p.startswith("portrait") else (500, 500)
            img = Image.new("RGB", (w, h), bg)
            d = ImageDraw.Draw(img)
            d.ellipse((w * .25, h * .2, w * .75, h * .7), fill=fg)
            buf = io.BytesIO(); img.save(buf, "JPEG", quality=70)
            out[p] = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
        return out
