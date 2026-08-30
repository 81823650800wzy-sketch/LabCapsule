"""Cubism model-folder validation tests without loading the proprietary Core."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop"))

from live2d_models import find_live2d_models, inspect_live2d_model  # noqa: E402
from pet_packages import discover_pet_packages, load_pet_package  # noqa: E402


def make_live2d(folder: Path, stem: str = "sample", motion_count: int = 1) -> Path:
    runtime = folder / "runtime"
    (runtime / "textures").mkdir(parents=True)
    (runtime / "motion").mkdir()
    (runtime / f"{stem}.moc3").write_bytes(b"MOC3-TEST")
    Image.new("RGBA", (128, 128), "#67e8f9").save(runtime / "textures" / "texture_00.png")
    motions = []
    for index in range(motion_count):
        name = f"idle_{index}.motion3.json"
        (runtime / "motion" / name).write_text(
            json.dumps({"Version": 3, "Meta": {}, "Curves": []}), encoding="utf-8")
        motions.append({"File": f"motion/{name}"})
    (runtime / f"{stem}.physics3.json").write_text(
        json.dumps({"Version": 3, "Meta": {}}), encoding="utf-8")
    model = runtime / f"{stem}.model3.json"
    model.write_text(json.dumps({
        "Version": 3,
        "FileReferences": {
            "Moc": f"{stem}.moc3",
            "Textures": ["textures/texture_00.png"],
            "Physics": f"{stem}.physics3.json",
            "Motions": {"Idle": motions},
        },
    }), encoding="utf-8")
    return model


class Live2DModelTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_model_references_texture_physics_and_motion(self):
        model = make_live2d(self.root / "hiyori", "hiyori", 2)
        asset = inspect_live2d_model(model)
        self.assertEqual(asset.name, "hiyori")
        self.assertEqual(asset.motion_count, 2)
        self.assertEqual(asset.motion_groups, ("Idle",))
        self.assertEqual(len(asset.texture_paths), 1)
        self.assertTrue(asset.physics_path.endswith("hiyori.physics3.json"))

    def test_model_rejects_reference_escape(self):
        model = make_live2d(self.root / "bad")
        raw = json.loads(model.read_text(encoding="utf-8"))
        raw["FileReferences"]["Moc"] = "../../outside.moc3"
        model.write_text(json.dumps(raw), encoding="utf-8")
        (self.root / "outside.moc3").write_bytes(b"outside")
        with self.assertRaisesRegex(ValueError, "之外"):
            inspect_live2d_model(model)

    def test_parent_library_discovers_two_nested_models(self):
        make_live2d(self.root / "hiyori_free", "free", 3)
        make_live2d(self.root / "hiyori_pro", "pro", 4)
        packages, errors = discover_pet_packages(self.root)
        self.assertEqual(errors, [])
        self.assertEqual([package.name for package in packages], ["hiyori_free", "hiyori_pro"])
        self.assertTrue(all(package.visual_kind == "live2d" for package in packages))
        self.assertEqual([package.live2d_motion_count for package in packages], [3, 4])

    def test_manifest_can_select_one_live2d_model(self):
        package_folder = self.root / "manifest-pet"
        model = make_live2d(package_folder, "chosen", 2)
        (package_folder / "pet.json").write_text(json.dumps({
            "schemaVersion": 1, "id": "chosen-live2d", "name": "会动的桌宠",
            "live2dModel": str(model.relative_to(package_folder)).replace("\\", "/"),
        }, ensure_ascii=False), encoding="utf-8")
        package = load_pet_package(package_folder)
        self.assertEqual(package.visual_kind, "live2d")
        self.assertEqual(package.live2d_motion_count, 2)
        self.assertTrue(package.visual_source_path.endswith("chosen.model3.json"))

    def test_depth_limited_finder(self):
        model = make_live2d(self.root / "one" / "two" / "three" / "four")
        self.assertEqual(find_live2d_models(self.root, max_depth=2), [])
        self.assertEqual(find_live2d_models(self.root, max_depth=5), [model.resolve()])


if __name__ == "__main__":
    unittest.main()
