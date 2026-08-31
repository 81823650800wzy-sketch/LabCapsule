import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop"))

from claude_bridge import ClaudeBridge


class ClaudeBridgeTests(unittest.TestCase):
    def test_complex_router_avoids_simple_status_question(self):
        self.assertFalse(ClaudeBridge.should_delegate("电脑现在怎么样？"))
        self.assertTrue(ClaudeBridge.should_delegate("请全面分析当前实验并生成报告"))
        self.assertTrue(ClaudeBridge.should_delegate("普通问题", model_requested=True))

    def test_json_output_is_bounded_and_redacted(self):
        raw = json.dumps({"result": "结论。API Key: sk-test-secret-value"})
        parsed = ClaudeBridge.parse_output(raw)
        self.assertIn("[已隐藏]", parsed)
        self.assertNotIn("sk-test-secret-value", parsed)

    def test_tool_call_markup_is_never_exposed_as_pet_text(self):
        raw = json.dumps({"result": "<tool_calls><invoke name=\"request_user_input\"></invoke></tool_calls>"})
        with self.assertRaisesRegex(ValueError, "安全拦截"):
            ClaudeBridge.parse_output(raw)

    def test_missing_cli_returns_clear_error(self):
        bridge = ClaudeBridge(executable=Path("Z:/missing/claude.exe"))
        result = bridge.process("复杂任务", {"connected": False})
        self.assertFalse(result.ok)
        self.assertIn("Claude", result.error)


if __name__ == "__main__":
    unittest.main()
