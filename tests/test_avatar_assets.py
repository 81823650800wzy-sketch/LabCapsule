"""Network avatar security, cache and animation tests."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
import sys
import tempfile
import threading
import unittest

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop"))

from avatar_assets import (  # noqa: E402
    DICEBEAR_CC0_PRESETS,
    MAX_DOWNLOAD_BYTES,
    clear_cached_avatar,
    decode_avatar,
    dicebear_url,
    download_avatar,
    load_cached_avatar,
    validate_avatar_url,
)


def encoded_image(image_format: str, animated: bool = False) -> bytes:
    output = BytesIO()
    first = Image.new("RGBA", (96, 128), "#67e8f9")
    if animated:
        second = Image.new("RGBA", (96, 128), "#facc15")
        first.save(output, format=image_format, save_all=True, append_images=[second],
                   duration=[45, 125], loop=0)
    else:
        first.save(output, format=image_format)
    return output.getvalue()


PNG = encoded_image("PNG")
GIF = encoded_image("GIF", animated=True)


class AvatarHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/avatar.png")
            self.end_headers()
            return
        if self.path == "/large":
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(MAX_DOWNLOAD_BYTES + 1))
            self.end_headers()
            return
        if self.path == "/html":
            payload, content_type = b"<html>not an avatar</html>", "text/html"
        elif self.path == "/avatar.gif":
            payload, content_type = GIF, "image/gif"
        else:
            payload, content_type = PNG, "image/png"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_args):
        return


class AvatarAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), AvatarHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.root_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.cache = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_url_policy_and_cc0_generator(self):
        self.assertEqual(validate_avatar_url(self.root_url + "/avatar.png"),
                         self.root_url + "/avatar.png")
        with self.assertRaises(ValueError):
            validate_avatar_url("http://example.com/avatar.png")
        with self.assertRaises(ValueError):
            validate_avatar_url("file:///tmp/avatar.png")
        with self.assertRaises(ValueError):
            validate_avatar_url("https://user:pass@example.com/avatar.png")
        for style in DICEBEAR_CC0_PRESETS.values():
            self.assertIn(f"/10.x/{style}/png?", dicebear_url(style, "实验 01"))

    def test_png_redirect_cache_and_integrity(self):
        progress = []
        asset = download_avatar(self.root_url + "/redirect", self.cache, progress.append)
        self.assertEqual(asset.format, "PNG")
        self.assertEqual((asset.width, asset.height, asset.frames), (96, 128, 1))
        self.assertTrue(asset.final_url.endswith("/avatar.png"))
        self.assertEqual(progress[-1], 100)
        cached = load_cached_avatar(self.cache)
        self.assertIsNotNone(cached)
        self.assertEqual(cached.sha256, asset.sha256)
        Path(asset.path).write_bytes(b"tampered")
        self.assertIsNone(load_cached_avatar(self.cache))

    def test_gif_decode_preserves_frames_and_timing(self):
        asset = download_avatar(self.root_url + "/avatar.gif", self.cache)
        decoded = decode_avatar(asset, 80)
        self.assertEqual(len(decoded.frames), 2)
        # GIF stores delays in 10 ms units; Pillow writes these as 40/120 ms.
        self.assertEqual(decoded.durations_ms, [40, 120])
        self.assertLessEqual(max(decoded.frames[0].size), 80)

    def test_failed_download_does_not_replace_previous_avatar(self):
        original = download_avatar(self.root_url + "/avatar.png", self.cache)
        with self.assertRaises(ValueError):
            download_avatar(self.root_url + "/html", self.cache)
        with self.assertRaises(ValueError):
            download_avatar(self.root_url + "/large", self.cache)
        cached = load_cached_avatar(self.cache)
        self.assertIsNotNone(cached)
        self.assertEqual(cached.sha256, original.sha256)

    def test_clear_removes_current_cache(self):
        download_avatar(self.root_url + "/avatar.png", self.cache)
        clear_cached_avatar(self.cache)
        self.assertIsNone(load_cached_avatar(self.cache))
        self.assertEqual(list(self.cache.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
