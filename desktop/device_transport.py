"""LAN and Bluetooth transports for LabCapsule Studio.

Both adapters expose the small ``SerialLink`` surface used by the desktop UI:
``connect``, ``close``, ``send``, ``upload`` and ``connected``.  They never
change the host Wi-Fi configuration; LAN only contacts an address that is
already reachable through the user's current network.
"""

from __future__ import annotations

import asyncio
import json
import queue
import struct
import threading
import time
from types import SimpleNamespace
from urllib import parse, request
import zlib


SERVICE_UUID = "6c430001-4c61-6243-6170-73756c650001"
COMMAND_UUID = "6c430002-4c61-6243-6170-73756c650001"
STATUS_UUID = "6c430003-4c61-6243-6170-73756c650001"
FILE_CONTROL_UUID = "6c430006-4c61-6243-6170-73756c650001"
FILE_DATA_UUID = "6c430007-4c61-6243-6170-73756c650001"
EXPERIMENT_DATA_UUID = "6c430008-4c61-6243-6170-73756c650001"


def normalize_base_url(value: str) -> str:
    clean = value.strip().rstrip("/")
    if not clean:
        raise ValueError("请输入设备局域网地址，例如 http://192.168.1.52")
    if "://" not in clean:
        clean = "http://" + clean
    parsed = parse.urlparse(clean)
    if parsed.scheme != "http" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("局域网设备地址必须是无账户信息的 http://IP 或主机名")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("局域网设备地址不要包含 API 路径、查询或片段")
    return clean


class LanLink:
    kind = "wifi"

    def __init__(self, on_line, on_state):
        self.on_line = on_line
        self.on_state = on_state
        self.base_url = ""
        self.port = None
        self.stop_event = threading.Event()
        self._connected = False
        self.commands: queue.Queue[str] = queue.Queue(maxsize=32)

    @property
    def connected(self) -> bool:
        return self._connected

    def _call(self, method: str, path: str, payload: bytes | None = None,
              content_type: str = "application/json") -> dict:
        call = request.Request(self.base_url + path, data=payload, method=method,
                               headers={"Content-Type": content_type,
                                        "Accept": "application/json",
                                        "User-Agent": "LabCapsule-Studio/1.0"})
        with request.urlopen(call, timeout=30) as response:
            data = response.read(2 * 1024 * 1024 + 1)
        if len(data) > 2 * 1024 * 1024:
            raise ValueError("设备响应过大")
        return json.loads(data.decode("utf-8")) if data else {}

    def _status(self) -> dict:
        status = self._call("GET", "/api/status")
        self.on_line("TRANSPORT_JSON," + json.dumps(status, ensure_ascii=False,
                                                     separators=(",", ":")))
        return status

    def connect(self, target: str) -> None:
        self.close()
        self.base_url = normalize_base_url(target)
        status = self._call("GET", "/api/status")
        if status.get("ok") is not True:
            raise RuntimeError("设备未返回有效局域网状态")
        self._connected = True
        self.port = SimpleNamespace(port=self.base_url)
        self.stop_event.clear()
        self.on_state(True, self.base_url)
        self.on_line("TRANSPORT_JSON," + json.dumps(status, ensure_ascii=False,
                                                     separators=(",", ":")))
        threading.Thread(target=self._poll, daemon=True, name="lan-status").start()

    def close(self) -> None:
        was_connected = self._connected
        self.stop_event.set()
        self._connected = False
        self.port = None
        if was_connected:
            self.on_state(False, "")

    def _poll(self) -> None:
        next_status = time.monotonic() + 2.0
        while not self.stop_event.is_set():
            command = ""
            try:
                timeout = max(0.05, min(0.5, next_status - time.monotonic()))
                try:
                    command = self.commands.get(timeout=timeout)
                except queue.Empty:
                    command = ""
                if command:
                    self._send_now(command)
                if time.monotonic() >= next_status:
                    self._status()
                    next_status = time.monotonic() + 2.0
            except Exception as error:
                self.on_line(f"ERR,LAN,{error}")
                if not command:
                    self.close()
                    return

    @staticmethod
    def _remote_action(command: str) -> str | None:
        parts = command.split(",")
        head = parts[0].upper()
        if head in {"STOP", "ABORT"}:
            return head
        if head == "MOCK" and len(parts) > 1:
            return "MOCK_" + parts[1].upper()
        if head in {"UP", "DOWN", "LEFT", "RIGHT", "OK", "BACK"}:
            return head
        if head in {"DEVELOPER", "DEV"}:
            return "DEVELOPER"
        if head == "DISPLAY" and len(parts) > 1:
            return {"PET": "PET", "HOME": "HOME", "DEV": "DEVELOPER",
                    "TEST": "TEST", "SETTINGS": "SETTINGS",
                    "WALLPAPER": "WALLPAPER"}.get(parts[1].upper())
        if head == "GIF" and len(parts) > 1:
            return "GIF_" + ("FPS:" + parts[2] if parts[1].upper() == "FPS" and
                              len(parts) > 2 else parts[1].upper())
        if head == "HOST" and len(parts) >= 5:
            return "HOST:" + ":".join(parts[1:5])
        if head == "PET" and len(parts) > 1:
            action = parts[1].upper()
            if action == "SHOW":
                return "PET"
            if action == "HIDE":
                return "HOME"
            if action == "CLEAR":
                return "PET_CLEAR"
            if action == "STATE" and len(parts) >= 4:
                return "PET_STATE:" + parts[2].upper() + ":" + parts[3].upper()
            if action == "IDENTITY" and len(parts) >= 4:
                return "PET_IDENTITY:" + parts[2] + ":" + parts[3].upper()
        return None

    def _send_now(self, command: str) -> None:
        if not self.connected:
            raise RuntimeError("局域网设备未连接")
        upper = command.upper()
        if upper in {"PING", "STATUS", "IDENTITY", "PET,STATUS"}:
            self._status()
            return
        if upper in {"SENSORS", "SCAN"}:
            result = self._call("GET", "/api/sensors")
            self.on_line("SENSORS_JSON," + json.dumps(result, ensure_ascii=False,
                                                       separators=(",", ":")))
            return
        parts = command.split(",")
        if parts[0].upper() == "START" and len(parts) >= 3:
            path = "/api/experiment?" + parse.urlencode(
                {"rate": parts[1], "duration": parts[2]})
            self._call("POST", path, b"")
            self.on_line(f"OK,START,RATE={parts[1]},DURATION={parts[2]},SOURCE=WIFI")
            return
        if parts[0].upper() == "STYLE" and len(parts) >= 5:
            body = json.dumps({"preset": int(parts[1]),
                               "wallpaperOpacity": int(parts[2]),
                               "panelOpacity": int(parts[3]),
                               "hudOpacity": int(parts[4])}).encode("utf-8")
            self._call("POST", "/api/display", body)
            return
        if parts[0].upper() == "MODE" and len(parts) >= 2:
            body = json.dumps({"mode": parts[1].lower()}).encode("utf-8")
            self._call("POST", "/api/mode", body)
            return
        if parts[0].upper() == "NOTICE" and len(parts) >= 3:
            body = json.dumps({"mode": "idle", "title": parts[1],
                               "message": ",".join(parts[2:])},
                              ensure_ascii=False).encode("utf-8")
            self._call("POST", "/api/mode", body)
            return
        action = self._remote_action(command)
        if not action:
            raise ValueError("该命令尚不支持局域网传输")
        path = "/api/control?" + parse.urlencode({"action": action})
        self._call("POST", path, b"")

    def send(self, command: str) -> None:
        if not self.connected:
            raise RuntimeError("局域网设备未连接")
        try:
            self.commands.put_nowait(command)
        except queue.Full as error:
            raise RuntimeError("局域网命令队列已满，请稍候重试") from error

    def upload(self, kind: str, payload: bytes, progress) -> None:
        if not self.connected:
            raise RuntimeError("局域网设备未连接")
        upper = kind.upper()
        crc = zlib.crc32(payload) & 0xFFFFFFFF
        progress(5)
        if upper == "CLIP":
            path = "/api/media/clip?" + parse.urlencode({"crc": f"{crc:08X}"})
        elif upper == "WALLPAPER":
            path = "/api/wallpaper"
        elif upper == "PETBUBBLE":
            path = "/api/pet/bubble?" + parse.urlencode({"crc": f"{crc:08X}"})
        else:
            raise ValueError("不支持的局域网上传类型")
        self._call("POST", path, payload, "application/octet-stream")
        progress(100)
        self._status()


