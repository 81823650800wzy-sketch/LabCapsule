from __future__ import annotations

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "android" / "src" / "com" / "labcapsule" / "remote" /
          "MainActivity.java").read_text(encoding="utf-8")
BUILD = (ROOT / "android" / "build-apk.ps1").read_text(encoding="utf-8")


def method_body(name: str, next_name: str) -> str:
    def locate(signature: str, offset: int = 0) -> int:
        positions = []
        for modifier in ("", "static ", "synchronized ", "static synchronized "):
            marker = f"    private {modifier}{signature}"
            position = SOURCE.find(marker, offset)
            if position >= 0:
                positions.append(position)
        if not positions:
            raise AssertionError(f"method signature not found: {signature}")
        return min(positions)

    start = locate(name)
    end = locate(next_name, start + 1)
    return SOURCE[start:end]


class AndroidV11NavigationTests(unittest.TestCase):
    def test_four_primary_sections_are_stable(self):
        self.assertIn('new String[]{"首页", "数据", "桌面", "设置"}', SOURCE)
        shell = method_body("void showSection", "void applyThemePalette")
        self.assertIn("buildHomePage()", shell)
        self.assertIn("buildDataPage()", shell)
        self.assertIn("buildScreenPage()", shell)
        self.assertIn("buildSettingsPage()", shell)

    def test_home_contains_only_avatar_and_conversation(self):
        home = method_body("View buildHomePage", "View buildDevicePage")
        self.assertIn("addMobileLive2dStage", home)
        self.assertIn("conversationSessionsView", home)
        self.assertIn("createNewConversation", home)
        self.assertIn("renderConversationSessions", home)
        self.assertNotIn("aiEndpoint =", home)
        self.assertNotIn("confirmLive2dImport", home)
        self.assertNotIn("快速实验", home)

    def test_every_page_builds_connection_banner(self):
        page = method_body("ScrollView page", "LinearLayout pageRoot")
        self.assertIn("buildConnectionBanner()", page)
        banner = method_body("View buildConnectionBanner", "boolean isDeviceConnected")
        self.assertIn("扫描并连接 BLE", banner)
        self.assertIn("检测局域网设备", banner)

    def test_settings_are_searchable_and_default_collapsed(self):
        settings = method_body("View buildSettingsPage", "void addAiSettingsGroup")
        for call in ("addAiSettingsGroup", "addLive2dSettingsGroup",
                     "addExperimentSettingsGroup", "addDeviceSettingsGroup",
                     "addNetworkSettingsGroup", "addMemorySettingsGroup"):
            self.assertIn(call, settings)
        collapsed = method_body("LinearLayout collapsedGroup", "void filterSettings")
        self.assertIn("body.setVisibility(View.GONE)", collapsed)
        self.assertIn("settingsGroups.add", collapsed)
        self.assertIn("fuzzyContains", SOURCE)


class AndroidV11MeasurementTests(unittest.TestCase):
    def test_ai_intent_selects_mpu_and_executes_protocol(self):
        intent = method_body("boolean handleLocalAssistantIntent", "int extractInteger")
        self.assertIn("震动", intent)
        self.assertIn("振动", intent)
        runner = method_body("void startAiMeasurement", "String inferExperimentName")
        self.assertIn("safeFallbackExperimentPlan", runner)
        self.assertIn('put("duration_seconds", duration)', runner)
        self.assertIn("acceptExperimentPlan", runner)
        planner = method_body("JSONObject validateExperimentPlan", "String experimentPlanSummary")
        self.assertIn('put("sensor", "mpu6050")', planner)
        self.assertIn("estimated_samples", planner)

    def test_calibration_is_applied_before_csv_storage(self):
        calibration = method_body("double[] applyCalibration", "String buildCalibrationSummary")
        self.assertIn("raw[i] - offset", calibration)
        notification = method_body("void handleExperimentNotification", "synchronized void closeLiveCapture")
        self.assertLess(notification.index("applyCalibration(rawAxes)"),
                        notification.index("liveCaptureOutput.write(line"))
        self.assertIn("calibrateFromQuestion", SOURCE)

    def test_chart_has_point_inspection_zoom_pan_and_exports(self):
        chart = SOURCE[SOURCE.index("private final class MotionChartView"):]
        self.assertIn("ScaleGestureDetector", chart)
        self.assertIn("selectPoint", chart)
        self.assertIn("ACTION_MOVE", chart)
        self.assertIn("AX %.4f", chart)
        self.assertIn("exportCurrentChart", SOURCE)
        self.assertIn("exportCurrentCsv", SOURCE)
        self.assertIn("REQUEST_EXPORT_CHART", SOURCE)

    def test_data_is_local_first_then_private_repo_sync(self):
        self.assertIn('new File(getFilesDir(), "live-experiments")', SOURCE)
        self.assertIn('"assistant_chat_history"', SOURCE)
        self.assertIn('"experiment_history"', SOURCE)
        self.assertIn('"memory/devices/" + activeDeviceId', SOURCE)
        self.assertIn('"data/devices/" + activeDeviceId', SOURCE)
        self.assertIn('optBoolean("private", false)', SOURCE)
        self.assertIn('.put("calibration", calibration)', SOURCE)
        self.assertIn("15L * 60L * 1000L", SOURCE)

    def test_build_metadata_is_v11(self):
        self.assertRegex(BUILD, r"--version-code\s+130")
        self.assertIn("--version-name '1.3.0'", BUILD)
        self.assertIn("LabCapsule-1.3.0.apk", BUILD)


if __name__ == "__main__":
    unittest.main()
