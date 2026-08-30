"""Repository skill script integration tests."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "labcapsule-pet-creator" / "scripts" / "create_pet_package.py"


class PetCreatorSkillTests(unittest.TestCase):
    def run_script(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *arguments], capture_output=True,
            text=True, encoding="utf-8", errors="replace", check=False)

    def test_create_then_validate_portable_package(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.png"
            output = root / "created-pet"
            Image.new("RGBA", (120, 160), "#facc15").save(source)
            created = self.run_script(
                "create", "--source", str(source), "--output", str(output),
                "--id", "skill-test", "--name", "Skill 测试员",
                "--persona", "你是统一形象的实验伙伴。", "--license", "CC0-1.0")
            self.assertEqual(created.returncode, 0, created.stderr)
            result = json.loads(created.stdout)
            self.assertTrue(result["valid"])
            self.assertEqual(result["frames"], 1)
            validated = self.run_script("validate", str(output))
            self.assertEqual(validated.returncode, 0, validated.stderr)
            self.assertEqual(json.loads(validated.stdout)["id"], "skill-test")

    def test_invalid_metadata_writes_nothing_and_nonempty_output_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.png"
            Image.new("RGB", (32, 32), "cyan").save(source)
            invalid_output = root / "invalid"
            invalid = self.run_script(
                "create", "--source", str(source), "--output", str(invalid_output),
                "--id", "Bad ID", "--name", "坏包")
            self.assertEqual(invalid.returncode, 2)
            self.assertFalse(invalid_output.exists())
            occupied = root / "occupied"
            occupied.mkdir()
            marker = occupied / "keep.txt"
            marker.write_text("keep", encoding="utf-8")
            refused = self.run_script(
                "create", "--source", str(source), "--output", str(occupied),
                "--id", "safe-pet", "--name", "安全包")
            self.assertEqual(refused.returncode, 2)
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep")

    def test_create_live2d_copies_only_runtime_dependency_graph(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source-runtime"
            (source / "textures").mkdir(parents=True)
            (source / "motions").mkdir()
            (source / "pet.moc3").write_bytes(b"test-moc3")
            Image.new("RGBA", (64, 64), "#67e8f9").save(source / "textures" / "pet.png")
            (source / "motions" / "idle.motion3.json").write_text(
                json.dumps({"Version": 3, "Meta": {}, "Curves": []}), encoding="utf-8")
            (source / "editor-only.cmo3").write_bytes(b"must-not-be-copied")
            model = source / "pet.model3.json"
            model.write_text(json.dumps({
                "Version": 3,
                "FileReferences": {
                    "Moc": "pet.moc3",
                    "Textures": ["textures/pet.png"],
                    "Motions": {"Idle": [{"File": "motions/idle.motion3.json"}]},
                },
            }), encoding="utf-8")
            output = root / "created-live2d"
            created = self.run_script(
                "create-live2d", "--model", str(model), "--output", str(output),
                "--id", "live2d-skill-test", "--name", "动态 Skill 测试员",
                "--license", "test-only")
            self.assertEqual(created.returncode, 0, created.stderr)
            result = json.loads(created.stdout)
            self.assertEqual(result["visualKind"], "live2d")
            self.assertEqual(result["motionCount"], 1)
            self.assertFalse((output / "live2d" / "editor-only.cmo3").exists())
            self.assertTrue((output / "live2d" / "pet.moc3").is_file())
            validated = self.run_script("validate", str(output))
            self.assertEqual(validated.returncode, 0, validated.stderr)


if __name__ == "__main__":
    unittest.main()
