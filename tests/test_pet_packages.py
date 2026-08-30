"""Unified pet-package parser, discovery and persistence tests."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop"))

from pet_packages import (  # noqa: E402
    avatar_asset_for_package,
    clear_selected_pet,
    discover_pet_packages,
    load_pet_package,
    save_selected_pet,
    selected_pet_package,
)


def make_package(folder: Path, package_id: str = "test-pet", name: str = "测试桌宠") -> Path:
    folder.mkdir(parents=True)
    Image.new("RGBA", (96, 128), "#facc15").save(folder / "avatar.png")
    (folder / "persona.txt").write_text("你是严谨、友善的实验伙伴。", encoding="utf-8")
    (folder / "pet.json").write_text(json.dumps({
        "schemaVersion": 1,
        "id": package_id,
        "name": name,
        "avatar": "avatar.png",
        "personaFile": "persona.txt",
        "greeting": "准备开始可靠实验。",
        "author": "LabCapsule Test",
        "license": "CC0-1.0",
    }, ensure_ascii=False), encoding="utf-8")
    return folder


class PetPackageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_manifest_package_loads_profile_and_canonical_avatar(self):
        package = load_pet_package(make_package(self.root / "pet-a"))
        self.assertEqual(package.package_id, "test-pet")
        self.assertEqual(package.name, "测试桌宠")
        self.assertIn("严谨", package.persona)
        self.assertFalse(package.inferred)
        asset = avatar_asset_for_package(package)
        self.assertEqual((asset.width, asset.height, asset.frames), (96, 128, 1))

    def test_library_discovers_immediate_package_folders(self):
        make_package(self.root / "one", "pet-one", "一号")
        make_package(self.root / "two", "pet-two", "二号")
        (self.root / "unrelated").mkdir()
        packages, errors = discover_pet_packages(self.root)
        self.assertEqual([item.package_id for item in packages], ["pet-one", "pet-two"])
        self.assertEqual(errors, [])

    def test_zero_config_folder_requires_exactly_one_image(self):
        folder = self.root / "simple-pet"
        folder.mkdir()
        Image.new("RGB", (64, 64), "cyan").save(folder / "avatar.gif")
        package = load_pet_package(folder)
        self.assertTrue(package.inferred)
        self.assertEqual(package.name, "simple-pet")
        Image.new("RGB", (64, 64), "yellow").save(folder / "other.png")
        with self.assertRaisesRegex(ValueError, "多个形象文件"):
            load_pet_package(folder)

    def test_manifest_rejects_path_escape_and_bad_id(self):
        outside = self.root / "outside.png"
        Image.new("RGB", (32, 32), "red").save(outside)
        folder = self.root / "bad"
        folder.mkdir()
        (folder / "pet.json").write_text(json.dumps({
            "schemaVersion": 1, "id": "Bad ID", "name": "坏包", "avatar": "../outside.png",
        }, ensure_ascii=False), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "id 只能"):
            load_pet_package(folder)
        raw = json.loads((folder / "pet.json").read_text("utf-8"))
        raw["id"] = "bad-pet"
        (folder / "pet.json").write_text(json.dumps(raw), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "文件夹之外"):
            load_pet_package(folder)

    def test_invalid_utf8_and_long_name_are_isolated_library_errors(self):
        good = make_package(self.root / "good", "good-pet", "正常桌宠")
        bad_text = make_package(self.root / "bad-text", "bad-text", "坏文本")
        (bad_text / "persona.txt").write_bytes(b"\xff\xfe")
        long_name = make_package(self.root / "long-name", "long-name", "名称")
        manifest = json.loads((long_name / "pet.json").read_text(encoding="utf-8"))
        manifest["name"] = "过" * 25
        (long_name / "pet.json").write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        packages, errors = discover_pet_packages(self.root)
        self.assertEqual([item.folder for item in packages], [str(good.resolve())])
        self.assertEqual(len(errors), 2)
        self.assertTrue(any("UTF-8" in error for error in errors))
        self.assertTrue(any("1–24" in error for error in errors))

    def test_selected_package_round_trip_and_clear(self):
        package = load_pet_package(make_package(self.root / "selected"))
        selection = self.root / "state" / "selected_pet.json"
        save_selected_pet(package, selection)
        restored = selected_pet_package(selection)
        self.assertIsNotNone(restored)
        self.assertEqual(restored.package_id, package.package_id)
        clear_selected_pet(selection)
        self.assertIsNone(selected_pet_package(selection))


if __name__ == "__main__":
    unittest.main()
