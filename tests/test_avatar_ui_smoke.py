"""Tk integration smoke test for unified local and network avatar behavior."""

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
from pet_packages import PetPackage  # noqa: E402


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
            original_selected_pet_package = desktop_app.selected_pet_package
            desktop_app.selected_pet_package = lambda: None
            app = desktop_app.Studio()
            app.withdraw()
            try:
                package = PetPackage(
                    package_id="ui-smoke", name="统一测试员", folder=temporary,
                    avatar_path=str(source), persona="你是统一形象的实验测试伙伴。",
                    greeting="统一链路已就绪。", license="CC0-1.0")
                app._apply_pet_package_decoded(package, decoded, persist=False)
                self.assertTrue(app.pet_avatar.has_custom_avatar)
                self.assertEqual(app.pet_name_var.get(), "统一测试员")
                self.assertIn("统一形象", app.pet_persona.get("1.0", "end"))
                app.show_pet_overlay()
                self.assertTrue(app.pet_overlay.avatar.has_custom_avatar)
                app.show_avatar_library()
                app.update_idletasks()
                self.assertTrue(app.avatar_library_window.winfo_exists())
                self.assertEqual(app.pet_package_box.master.cget("text"),
                                 "本地统一桌宠角色包")
                app.send_avatar_to_screen_studio()
                self.assertEqual(app.media_path, str(source))
                self.assertFalse(app.pet_path)
                app.restore_vector_avatar()
                self.assertFalse(app.pet_avatar.has_custom_avatar)
            finally:
                app.close_app()
                desktop_app.selected_pet_package = original_selected_pet_package

    def test_live2d_package_uses_stage_and_overlay_without_raster_handoff(self):
        original_selected_pet_package = desktop_app.selected_pet_package
        desktop_app.selected_pet_package = lambda: None
        app = desktop_app.Studio()
        app.withdraw()
        launched: list[str] = []
        try:
            package = PetPackage(
                package_id="live2d-smoke", name="动态测试员", folder=str(ROOT),
                avatar_path="", persona="你是动态实验伙伴。", greeting="动作链路已就绪。",
                license="test-only", visual_kind="live2d",
                live2d_model_path=str(ROOT / "fixtures" / "pet.model3.json"),
                live2d_motion_count=8,
            )
            app._launch_live2d_player = lambda _package, mode: launched.append(mode)
            app._activate_live2d_package(package, persist=False)
            self.assertIs(app.active_pet_package, package)
            self.assertIsNone(app.avatar_decoded)
            self.assertEqual(app.pet_name_var.get(), "动态测试员")
            self.assertIn("8 个动作", app.pet_avatar_source_label.cget("text"))
            self.assertEqual(launched, ["stage"])
            app.show_pet_overlay()
            self.assertEqual(launched, ["stage", "overlay"])
        finally:
            app.close_app()
            desktop_app.selected_pet_package = original_selected_pet_package


if __name__ == "__main__":
    unittest.main()
