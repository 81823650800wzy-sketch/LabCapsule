import sys
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop"))

from pet_device import (PET_BUBBLE_BYTES, PET_BUBBLE_HEIGHT, PET_BUBBLE_WIDTH,
                        pet_state_command, render_pet_bubble, sanitize_device_reply)


class PetDeviceTests(unittest.TestCase):
    def test_chinese_reply_is_fixed_size_and_non_empty(self):
        payload = render_pet_bubble("设备正常，当前采样率为 200 赫兹。")
        self.assertEqual(len(payload), PET_BUBBLE_BYTES)
        self.assertEqual(PET_BUBBLE_WIDTH * PET_BUBBLE_HEIGHT, len(payload) * 8)
        self.assertGreater(sum(byte.bit_count() for byte in payload), 80)

    def test_long_reply_is_bounded(self):
        first = render_pet_bubble("复杂实验结果" * 100)
        second = render_pet_bubble("复杂实验结果" * 100)
        self.assertEqual(first, second)
        self.assertEqual(len(first), PET_BUBBLE_BYTES)

    def test_secret_is_redacted_before_rendering(self):
        clean = sanitize_device_reply("API Key: sk-test-secret-value 请勿显示")
        self.assertIn("[已隐藏]", clean)
        self.assertNotIn("sk-test-secret-value", clean)

    def test_pet_state_command_is_allowlisted(self):
        self.assertEqual(pet_state_command("happy", "bounce"), "PET,STATE,HAPPY,BOUNCE")
        self.assertEqual(pet_state_command("unknown", "DROP TABLE"),
                         "PET,STATE,SPEAKING,TALK")


if __name__ == "__main__":
    unittest.main()
