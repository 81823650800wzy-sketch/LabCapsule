"""Live2D consent and packaged/source player command regression tests."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop"))

from live2d_runtime import (CORE_URL, has_live2d_consent, player_command,
                            save_live2d_consent, write_live2d_action)  # noqa: E402


class Live2DRuntimeTests(unittest.TestCase):
    def test_consent_is_bound_to_schema_and_official_core_url(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "consent.json"
            self.assertFalse(has_live2d_consent(path))
            save_live2d_consent(path)
            self.assertTrue(has_live2d_consent(path))
            raw = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(raw["schemaVersion"], 1)
            self.assertEqual(raw["coreUrl"], CORE_URL)
            raw["coreUrl"] = "https://example.invalid/core.js"
            path.write_text(json.dumps(raw), encoding="utf-8")
            self.assertFalse(has_live2d_consent(path))

    def test_source_and_frozen_commands_do_not_use_shell(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = root / "pet.model3.json"
            model.write_text("{}", encoding="utf-8")
            source = player_command(model, "stage", root, "python.exe", frozen=False)
            frozen = player_command(model, "overlay", root, "LabCapsuleStudio.exe", frozen=True)
            self.assertEqual(source, ["python.exe", str(root / "live2d_player.py"),
                                      str(model.resolve()), "--mode", "stage"])
            self.assertEqual(frozen, ["LabCapsuleStudio.exe", "--live2d-player",
                                      str(model.resolve()), "--mode", "overlay"])
            with self.assertRaises(ValueError):
                player_command(model, "invalid", root, frozen=False)

    def test_control_action_is_atomic_and_allowlisted(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "control.json"
            revision = write_live2d_action("happy", "bounce", path)
            raw = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(raw["revision"], revision)
            self.assertEqual(raw["emotion"], "HAPPY")
            self.assertEqual(raw["action"], "BOUNCE")
            write_live2d_action("bad/value", "delete files", path)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["action"], "TALK")

    def test_player_command_accepts_explicit_control_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = root / "pet.model3.json"
            control = root / "control.json"
            model.write_text("{}", encoding="utf-8")
            command = player_command(model, "stage", root, "python.exe", frozen=False,
                                     control_path=control)
            self.assertEqual(command[-2:], ["--control", str(control.resolve())])


if __name__ == "__main__":
    unittest.main()
