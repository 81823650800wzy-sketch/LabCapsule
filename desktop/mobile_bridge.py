"""Opt-in LAN bridge between the LabCapsule phone app and Studio.

The bridge deliberately exposes an allowlisted, read-only surface.  Pairing is
confirmed by a short code shown in Studio; bearer tokens are stored only as
SHA-256 hashes on the PC.  It never provides a shell or arbitrary file access.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import socket
import threading
import time
from typing import Callable


MAX_REQUEST_BYTES = 32 * 1024
MAX_QUESTION_CHARS = 12_000
PAIR_TTL_SECONDS = 10 * 60
SCOPES = ("computer.status", "labcapsule.context", "claude.delegate")


def _json_safe(value):
    """Round-trip callbacks through JSON and cap pathological output."""
    encoded = json.dumps(value, ensure_ascii=False, default=str)
    if len(encoded.encode("utf-8")) > 256 * 1024:
        raise ValueError("电脑状态超过安全大小")
    return json.loads(encoded)


@dataclass(frozen=True)
class BridgeInfo:
    host: str
    port: int
    pairing_code: str
    expires_at: float

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"


class MobileBridgeServer:
    def __init__(self, storage_path: Path, status_provider: Callable[[], dict],
                 ask_provider: Callable[[str], dict], host: str = "0.0.0.0",
                 port: int = 8765):
        self.storage_path = Path(storage_path)
        self.status_provider = status_provider
        self.ask_provider = ask_provider
        self.host = host
        self.port = int(port)
        self.httpd: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None
        self.pairing_code = ""
        self.pairing_expires = 0.0
        self.pair_attempts: dict[str, tuple[int, float]] = {}
        self.authorized = self._load_authorized()
        self.lock = threading.Lock()

    def _load_authorized(self) -> dict:
        try:
            raw = json.loads(self.storage_path.read_text(encoding="utf-8"))
            devices = raw.get("devices", {})
            if not isinstance(devices, dict):
                return {}
            clean = {}
            for device_id, item in list(devices.items())[:30]:
                if (not isinstance(item, dict) or
                        not str(item.get("tokenHash", "")).isalnum()):
                    continue
                clean[str(device_id)[:80]] = {
                    "tokenHash": str(item["tokenHash"])[:64],
                    "name": str(item.get("name", "LabCapsule 手机"))[:80],
                    "createdAt": str(item.get("createdAt", ""))[:40],
                    "scopes": list(SCOPES),
                }
            return clean
        except (OSError, ValueError, TypeError):
            return {}

    def _save_authorized(self) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.storage_path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"schemaVersion": 1, "devices": self.authorized},
                                        ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.storage_path)

    @staticmethod
    def lan_address() -> str:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(("8.8.8.8", 80))
            return str(probe.getsockname()[0])
        except OSError:
            return "127.0.0.1"
        finally:
            probe.close()

    def start(self) -> BridgeInfo:
        if self.httpd is not None:
            return self.info()
        self.pairing_code = f"{secrets.randbelow(1_000_000):06d}"
        self.pairing_expires = time.time() + PAIR_TTL_SECONDS
        owner = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "LabCapsuleBridge/1.0"

            def log_message(self, _format, *_args):
                return

            def _reply(self, code: int, payload: dict):
                body = json.dumps(payload, ensure_ascii=False,
                                  separators=(",", ":")).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _body(self) -> dict:
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError as error:
                    raise ValueError("Content-Length 无效") from error
                if length <= 0 or length > MAX_REQUEST_BYTES:
                    raise ValueError("请求大小无效")
                value = json.loads(self.rfile.read(length).decode("utf-8"))
                if not isinstance(value, dict):
                    raise ValueError("请求必须是 JSON 对象")
                return value

            def _authorized(self) -> tuple[str, dict] | None:
                header = self.headers.get("Authorization", "")
                token = header[7:].strip() if header.startswith("Bearer ") else ""
                if len(token) < 32:
                    return None
                digest = hashlib.sha256(token.encode("ascii", errors="ignore")).hexdigest()
                with owner.lock:
                    for device_id, item in owner.authorized.items():
                        if hmac.compare_digest(digest, item.get("tokenHash", "")):
                            return device_id, item
                return None

            def do_GET(self):
                if self.path == "/health":
                    self._reply(200, {"ok": True, "service": "LabCapsule Studio",
                                      "pairingRequired": True})
                    return
                if self.path != "/v1/status":
                    self._reply(404, {"error": "not_found"})
                    return
                auth = self._authorized()
                if auth is None:
                    self._reply(401, {"error": "permission_required"})
                    return
                try:
                    self._reply(200, {"ok": True, "source": "studio",
                                      "deviceId": auth[0],
                                      "context": _json_safe(owner.status_provider())})
                except Exception as error:
                    self._reply(500, {"error": str(error)[:200]})

            def do_POST(self):
                try:
                    body = self._body()
                except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
                    self._reply(400, {"error": str(error)[:160]})
                    return
                if self.path == "/v1/pair":
                    ip = self.client_address[0]
                    now = time.time()
                    attempts, blocked_until = owner.pair_attempts.get(ip, (0, 0.0))
                    if now < blocked_until:
                        self._reply(429, {"error": "too_many_attempts"})
                        return
                    code = str(body.get("code", ""))
                    if (now > owner.pairing_expires or
                            not hmac.compare_digest(code, owner.pairing_code)):
                        attempts += 1
                        owner.pair_attempts[ip] = (0, now + 300) if attempts >= 8 else (attempts, 0)
                        self._reply(403, {"error": "pairing_code_invalid"})
                        return
                    device_id = str(body.get("deviceId", ""))[:80]
                    if not device_id or not all(ch.isalnum() or ch in "-_." for ch in device_id):
                        self._reply(400, {"error": "device_id_invalid"})
                        return
                    token = secrets.token_urlsafe(32)
                    with owner.lock:
                        owner.authorized[device_id] = {
                            "tokenHash": hashlib.sha256(token.encode("ascii")).hexdigest(),
                            "name": str(body.get("name", "LabCapsule 手机"))[:80],
                            "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            "scopes": list(SCOPES),
                        }
                        owner._save_authorized()
                        owner.pairing_code = f"{secrets.randbelow(1_000_000):06d}"
                        owner.pairing_expires = time.time() + PAIR_TTL_SECONDS
                    self._reply(200, {"ok": True, "token": token, "scopes": list(SCOPES),
                                      "warning": "只读状态与受限 Claude 分析权限"})
                    return
                if self.path != "/v1/ask":
                    self._reply(404, {"error": "not_found"})
                    return
                auth = self._authorized()
                if auth is None:
                    self._reply(401, {"error": "permission_required"})
                    return
                question = str(body.get("question", "")).strip()
                if not question or len(question) > MAX_QUESTION_CHARS:
                    self._reply(400, {"error": "question_invalid"})
                    return
                try:
                    result = _json_safe(owner.ask_provider(question))
                    self._reply(200, {"ok": True, "source": "computer-claude",
                                      "result": result})
                except Exception as error:
                    self._reply(500, {"error": str(error)[:200]})

        self.httpd = ThreadingHTTPServer((self.host, self.port), Handler)
        self.httpd.daemon_threads = True
        self.port = int(self.httpd.server_address[1])
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True,
                                       name="mobile-bridge")
        self.thread.start()
        return self.info()

    def info(self) -> BridgeInfo:
        return BridgeInfo(self.lan_address(), self.port, self.pairing_code,
                          self.pairing_expires)

    def stop(self) -> None:
        active = self.httpd
        self.httpd = None
        if active is not None:
            active.shutdown()
            active.server_close()
        thread = self.thread
        self.thread = None
        if thread and thread is not threading.current_thread():
            thread.join(timeout=2)
