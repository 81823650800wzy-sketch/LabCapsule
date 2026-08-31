"""Local-only WebView2 host for a validated Cubism model3 runtime folder."""

from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import sys
import threading
from urllib.parse import unquote, urlparse

from live2d_models import inspect_live2d_model


CORE_URL = "https://cubism.live2d.com/sdk-web/core/05/live2dcubismcore.min.js"
OFFICIAL_FILE_GUIDE = "https://docs.live2d.com/en/cubism-editor-manual/file-type-and-extension/"
OFFICIAL_LICENSE = "https://www.live2d.com/en/sdk/license/expandable/"


def resource_path(*parts: str) -> Path:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return root.joinpath(*parts)


def player_html() -> bytes:
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>LabCapsule Live2D</title>
  <style>
    :root {{ color-scheme: dark; font-family: "Microsoft YaHei UI", sans-serif; }}
    * {{ box-sizing: border-box; }}
    html, body {{ width: 100%; height: 100%; margin: 0; overflow: hidden; background: #080c12; }}
    body::before {{ content: ""; position: fixed; inset: 0; pointer-events: none;
      background: radial-gradient(circle at 50% 35%, #162433 0, #080c12 66%); }}
    #live2d-canvas {{ position: fixed; inset: 0; width: 100%; height: 100%; }}
    #hud {{ position: fixed; left: 12px; right: 12px; bottom: 10px; z-index: 2;
      padding: 9px 11px; border: 1px solid #67e8f9; background: rgba(8,12,18,.72);
      backdrop-filter: blur(12px); border-radius: 14px; }}
    #status {{ color: #67e8f9; font-size: 12px; }}
    #status.error {{ color: #fb7185; }}
    #motion-bar {{ display: flex; gap: 6px; margin-top: 7px; overflow-x: auto; }}
    button {{ color: #111827; background: #facc15; border: 0; border-radius: 999px;
      padding: 6px 11px; font-weight: 700; cursor: pointer; }}
    #close-player {{ position: fixed; z-index: 3; top: 10px; right: 10px; width: 32px;
      height: 32px; padding: 0; background: rgba(15,23,42,.72); color: #f8fafc;
      border: 1px solid rgba(103,232,249,.75); font-size: 18px; }}
    .overlay {{ background: transparent; }}
    .overlay::before {{ display: none; }}
    .overlay #hud {{ opacity: .16; transition: opacity .2s; }}
    .overlay #hud:hover {{ opacity: 1; }}
    .pywebview-drag-region {{ -webkit-app-region: drag; }}
    button, #motion-bar {{ -webkit-app-region: no-drag; }}
  </style>
  <script src="{CORE_URL}"></script>
  <script defer src="/assets/player.bundle.js"></script>
</head>
<body>
  <canvas id="live2d-canvas"></canvas>
  <button id="close-player" type="button" aria-label="关闭 Live2D 窗口">×</button>
  <div id="hud" class="pywebview-drag-region"><div id="status">正在校验并载入 Cubism 模型…</div><div id="motion-bar"></div></div>
</body>
</html>""".encode("utf-8")


class PlayerServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, handler, model_path: Path, mode: str,
                 control_path: Path | None = None):
        super().__init__(address, handler)
        self.model_path = model_path
        self.model_root = model_path.parent.resolve()
        self.asset_root = resource_path("live2d_web", "dist").resolve()
        self.mode = mode
        self.control_path = control_path
        self.asset = inspect_live2d_model(model_path)


class PlayerHandler(BaseHTTPRequestHandler):
    server: PlayerServer

    def log_message(self, _format, *_args):
        return

    def _send(self, status: int, content_type: str, payload: bytes):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; script-src 'self' https://cubism.live2d.com; "
            "connect-src 'self'; img-src 'self' data: blob:; style-src 'unsafe-inline'; "
            "worker-src blob:",
        )
        self.end_headers()
        self.wfile.write(payload)

    def _safe_file(self, root: Path, relative: str) -> Path | None:
        candidate = (root / unquote(relative)).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            return None
        return candidate if candidate.is_file() else None

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            self._send(200, "text/html; charset=utf-8", player_html())
            return
        if path == "/config.json":
            asset = self.server.asset
            payload = json.dumps({
                "name": asset.name,
                "modelUrl": "/model/" + self.server.model_path.name,
                "motionGroups": list(asset.motion_groups),
                "motionCount": asset.motion_count,
                "mode": self.server.mode,
                "controlUrl": "/control.json" if self.server.control_path else "",
                "officialFileGuide": OFFICIAL_FILE_GUIDE,
                "officialLicense": OFFICIAL_LICENSE,
            }, ensure_ascii=False).encode("utf-8")
            self._send(200, "application/json; charset=utf-8", payload)
            return
        if path == "/control.json" and self.server.control_path:
            payload = {"schemaVersion": 1, "revision": 0,
                       "emotion": "IDLE", "action": "IDLE"}
            try:
                control = self.server.control_path
                if control.is_file() and control.stat().st_size <= 4096:
                    raw = json.loads(control.read_text(encoding="utf-8"))
                    action = str(raw.get("action", "IDLE"))
                    emotion = str(raw.get("emotion", "IDLE"))
                    if action.replace("_", "").isalnum() and emotion.replace("_", "").isalnum():
                        payload = {"schemaVersion": 1, "revision": int(raw.get("revision", 0)),
                                   "emotion": emotion[:16], "action": action[:16]}
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
                pass
            self._send(200, "application/json; charset=utf-8",
                       json.dumps(payload, separators=(",", ":")).encode("utf-8"))
            return
        if path.startswith("/assets/"):
            target = self._safe_file(self.server.asset_root, path[len("/assets/"):])
        elif path.startswith("/model/"):
            target = self._safe_file(self.server.model_root, path[len("/model/"):])
        else:
            target = None
        if target is None:
            self._send(404, "text/plain; charset=utf-8", "Not found".encode("utf-8"))
            return
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self._send(200, content_type, target.read_bytes())


def run_player(model_path: str | Path, mode: str = "stage",
               control_path: str | Path | None = None) -> int:
    model = Path(model_path).expanduser().resolve()
    asset = inspect_live2d_model(model)
    bundle = resource_path("live2d_web", "dist", "player.bundle.js")
    if not bundle.is_file():
        raise RuntimeError("缺少 Live2D Web 展示层；请先执行 live2d_web 的 npm build")
    try:
        import webview
    except ImportError as error:
        raise RuntimeError("缺少 pywebview；请安装桌面端 requirements.txt") from error
    control = Path(control_path).expanduser().resolve() if control_path else None
    server = PlayerServer(("127.0.0.1", 0), PlayerHandler, model, mode, control)
    thread = threading.Thread(target=server.serve_forever, daemon=True, name="live2d-http")
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/"
    window_ref = {}

    class PlayerApi:
        def close_player(self):
            player_window = window_ref.get("window")
            if player_window is not None:
                player_window.destroy()
            return True

    api = PlayerApi()
    try:
        window = webview.create_window(
            f"LabCapsule Live2D · {asset.name}", url=url,
            width=420 if mode == "overlay" else 520,
            height=600 if mode == "overlay" else 720,
            min_size=(300, 420), frameless=mode == "overlay",
            on_top=mode == "overlay", transparent=mode == "overlay",
            background_color="#000000" if mode == "overlay" else "#080c12",
            js_api=api,
        )
        # Keep the native Window out of `js_api`: pywebview recursively exports
        # public API attributes, and a Window contains an unbounded Windows
        # AccessibilityObject graph. Only the close method is exposed to JS.
        window_ref["window"] = window
        webview.start(gui="edgechromium", debug=False)
        return 0
    finally:
        server.shutdown()
        server.server_close()


def run_player_guarded(model_path: str | Path, mode: str = "stage",
                       control_path: str | Path | None = None) -> int:
    try:
        return run_player(model_path, mode, control_path)
    except Exception as error:
        try:
            import tkinter as tk
            from tkinter import messagebox

            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("LabCapsule Live2D 启动失败", str(error), parent=root)
            root.destroy()
        except Exception:
            print(f"Live2D player error: {error}", file=sys.stderr)
        return 2


def main() -> int:
    parser = argparse.ArgumentParser(description="LabCapsule local Live2D stage")
    parser.add_argument("model")
    parser.add_argument("--mode", choices=("stage", "overlay"), default="stage")
    parser.add_argument("--control", default="")
    args = parser.parse_args()
    return run_player_guarded(args.model, args.mode, args.control or None)


if __name__ == "__main__":
    raise SystemExit(main())
