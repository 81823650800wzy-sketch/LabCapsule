from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "android" / "src" / "com" / "labcapsule" / "remote" /
          "MainActivity.java").read_text(encoding="utf-8")
MOBILE_BRIDGE = (ROOT / "desktop" / "mobile_bridge.py").read_text(encoding="utf-8")
CLAUDE_BRIDGE = (ROOT / "desktop" / "claude_bridge.py").read_text(encoding="utf-8")
FIRMWARE = (ROOT / "firmware" / "main" / "labcapsule_main.c").read_text(encoding="utf-8")
SENSOR_HUB = (ROOT / "firmware" / "main" / "sensor_hub.c").read_text(encoding="utf-8")


class AndroidV13AiExperimentTests(unittest.TestCase):
    def test_measurement_is_planned_by_real_ai_before_start(self):
        self.assertIn("planExperimentWithAi(q)", SOURCE)
        self.assertIn("callAssistantJson", SOURCE)
        self.assertIn('reference_mode=none|computer_claude|computer_web', SOURCE)
        self.assertIn("尚未向设备下发 START", SOURCE)

    def test_plan_has_strict_sensor_and_sample_safety_bounds(self):
        self.assertIn('!"mpu6050".equalsIgnoreCase', SOURCE)
        self.assertIn("expected > 500_000L", SOURCE)
        self.assertIn("当前固件只允许启动 MPU6050 真实采集", SOURCE)
        self.assertIn("预计样本超过 500000", SOURCE)

    def test_real_i2c_inventory_is_required_before_start(self):
        self.assertIn('putString("detected_sensor_ids"', SOURCE)
        self.assertIn('isDetectedSensor("mpu6050")', SOURCE)
        self.assertIn("真实 I²C 预检未发现 MPU6050", SOURCE)
        self.assertIn('putLong("sensor_inventory_ms"', SOURCE)
        self.assertIn("scannedAt >= preflightStartedAt", SOURCE)

    def test_abort_elapsed_and_live_progress_are_user_visible(self):
        self.assertIn('button("终止实验"', SOURCE)
        self.assertIn('writeBleCommand("ABORT")', SOURCE)
        self.assertIn('sendAction("abort")', SOURCE)
        self.assertIn("experimentClockRunnable", SOURCE)
        self.assertIn("experimentProgressBar", SOURCE)
        self.assertIn("预计 ", SOURCE)
        self.assertIn('"outcome"', SOURCE)
        self.assertIn('wasAborted ? "aborted" : "complete"', SOURCE)

    def test_start_is_confirmed_and_web_reference_is_bounded(self):
        self.assertIn("markExperimentStarted", SOURCE)
        self.assertIn("pendingBleExperimentProtocol", SOURCE)
        self.assertIn("等待设备确认", SOURCE)
        self.assertIn("设备未接受实验 START", SOURCE)
        self.assertIn('"/v1/research"', SOURCE)
        self.assertIn('"reference.web"', MOBILE_BRIDGE)
        self.assertIn('tools="WebSearch,WebFetch"', CLAUDE_BRIDGE)
        self.assertNotIn('tools="Bash', CLAUDE_BRIDGE)

    def test_firmware_recovers_i2c_and_does_not_scan_during_sampling(self):
        self.assertIn("s_mpu_mutex", FIRMWARE)
        self.assertIn("MPU_READ_RETRY", FIRMWARE)
        self.assertIn("offline_store_finish(true)", FIRMWARE)
        self.assertIn("sensor_hub_set_scan_enabled(false)", FIRMWARE)
        self.assertIn("if (!s_scan_enabled)", SENSOR_HUB)
        self.assertIn("xSemaphoreTake(s_bus_mutex", SENSOR_HUB)

    def test_firmware_preflight_uses_a_real_sample_and_recovers_error_state(self):
        self.assertIn("mpu_health_check_and_recover", FIRMWARE)
        self.assertIn("mpu_read_sample(&probe_sample)", FIRMWARE)
        self.assertIn("ERR,MPU_NOT_READY", FIRMWARE)
        self.assertIn("get_state() == STATE_ERROR) set_state(STATE_READY)", FIRMWARE)

    def test_gif_refresh_is_paused_while_experiment_owns_display(self):
        self.assertIn("get_state() == STATE_RECORDING", FIRMWARE)
        self.assertIn("get_state() != STATE_RECORDING", FIRMWARE)
        self.assertIn("persisted clip marked as playing", FIRMWARE)


if __name__ == "__main__":
    unittest.main()