class BleLink:
    kind = "ble"

    def __init__(self, on_line, on_state):
        self.on_line = on_line
        self.on_state = on_state
        self.port = None
        self.client = None
        self.loop = None
        self.thread = None
        self.stop_event = threading.Event()
        self.ready_event = threading.Event()
        self.connect_error = ""
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    @staticmethod
    def available() -> bool:
        try:
            import bleak  # noqa: F401
            return True
        except ImportError:
            return False

    def connect(self, target: str) -> None:
        if not self.available():
            raise RuntimeError("缺少 bleak；请重新安装 V1 桌面包或运行 pip install bleak")
        self.close()
        self.stop_event.clear()
        self.ready_event.clear()
        self.connect_error = ""
        self.thread = threading.Thread(target=self._thread_main, args=(target.strip(),),
                                       daemon=True, name="ble-link")
        self.thread.start()
        if not self.ready_event.wait(18):
            self.stop_event.set()
            raise TimeoutError("蓝牙扫描/连接超过 18 秒")
        if self.connect_error:
            raise RuntimeError(self.connect_error)

    def _thread_main(self, target: str) -> None:
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._run(target))
        except Exception as error:
            self.connect_error = str(error)
            self.ready_event.set()
        finally:
            self._connected = False
            self.client = None
            self.loop.close()

    async def _run(self, target: str) -> None:
        from bleak import BleakClient, BleakScanner

        devices = await BleakScanner.discover(timeout=7.0, service_uuids=[SERVICE_UUID])
        lowered = target.lower()
        device = next((item for item in devices if
                       (target and (item.address.lower() == lowered or
                                    (item.name or "").lower() == lowered))), None)
        if device is None:
            device = next((item for item in devices if (item.name or "").startswith("LabCapsule")), None)
        if device is None:
            raise RuntimeError("附近未发现 LabCapsule BLE；请确认设备已开机且未被其他手机占用")
        async with BleakClient(device) as client:
            self.client = client
            await client.start_notify(STATUS_UUID, self._status_notification)
            await client.start_notify(EXPERIMENT_DATA_UUID, self._data_notification)
            self._connected = True
            self.port = SimpleNamespace(port=f"BLE:{device.name or device.address}")
            self.on_state(True, self.port.port)
            await self._write_command("STATUS")
            self.ready_event.set()
            while not self.stop_event.is_set() and client.is_connected:
                await asyncio.sleep(0.2)
            if client.is_connected:
                await client.stop_notify(EXPERIMENT_DATA_UUID)
                await client.stop_notify(STATUS_UUID)
        self.on_state(False, "")

    def _status_notification(self, _characteristic, data: bytearray) -> None:
        try:
            text = bytes(data).decode("utf-8")
            self.on_line("TRANSPORT_JSON," + text)
        except UnicodeDecodeError:
            self.on_line("ERR,BLE,INVALID_STATUS_UTF8")

    def _data_notification(self, _characteristic, data: bytearray) -> None:
        raw = bytes(data)
        if len(raw) == 17 and raw[0] == 0x10:
            timestamp, *axes = struct.unpack_from("<I6h", raw, 1)
            values = [axes[index] / (4096.0 if index < 3 else 16.0)
                      for index in range(6)]
            self.on_line("DATA," + str(timestamp) + "," +
                         ",".join(f"{value:.5f}" for value in values))

    async def _write_command(self, command: str) -> None:
        if not self.client or not self.client.is_connected:
            raise RuntimeError("蓝牙设备未连接")
        await self.client.write_gatt_char(COMMAND_UUID, command.encode("utf-8"), response=True)
        await asyncio.sleep(0.06)
        status = await self.client.read_gatt_char(STATUS_UUID, use_cached=False)
        self._status_notification(None, status)

    @staticmethod
    def _ble_command(command: str) -> str:
        upper = command.upper()
        if upper in {"PING", "STATUS", "IDENTITY", "PET,STATUS"}:
            return "STATUS"
        if upper in {"SENSORS", "SCAN"}:
            return "SENSORS"
        parts = command.split(",")
        if parts[0].upper() == "START" and len(parts) >= 3:
            return f"START:{parts[1]}:{parts[2]}"
        action = LanLink._remote_action(command)
        if action:
            return action
        if parts[0].upper() == "MODE" and len(parts) >= 2:
            return "MODE:" + parts[1].upper()
        if parts[0].upper() == "STYLE" and len(parts) >= 5:
            return "STYLE:" + ":".join(parts[1:5])
        if parts[0].upper() == "NOTICE" and len(parts) >= 3:
            return "NOTICE:" + parts[1] + "|" + ",".join(parts[2:])
        raise ValueError("该命令尚不支持蓝牙传输")

    def send(self, command: str) -> None:
        if not self.connected or not self.loop:
            raise RuntimeError("蓝牙设备未连接")
        future = asyncio.run_coroutine_threadsafe(
            self._write_command(self._ble_command(command)), self.loop)
        future.result(timeout=12)

    async def _upload(self, kind: str, payload: bytes, progress) -> None:
        if not self.client or not self.client.is_connected:
            raise RuntimeError("蓝牙设备未连接")
        upper = kind.upper()
        if upper not in {"CLIP", "WALLPAPER", "PETBUBBLE"}:
            raise ValueError("不支持的蓝牙上传类型")
        crc = zlib.crc32(payload) & 0xFFFFFFFF
        begin = f"BEGIN:{upper}:{len(payload)}:0:{crc:08X}:raw565:0:0:240:320"
        await self.client.write_gatt_char(FILE_CONTROL_UUID, begin.encode("ascii"), response=True)
        chunk_size = 220
        for offset in range(0, len(payload), chunk_size):
            await self.client.write_gatt_char(FILE_DATA_UUID,
                                              payload[offset:offset + chunk_size],
                                              response=True)
            progress(min(99, round((offset + chunk_size) * 100 / len(payload))))
        await self.client.write_gatt_char(FILE_CONTROL_UUID, b"END", response=True)
        progress(100)
        await self._write_command("STATUS")

    def upload(self, kind: str, payload: bytes, progress) -> None:
        if not self.connected or not self.loop:
            raise RuntimeError("蓝牙设备未连接")
        future = asyncio.run_coroutine_threadsafe(self._upload(kind, payload, progress), self.loop)
        future.result(timeout=max(30, len(payload) // 1000 + 30))

    def close(self) -> None:
        was_connected = self._connected
        self.stop_event.set()
        if self.thread and self.thread.is_alive() and threading.current_thread() is not self.thread:
            self.thread.join(timeout=5)
        self._connected = False
        self.port = None
        if was_connected and (not self.thread or not self.thread.is_alive()):
            # _run normally emits this; this path covers early teardown.
            pass
