import sys
from pathlib import Path
import unittest
import tempfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop"))

from device_transport import BleLink, LanLink, normalize_base_url  # noqa: E402
from labcapsule_desktop import parse_key_value_fields  # noqa: E402
from speech_input import validate_speech_endpoint  # noqa: E402
from experiment_store import ExperimentStore  # noqa: E402


class DeviceTransportV1Tests(unittest.TestCase):
    def test_lan_url_is_host_only_and_never_contains_credentials(self):
        self.assertEqual(normalize_base_url("192.168.1.42"), "http://192.168.1.42")
        with self.assertRaises(ValueError):
            normalize_base_url("http://user:secret@192.168.1.42")
        with self.assertRaises(ValueError):
            normalize_base_url("https://192.168.1.42/api/status")

    def test_commands_map_to_shared_remote_protocol(self):
        self.assertEqual(LanLink._remote_action("PET,STATE,HAPPY,BOUNCE"),
                         "PET_STATE:HAPPY:BOUNCE")
        self.assertEqual(LanLink._remote_action("PET,IDENTITY,live2d-123,PROXY"),
                         "PET_IDENTITY:live2d-123:PROXY")
        self.assertEqual(BleLink._ble_command("START,200,10"), "START:200:10")
        self.assertEqual(BleLink._ble_command("STYLE,1,82,76,100"),
                         "STYLE:1:82:76:100")

    def test_v1_pong_fields_keep_version_separate(self):
        fields = "PONG,LABCAPSULE,1.0.0-alpha,DEVICE=lc-000000000000".split(",")
        self.assertEqual(fields[2], "1.0.0-alpha")
        self.assertEqual(parse_key_value_fields(fields[3:])["DEVICE"],
                         "lc-000000000000")

    def test_speech_endpoint_requires_tls_except_localhost(self):
        self.assertEqual(validate_speech_endpoint("https://api.openai.com/v1"),
                         "https://api.openai.com/v1/audio/transcriptions")
        self.assertEqual(validate_speech_endpoint("http://127.0.0.1:8000/v1"),
                         "http://127.0.0.1:8000/v1/audio/transcriptions")
        with self.assertRaises(ValueError):
            validate_speech_endpoint("http://example.com/v1")

    def test_experiment_store_is_partitioned_by_device(self):
        with tempfile.TemporaryDirectory() as folder:
            store = ExperimentStore(Path(folder))
            session = store.save("lc-000000000000", [["0", "1", "2", "3", "4", "5", "6"]],
                                 200, 10, "2026-09-01T12:00:00+08:00", False, "稳定")
            recent = store.recent("lc-000000000000")
            self.assertEqual(recent[0]["id"], session["id"])
            self.assertEqual(recent[0]["sampleCount"], 1)
            self.assertTrue((Path(folder) / "experiments" / "lc-000000000000" /
                             f"{session['id']}.csv").is_file())


if __name__ == "__main__":
    unittest.main()
