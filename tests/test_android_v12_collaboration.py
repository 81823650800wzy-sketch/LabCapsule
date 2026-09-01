from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "android" / "src" / "com" / "labcapsule" / "remote" /
          "MainActivity.java").read_text(encoding="utf-8")


class AndroidV12CollaborationTests(unittest.TestCase):
    def test_update_download_reports_real_progress_and_recovers(self):
        self.assertIn("COLUMN_BYTES_DOWNLOADED_SO_FAR", SOURCE)
        self.assertIn("COLUMN_TOTAL_SIZE_BYTES", SOURCE)
        self.assertIn('putLong("apk_download_id"', SOURCE)
        self.assertIn("pollApkDownload", SOURCE)

    def test_conversations_have_sessions_search_and_distinct_bubbles(self):
        self.assertIn('"assistant_chat_sessions"', SOURCE)
        self.assertIn("createNewConversation", SOURCE)
        self.assertIn("jumpToMatch", SOURCE)
        self.assertIn("messageBubble", SOURCE)
        self.assertIn("Gravity.END", SOURCE)
        self.assertIn("Gravity.START", SOURCE)

    def test_role_cards_are_private_cached_and_partially_applied(self):
        self.assertIn('optBoolean("private", false)', SOURCE)
        self.assertIn("labcapsule-rolecards-v1", SOURCE)
        self.assertIn("previewBase64", SOURCE)
        self.assertIn("sha256Hex", SOURCE)
        self.assertIn("roleReplaceVisual", SOURCE)
        self.assertIn("roleReplacePersona", SOURCE)
        self.assertIn("roleReplaceVoice", SOURCE)
        self.assertIn("extractZipPrefix", SOURCE)

    def test_computer_bridge_requires_pairing_and_keystore_token(self):
        self.assertIn("confirmComputerPairing", SOURCE)
        self.assertIn('secureStore.put("computer_bridge_token"', SOURCE)
        self.assertIn('"/v1/status"', SOURCE)
        self.assertIn('"/v1/ask"', SOURCE)
        self.assertIn("handleComputerAssistantIntent", SOURCE)


if __name__ == "__main__":
    unittest.main()
