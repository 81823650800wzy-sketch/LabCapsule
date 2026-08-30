"""Fast model/runtime tests for LabCapsule Studio V0.8."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop"))

from interactive_chart import InteractiveMotionChart, MotionPoint  # noqa: E402
from labcapsule_desktop import parse_motion_data_line  # noqa: E402
from pet_agent import PetAgentRuntime, PetSettings, _redact_secrets  # noqa: E402


def point(index: int, value: float) -> MotionPoint:
    return MotionPoint(index, index / 100.0, value, 0, 0, 0, 0, 0,
                       abs(value), 0)


class InteractiveChartTests(unittest.TestCase):
    def test_extrema_decimator_preserves_narrow_peak(self):
        points = [point(index, 100.0 if index == 543 else 0.0) for index in range(2000)]
        reduced = InteractiveMotionChart._decimate_extrema(points, "ax", 120)
        self.assertLessEqual(len(reduced), 244)
        self.assertEqual(max(item.ax for item in reduced), 100.0)
        self.assertIs(reduced[0], points[0])
        self.assertIs(reduced[-1], points[-1])


class DataParserTests(unittest.TestCase):
    def test_valid_motion_record(self):
        fields, timestamp, values = parse_motion_data_line("DATA,1000,1,2,3,4,5,6")
        self.assertEqual(timestamp, 1000)
        self.assertEqual(fields, ["1000", "1", "2", "3", "4", "5", "6"])
        self.assertEqual(values, (1.0, 2.0, 3.0, 4.0, 5.0, 6.0))

    def test_corrupt_or_non_finite_motion_record_is_rejected(self):
        self.assertIsNone(parse_motion_data_line("DATA,broken,1,2,3,4,5,6"))
        self.assertIsNone(parse_motion_data_line("DATA,1,nan,2,3,4,5,6"))
        self.assertIsNone(parse_motion_data_line("DATA,-1,1,2,3,4,5,6"))


class PetRuntimeTests(unittest.TestCase):
    def test_endpoint_validation_requires_https_except_localhost(self):
        PetSettings(endpoint="http://127.0.0.1:11434/v1").validate()
        PetSettings(endpoint="https://api.deepseek.com/v1").validate()
        with self.assertRaises(ValueError):
            PetSettings(endpoint="http://example.com/v1").validate()

    def test_secret_redaction(self):
        value = _redact_secrets("api_key: sk-123456 Bearer abcdefgh password=noop 密码：12345678")
        self.assertNotIn("sk-123456", value)
        self.assertNotIn("abcdefgh", value)
        self.assertNotIn("12345678", value)

    def test_structured_reply_tolerates_json_fence(self):
        parsed = PetAgentRuntime._parse_json('```json\n{"reply":"好","emotion":"happy"}\n```')
        self.assertEqual(parsed["reply"], "好")

    def test_event_schema_has_confirmation_risk(self):
        schema = json.loads((ROOT / "docs" / "pet_event_v1.schema.json").read_text("utf-8"))
        risk = schema["properties"]["payload"]["properties"]["risk"]["enum"]
        self.assertEqual(risk, ["passive", "confirm", "blocked"])


if __name__ == "__main__":
    unittest.main()
