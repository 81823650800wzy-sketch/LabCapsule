import json
from pathlib import Path
import sys
import tempfile
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "desktop"))
from mobile_bridge import MobileBridgeServer


def request(url, method="GET", body=None, token=""):
    payload = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    try:
        with urlopen(Request(url, data=payload, method=method, headers=headers), timeout=4) as value:
            return value.status, json.loads(value.read())
    except HTTPError as error:
        return error.code, json.loads(error.read())


class MobileBridgeTests(unittest.TestCase):
    def test_pair_status_and_claude_delegate(self):
        with tempfile.TemporaryDirectory() as temporary:
            server = MobileBridgeServer(Path(temporary) / "bridge.json",
                                        lambda: {"computer": {"cpu": 17}, "connected": True},
                                        lambda question: {"reply": "Claude:" + question},
                                        lambda question: {"reply": "Web:" + question},
                                        host="127.0.0.1", port=0)
            info = server.start()
            base = f"http://127.0.0.1:{info.port}"
            try:
                code, _ = request(base + "/v1/status")
                self.assertEqual(401, code)
                code, paired = request(base + "/v1/pair", "POST",
                                       {"code": info.pairing_code,
                                        "deviceId": "phone-test", "name": "测试手机"})
                self.assertEqual(200, code)
                token = paired["token"]
                code, status = request(base + "/v1/status", token=token)
                self.assertEqual(200, code)
                self.assertEqual(17, status["context"]["computer"]["cpu"])
                code, result = request(base + "/v1/ask", "POST",
                                       {"question": "分析当前实验"}, token)
                self.assertEqual(200, code)
                self.assertEqual("Claude:分析当前实验", result["result"]["reply"])
                code, research = request(base + "/v1/research", "POST",
                                         {"question": "查找振动标准"}, token)
                self.assertEqual(200, code)
                self.assertEqual("computer-web", research["source"])
                self.assertEqual("Web:查找振动标准", research["result"]["reply"])
                self.assertIn("reference.web", paired["scopes"])
            finally:
                server.stop()

    def test_wrong_pairing_code_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            server = MobileBridgeServer(Path(temporary) / "bridge.json", lambda: {},
                                        lambda _: {}, host="127.0.0.1", port=0)
            info = server.start()
            try:
                code, _ = request(f"http://127.0.0.1:{info.port}/v1/pair", "POST",
                                  {"code": "000000", "deviceId": "phone"})
                self.assertEqual(403, code)
            finally:
                server.stop()


if __name__ == "__main__":
    unittest.main()
