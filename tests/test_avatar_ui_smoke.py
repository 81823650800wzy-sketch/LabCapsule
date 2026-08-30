"""Tk integration smoke test for the network avatar feature."""

from __future__ import annotations

import hashlib
from pathlib import Path
import sys
import tempfile
import unittest

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop"))

from avatar_assets import AvatarAsset, decode_avatar  # noqa: E402
import labcapsule_desktop as desktop_app  # noqa: E402


class AvatarUiSmokeTests(unittest.TestCase):
    def test_stage_overlay_library_and_screen_studio_handoff(self):
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary) / "avatar-cache"
            desktop_app.AVATAR_CACHE_DIR = cache
            source = Path(temporary) / "avatar.png"
            Image.new("RGBA", (96, 128), "#67e8f9").save(source)
            blob = source.read_bytes()
            asset = AvatarAsset(
                path=str(source), source_url="https://example.com/avatar.png",
                final_url="https://example.com/avatar.png",
                sha256=hashlib.sha256(blob).hexdigest(), format="PNG",
                content_type="image/png", bytes=len(blob), width=96,
                height=128, frames=1,
            )
            decoded = decode_avatar(asset, 220)
            app = desktop_app.Studio()
            app.withdraw()
            try:
                app._apply_avatar_decoded(decoded, "UI 自动测试")
                self.assertTrue(app.pet_avatar.has_custom_avatar)
                app.show_pet_overlay()
                self.assertTrue(app.pet_overlay.avatar.has_custom_avatar)
                app.show_avatar_library()
                app.update_idletasks()
                self.assertTrue(app.avatar_library_window.winfo_exists())
                app.send_avatar_to_screen_studio()
                self.assertEqual(app.media_path, str(source))
                self.assertFalse(app.pet_path)
                app.restore_vector_avatar()
                self.assertFalse(app.pet_avatar.has_custom_avatar)
            finally:
                app.close_app()


if __name__ == "__main__":
    unittest.main()
