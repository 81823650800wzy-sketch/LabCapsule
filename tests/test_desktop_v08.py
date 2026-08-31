"""Fast model/runtime tests for LabCapsule Studio V0.8."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop"))

from interactive_chart import InteractiveMotionChart, MotionPoint  # noqa: E402
from labcapsule_desktop import SerialLink, parse_motion_data_line  # noqa: E402
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

    def test_serial_write_all_handles_short_driver_writes(self):
        class PartialPort:
            def __init__(self):
                self.data = bytearray()

            def write(self, payload):
                piece = bytes(payload[:3])
                self.data.extend(piece)
                return len(piece)

        port = PartialPort()
        SerialLink._write_all(port, b"0123456789")
        self.assertEqual(bytes(port.data), b"0123456789")


class PetRuntimeTests(unittest.TestCase):
    def test_endpoint_validation_requires_https_except_localhost(self):
        PetSettings(endpoint="http://127.0.0.1:11434/v1").validate()
        PetSettings(endpoint="https://api.deepseek.com/v1").validate()
        with self.assertRaises(ValueError):
            PetSettings(endpoint="http://example.com/v1").validate()

    def test_deepseek_legacy_model_is_migrated_but_custom_model_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "pet_settings.json"
            with patch("pet_agent.CONFIG_PATH", config):
                config.write_text(json.dumps({
                    "endpoint": "https://api.deepseek.com/v1",
                    "model": "deepseek-chat",
                }), encoding="utf-8")
                self.assertEqual(PetSettings.load().model, "deepseek-v4-flash")

                config.write_text(json.dumps({
                    "endpoint": "https://llm.example.com/v1",
                    "model": "deepseek-chat",
                }), encoding="utf-8")
                self.assertEqual(PetSettings.load().model, "deepseek-chat")

    def test_secret_redaction(self):
        value = _redact_secrets("api_key: sk-123456 Bearer abcdefgh password=noop 密码：12345678")
        self.assertNotIn("sk-123456", value)
        self.assertNotIn("abcdefgh", value)
        self.assertNotIn("12345678", value)

    def test_structured_reply_tolerates_json_fence(self):
        parsed = PetAgentRuntime._parse_json('```json\n{"reply":"好","emotion":"happy"}\n```')
        self.assertEqual(parsed["reply"], "好")

    def test_empty_model_reply_retries_without_old_conversation(self):
        runtime = PetAgentRuntime(PetSettings(
            api_key="test-key", model="deepseek-v4-flash", remember=False,
        ))
        runtime.memory.messages = [
            {"role": "user", "content": "旧问题"},
            {"role": "assistant", "content": "旧格式回答"},
        ]
        requests = []

        def fake_request(body):
            requests.append(body)
            if len(requests) == 1:
                return {"choices": [{"message": {"content": ""}}]}
            return {"choices": [{"message": {"content": json.dumps({
                "reply": "电脑状态正常。", "emotion": "speaking",
                "device_notice": True, "action": "TALK",
            }, ensure_ascii=False)}}]}

        runtime._request_chat = fake_request
        reply = runtime.chat("电脑现在怎么样？", {"computer": {"cpu_percent": 12}})

        self.assertEqual(reply.text, "电脑状态正常。")
        self.assertEqual(reply.action, "TALK")
        self.assertEqual(len(requests), 2)
        retry_contents = [item["content"] for item in requests[1]["messages"]]
        self.assertNotIn("旧问题", retry_contents)
        self.assertIn("电脑现在怎么样？", retry_contents)

    def test_event_schema_has_confirmation_risk(self):
        schema = json.loads((ROOT / "docs" / "pet_event_v1.schema.json").read_text("utf-8"))
        risk = schema["properties"]["payload"]["properties"]["risk"]["enum"]
        self.assertEqual(risk, ["passive", "confirm", "blocked"])


if __name__ == "__main__":
    unittest.main()
