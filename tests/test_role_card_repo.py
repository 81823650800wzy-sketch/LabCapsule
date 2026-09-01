import json
from pathlib import Path
import sys
import tempfile
import unittest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "desktop"))
from pet_packages import load_pet_package
from role_card_repo import apply_role_card, build_role_card, read_role_manifest


class RoleCardTests(unittest.TestCase):
    def test_build_and_partial_apply_live2d_bundle(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = root / "source"
            package.mkdir()
            (package / "model.model3.json").write_text(json.dumps({
                "Version": 3, "FileReferences": {"Moc": "model.moc3",
                "Textures": ["texture.png"]}}), encoding="utf-8")
            (package / "model.moc3").write_bytes(b"MOC3")
            Image.new("RGBA", (8, 8), "red").save(package / "texture.png")
            (package / "persona.txt").write_text("严谨的 Hiyori", encoding="utf-8")
            (package / "pet.json").write_text(json.dumps({
                "schemaVersion": 1, "id": "hiyori-test", "name": "Hiyori",
                "live2dModel": "model.model3.json", "personaFile": "persona.txt"}),
                encoding="utf-8")
            preview = root / "preview.png"
            Image.new("RGB", (30, 40), "yellow").save(preview)
            pet = load_pet_package(package)
            bundle = root / "card.zip"
            item = build_role_card(pet, pet.persona, preview, None, bundle)
            self.assertEqual(item["sha256"], item["sha256"].lower())
            self.assertEqual("hiyori-test", read_role_manifest(bundle)["id"])
            target = root / "applied"
            manifest = apply_role_card(bundle, target, True, True, False)
            self.assertEqual("hiyori-test", manifest["id"])
            restored = load_pet_package(target)
            self.assertEqual("live2d", restored.visual_kind)
            self.assertEqual("严谨的 Hiyori", restored.persona)


if __name__ == "__main__":
    unittest.main()
