"""LabCapsule Studio V1 - interactive data and AI companion for Windows.

The app intentionally never changes the computer's Wi-Fi connection.  It uses
USB, an already-reachable LAN address, or BLE for device control and transfer.
"""

from __future__ import annotations

import asyncio
import base64
import csv
from datetime import datetime
import json
import hashlib
import io
import math
import platform
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import webbrowser
import zlib

import psutil
import serial
from serial.tools import list_ports
from PIL import Image, ImageTk

from avatar_assets import (AVATAR_CACHE_DIR, DICEBEAR_CC0_PRESETS, DecodedAvatar,
                           clear_cached_avatar, decode_avatar, dicebear_url,
                           display_url, download_avatar, load_cached_avatar)
from interactive_chart import InteractiveMotionChart
from claude_bridge import ClaudeBridge
from media_codec import (HEIGHT, MAX_FPS, WIDTH, build_clip_from_frames, build_media,
                         compose_frame, load_frames)
from pet_agent import CharacterProfile, PetAgentRuntime, PetAvatarCanvas, PetOverlay, PetReply, PetSettings
from pet_device import pet_state_command, render_pet_bubble
from pet_packages import (APP_DIR, PET_SELECTION_PATH, PetPackage, avatar_asset_for_package, clear_selected_pet,
                          discover_pet_packages, load_pet_package, save_selected_pet,
                          selected_pet_package)
from live2d_runtime import (CONTROL_PATH, has_live2d_consent, player_command,
                            save_live2d_consent, write_live2d_action)
from memory_repo import (GitHubMemoryClient, MemoryRemote, empty_snapshot,
                         merge_snapshots)
from mobile_bridge import MobileBridgeServer
from role_card_repo import (GitHubRoleCardClient, RoleCardRemote, apply_role_card,
                            build_role_card)
from device_transport import BleLink, LanLink
from speech_input import record_wav, transcribe_wav
from experiment_store import ExperimentStore


APP_VERSION = "1.2.0"
BAUD_RATE = 460800
ROOT = Path(__file__).resolve().parent


def parse_motion_data_line(line: str):
    """Validate one firmware DATA record before it reaches charts or CSV."""
    parts = line.split(",")
    if len(parts) < 8 or parts[0] != "DATA":
        return None
    try:
        timestamp_us = int(parts[1])
        values = tuple(float(value) for value in parts[2:8])
    except ValueError:
        return None
    if not 0 <= timestamp_us <= 0xFFFFFFFFFFFFFFFF or not all(map(math.isfinite, values)):
        return None
    return parts[1:8], timestamp_us, values


def parse_key_value_fields(parts: list[str]) -> dict[str, str]:
    """Parse firmware comma fields while ignoring malformed diagnostics."""
    values: dict[str, str] = {}
    for item in parts:
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        key = key.strip().upper()
        if key:
            values[key] = value.strip()
    return values


class SerialLink:
    kind = "usb"

    def __init__(self, on_line, on_state):
        self.on_line = on_line
        self.on_state = on_state
        self.port: serial.Serial | None = None
        self.stop_event = threading.Event()
        self.write_lock = threading.Lock()
        self.ready_event = threading.Event()
        self.done_event = threading.Event()
        self.upload_error = ""

    @property
    def connected(self) -> bool:
        return bool(self.port and self.port.is_open)

    def connect(self, name: str) -> None:
        self.close()
        self.port = serial.Serial(name, BAUD_RATE, timeout=0.1, write_timeout=15)
        self.stop_event.clear()
        threading.Thread(target=self._reader, daemon=True, name="serial-reader").start()
        self.on_state(True, name)
        self.send("PING")
        self.send("STATUS")
        self.send("IDENTITY")
        self.send("PET,STATUS")
        self.send("NETWORK")

    def close(self) -> None:
        self.stop_event.set()
        active = self.port
        self.port = None
        if active:
            try:
                active.close()
            except Exception:
                pass
            self.on_state(False, "")

    def send(self, command: str) -> None:
        if not self.connected:
            raise RuntimeError("设备未连接")
        safe = command.replace("\r", " ").replace("\n", " ")
        with self.write_lock:
            assert self.port
            self._write_all(self.port, (safe + "\n").encode("utf-8"))

    @staticmethod
    def _write_all(active, payload: bytes) -> None:
        """Honor short serial writes instead of silently truncating a frame."""
        view = memoryview(payload)
        offset = 0
        while offset < len(view):
            written = active.write(view[offset:])
            if not written:
                raise OSError("串口写入未取得进展")
            offset += int(written)

    def upload(self, kind: str, payload: bytes, progress) -> None:
        if not self.connected:
            raise RuntimeError("设备未连接")
        crc = zlib.crc32(payload) & 0xFFFFFFFF
        attempts = 3 if kind.upper() == "PETBUBBLE" else 2
        # RAM-only bubbles are accepted much faster than flash-backed media.
        # Explicit pacing prevents small CH343/CP210x receive FIFOs from
        # overrunning while the display task is active.
        chunk_size = 64 if kind.upper() == "PETBUBBLE" else 256
        with self.write_lock:
            assert self.port
            for attempt in range(1, attempts + 1):
                self.ready_event.clear()
                self.done_event.clear()
                self.upload_error = ""
                header = f"UPLOAD,{kind},{len(payload)},{crc:08X}\n".encode("ascii")
                self._write_all(self.port, header)
                self.port.flush()
                if not self.ready_event.wait(8):
                    raise TimeoutError("设备未进入 USB 上传模式")
                if self.upload_error:
                    raise RuntimeError(self.upload_error)
                for offset in range(0, len(payload), chunk_size):
                    if self.stop_event.is_set():
                        raise RuntimeError("连接已断开")
                    self._write_all(self.port, payload[offset : offset + chunk_size])
                    if kind.upper() == "PETBUBBLE":
                        self.port.flush()
                        time.sleep(0.010)
                    else:
                        self.port.flush()
                        # The FAT writer commits its 16 KiB buffer in bursts.
                        # Leave headroom in bridge/UART FIFOs across those stalls.
                        sent = min(chunk_size, len(payload) - offset)
                        time.sleep(0.250 if (offset + sent) % 4096 == 0 else 0.006)
                    progress(min(99, round((offset + chunk_size) * 100 / len(payload))))
                self.port.flush()
                if not self.done_event.wait(60):
                    raise TimeoutError("设备未确认媒体校验结果")
                if not self.upload_error:
                    break
                retryable = ("INVALID_CRC" in self.upload_error or
                             "TIMEOUT" in self.upload_error)
                if not retryable or attempt == attempts:
                    raise RuntimeError(self.upload_error)
                progress(0)
                time.sleep(0.12 * attempt)
        progress(100)

    def _reader(self) -> None:
        buffer = bytearray()
        try:
            while not self.stop_event.is_set() and self.connected:
                assert self.port
                data = self.port.read(1024)
                if not data:
                    continue
                buffer.extend(data)
                while b"\n" in buffer:
                    raw, _, buffer = buffer.partition(b"\n")
                    line = raw.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue
                    if line.startswith("READY,UPLOAD,"):
                        self.ready_event.set()
                    if line.startswith("OK,UPLOAD,"):
                        self.done_event.set()
                    if line.startswith("ERR,UPLOAD,"):
                        self.upload_error = line
                        self.ready_event.set()
                        self.done_event.set()
                    self.on_line(line)
        except Exception as error:
            if not self.stop_event.is_set():
                self.on_line(f"DESKTOP,串口异常,{error}")
        finally:
            if self.port:
                self.close()


class WindowsNotificationBridge:
    """Optional Windows notification access; the app remains usable without it."""

    def __init__(self):
        self.listener = None
        self.seen: set[int] = set()

    async def _enable(self):
        from winsdk.windows.ui.notifications.management import UserNotificationListener

        self.listener = UserNotificationListener.current
        status = await self.listener.request_access_async()
        return "allowed" in str(status).lower()

    def enable(self) -> bool:
        try:
            return bool(asyncio.run(self._enable()))
        except Exception:
            return False

    async def _poll(self):
        from winsdk.windows.ui.notifications import NotificationKinds

        if self.listener is None:
            return []
        items = await self.listener.get_notifications_async(NotificationKinds.TOAST)
        output = []
        for item in items:
            identifier = int(item.id)
            if identifier in self.seen:
                continue
            self.seen.add(identifier)
            app = item.app_info.display_info.display_name
            binding = item.notification.visual.get_binding(
                "ToastGeneric"
            ) or item.notification.visual.get_binding("ToastText02")
            texts = [] if binding is None else [element.text for element in binding.get_text_elements()]
            title = texts[0] if texts else app
            body = " ".join(texts[1:]) if len(texts) > 1 else app
            output.append((title, body))
        return output[-5:]

    def poll(self):
        try:
            return asyncio.run(self._poll())
        except Exception:
            return []


class Studio(tk.Tk):
    BG = "#0b0e13"
    PANEL = "#151a22"
    PANEL_2 = "#1d2430"
    INK = "#f1f5f9"
    MUTED = "#92a0b4"
    CYAN = "#67e8f9"
    YELLOW = "#facc15"
    RED = "#fb7185"

    def __init__(self):
        super().__init__()
        self.title(f"LabCapsule Studio {APP_VERSION}")
        self.geometry("1180x760")
        self.minsize(1000, 680)
        self.configure(bg=self.BG)
        self.protocol("WM_DELETE_WINDOW", self.close_app)
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.transport_var = tk.StringVar(value="USB 数据线")
        self.transport_mode = "USB 数据线"
        self.link = self._make_link(self.transport_mode)
        self.notification_bridge = WindowsNotificationBridge()
        self.notification_enabled = False
        self.last_notification_poll = 0.0
        self.samples: list[list[str]] = []
        self.experiment_store = ExperimentStore(APP_DIR)
        self.experiment_started_at = ""
        self.experiment_session_saved = False
        self.device_state = "READY"
        self.device_recording = False
        self.device_rate = 0
        self.device_duration = 0
        self.device_firmware_version = ""
        self.device_id = ""
        self.device_alias = ""
        self.device_character_id = ""
        self.device_pet_proxy = False
        self.device_sta_connected = False
        self.device_sta_ip = "0.0.0.0"
        self.memory_sync_active = False
        self.memory_revision = 0
        self.memory_synced_device = ""
        self.last_handshake_at = 0.0
        self.host_snapshot: dict[str, object] = {}
        self.last_sample: tuple[str, ...] | None = None
        self.last_pet_error_at = 0.0
        self.media_path = ""
        self.pet_path = ""
        self.preview_photo = None
        self.pet_settings = PetSettings.load()
        self.pet_runtime = PetAgentRuntime(self.pet_settings)
        self.claude_bridge = ClaudeBridge(self.pet_settings.claude_model)
        self.mobile_bridge: MobileBridgeServer | None = None
        self.role_preview_path = ""
        self.role_voice_path = ""
        self.role_card_catalog: dict = {"schemaVersion": 1, "cards": []}
        self.role_card_window: tk.Toplevel | None = None
        self.role_card_photos: list[ImageTk.PhotoImage] = []
        self.role_profile_override: CharacterProfile | None = None
        self.device_pet_enabled = False
        self.pet_device_sync_active = False
        self.pending_pet_device_reply: PetReply | None = None
        self.last_pet_reply = PetReply(self.pet_settings.profile.greeting, "idle", True,
                                       source="event", action="IDLE")
        self.pet_overlay: PetOverlay | None = None
        self.active_pet_package: PetPackage | None = None
        self.live2d_processes: list[tuple[str, subprocess.Popen]] = []
        self.live2d_license_window: tk.Toplevel | None = None
        self.pet_emotion = "idle"
        self.avatar_decoded: DecodedAvatar | None = None
        self.avatar_library_window: tk.Toplevel | None = None
        self.avatar_download_active = False
        self.avatar_url_var = tk.StringVar(value=self.pet_settings.avatar_url)
        self.avatar_seed_var = tk.StringVar(value="LabCapsule")
        self.avatar_preset_var = tk.StringVar(value=next(iter(DICEBEAR_CC0_PRESETS)))
        self.pet_package_var = tk.StringVar()
        self.pet_package_choices: dict[str, PetPackage] = {}
        self._style()
        self._layout()
        self.refresh_ports()
        self.after(150, self._restore_selected_pet_or_avatar)
        self.after(50, self._pump)
        self.after(1000, self._heartbeat)

    def _style(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", background=self.BG, foreground=self.INK, fieldbackground=self.PANEL,
                        bordercolor=self.PANEL_2, font=("Microsoft YaHei UI", 10))
        style.configure("TNotebook", background=self.BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=self.PANEL, foreground=self.MUTED,
                        padding=(24, 12), borderwidth=0)
        style.map("TNotebook.Tab", background=[("selected", self.PANEL_2)],
                  foreground=[("selected", self.CYAN)])
        style.configure("Accent.TButton", background=self.YELLOW, foreground="#111318",
                        padding=(14, 8), font=("Microsoft YaHei UI", 10, "bold"))
        style.configure("TButton", background=self.PANEL_2, foreground=self.INK, padding=(11, 7))
        style.map("TButton", background=[("active", "#2a3443")])
        style.configure("Card.TLabelframe", background=self.PANEL, foreground=self.CYAN,
                        padding=12, borderwidth=1, relief="solid")
        style.configure("Card.TLabelframe.Label", background=self.PANEL, foreground=self.CYAN,
                        font=("Microsoft YaHei UI", 10, "bold"))
        style.configure("TLabel", background=self.BG, foreground=self.INK)
        style.configure("Panel.TLabel", background=self.PANEL, foreground=self.INK)
        style.configure("Muted.TLabel", background=self.PANEL, foreground=self.MUTED)
        style.configure("TEntry", fieldbackground="#0f141c", foreground=self.INK)
        style.configure("TCombobox", fieldbackground="#0f141c", foreground=self.INK)
        style.configure("Horizontal.TProgressbar", background=self.CYAN, troughcolor=self.PANEL_2)

    def _make_link(self, mode: str):
        line = lambda value: self.events.put(("line", value))
        state = lambda connected, target: self.events.put(
            ("state", (connected, target)))
        if mode == "局域网 WiFi":
            return LanLink(line, state)
        if mode == "蓝牙 BLE":
            return BleLink(line, state)
        return SerialLink(line, state)

    def _layout(self):
        header = tk.Frame(self, bg=self.BG)
        header.pack(fill="x", padx=20, pady=(16, 8))
        tk.Label(header, text="LABCAPSULE / STUDIO", bg=self.BG, fg=self.INK,
                 font=("Bahnschrift", 19, "bold")).pack(side="left")
        tk.Label(header, text=" USB · LAN · BLE / LOCAL MEDIA / MOTION LAB ", bg=self.YELLOW,
                 fg="#111318", font=("Bahnschrift", 9, "bold"), padx=8, pady=3).pack(side="left", padx=14)
        self.connection_label = tk.Label(header, text="● 未连接", bg=self.BG, fg=self.RED,
                                         font=("Microsoft YaHei UI", 10, "bold"))
        self.connection_label.pack(side="right")

        connect = tk.Frame(self, bg=self.PANEL, padx=12, pady=10)
        connect.pack(fill="x", padx=20, pady=(0, 10))
        tk.Label(connect, text="连接方式", bg=self.PANEL, fg=self.MUTED).pack(side="left")
        self.transport_box = ttk.Combobox(
            connect, textvariable=self.transport_var,
            values=("USB 数据线", "局域网 WiFi", "蓝牙 BLE"),
            width=13, state="readonly")
        self.transport_box.pack(side="left", padx=(8, 4))
        self.transport_box.bind("<<ComboboxSelected>>", self.on_transport_changed)
        self.port_var = tk.StringVar()
        self.port_box = ttk.Combobox(connect, textvariable=self.port_var, width=34, state="readonly")
        self.port_box.pack(side="left", padx=10)
        self.scan_button = ttk.Button(connect, text="重新扫描", command=self.refresh_ports)
        self.scan_button.pack(side="left", padx=4)
        self.connect_button = ttk.Button(connect, text="连接", style="Accent.TButton",
                                         command=self.toggle_connect)
        self.connect_button.pack(side="left", padx=4)
        self.network_label = tk.Label(
            connect, text="不会连接或切换设备热点，不影响电脑联网",
            bg=self.PANEL, fg=self.CYAN)
        self.network_label.pack(side="right")

        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        self.experiment = tk.Frame(self.tabs, bg=self.BG)
        self.pet = tk.Frame(self.tabs, bg=self.BG)
        self.settings = tk.Frame(self.tabs, bg=self.BG)
        self.tabs.add(self.pet, text="实验助手")
        self.tabs.add(self.experiment, text="实验数据")
        self.tabs.add(self.settings, text="设置")
        self._settings_shell()
        self._dashboard_ui()
        self._screen_ui()
        self._experiment_ui()
        self._pet_ui()
        self._console_ui()

    def _settings_shell(self):
        shell = tk.Frame(self.settings, bg=self.BG)
        shell.pack(fill="both", expand=True)
        canvas = tk.Canvas(shell, bg=self.BG, highlightthickness=0, borderwidth=0)
        scrollbar = ttk.Scrollbar(shell, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        content = tk.Frame(canvas, bg=self.BG)
        window = canvas.create_window((0, 0), window=content, anchor="nw")
        content.bind("<Configure>", lambda _event: canvas.configure(
            scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window, width=event.width))
        self.settings_canvas = canvas
        self.settings_sections: dict[str, tuple[ttk.Button, tk.Frame]] = {}

        def section(key: str, title: str) -> tk.Frame:
            outer = tk.Frame(content, bg=self.BG)
            outer.pack(fill="x", padx=4, pady=4)
            body = tk.Frame(outer, bg=self.BG)

            def toggle():
                self.open_settings_section(key if not body.winfo_ismapped() else "")

            button = ttk.Button(outer, text=f"＋ {title}", command=toggle)
            button.pack(fill="x")
            self.settings_sections[key] = (button, body)
            return body

        self.dashboard = section("device", "设备、连接与通知")
        self.screen = section("screen", "屏幕、壁纸与媒体")
        self.console = section("diagnostics", "开发者诊断")
        ttk.Label(content,
                  text="设置区默认折叠；日常使用只需实验助手和实验数据。",
                  style="Muted.TLabel").pack(anchor="w", padx=10, pady=12)

    def open_settings_section(self, key: str):
        for name, (button, body) in self.settings_sections.items():
            if name == key:
                body.pack(fill="both", expand=True, pady=(4, 0))
                button.configure(text="－ " + {
                    "device": "设备、连接与通知",
                    "screen": "屏幕、壁纸与媒体",
                    "diagnostics": "开发者诊断",
                }[name])
            else:
                body.pack_forget()
                button.configure(text="＋ " + {
                    "device": "设备、连接与通知",
                    "screen": "屏幕、壁纸与媒体",
                    "diagnostics": "开发者诊断",
                }[name])
        self.settings_canvas.yview_moveto(0.0)

    def _card(self, parent, title, row, column, **grid):
        box = ttk.LabelFrame(parent, text=title, style="Card.TLabelframe")
        box.grid(row=row, column=column, sticky="nsew", padx=6, pady=6, **grid)
        return box

    def _dashboard_ui(self):
        self.dashboard.columnconfigure((0, 1, 2), weight=1)
        self.dashboard.rowconfigure(1, weight=1)
        self.metric_labels = {}
        for index, (key, title) in enumerate((("cpu", "CPU"), ("ram", "内存"), ("disk", "磁盘"))):
            card = self._card(self.dashboard, title, 0, index)
            label = ttk.Label(card, text="--%", style="Panel.TLabel",
                              font=("Bahnschrift", 28, "bold"))
            label.pack(anchor="w", padx=8, pady=8)
            self.metric_labels[key] = label
        device = self._card(self.dashboard, "设备联机与自动模式", 1, 0, columnspan=2)
        self.device_status = tk.Text(device, bg="#0f141c", fg=self.INK, insertbackground=self.INK,
                                     relief="flat", height=15, font=("Cascadia Mono", 10))
        self.device_status.pack(fill="both", expand=True)
        commands = tk.Frame(device, bg=self.PANEL)
        commands.pack(fill="x", pady=(8, 0))
        for label, command in (("刷新状态", "STATUS"), ("闲置信息", "MODE,IDLE"),
                               ("实验界面", "MODE,EXPERIMENT"), ("开发诊断", "DISPLAY,DEV")):
            ttk.Button(commands, text=label, command=lambda value=command: self.send(value)).pack(side="left", padx=3)
        notice = self._card(self.dashboard, "电脑通知镜像", 1, 2)
        ttk.Label(notice, text="授权后读取 Windows Toast，并自动在设备闲置界面展示。",
                  style="Muted.TLabel", wraplength=270).pack(anchor="w", pady=(0, 10))
        ttk.Button(notice, text="启用系统通知读取", style="Accent.TButton",
                   command=self.enable_notifications).pack(fill="x")
        self.notice_title = tk.StringVar(value="LABCAPSULE")
        self.notice_body = tk.StringVar(value="USB DESKTOP ONLINE")
        ttk.Entry(notice, textvariable=self.notice_title).pack(fill="x", pady=(16, 5))
        ttk.Entry(notice, textvariable=self.notice_body).pack(fill="x", pady=5)
        ttk.Button(notice, text="发送测试通知", command=self.send_manual_notice).pack(fill="x", pady=5)
        self.notice_state = ttk.Label(notice, text="可选组件未授权", style="Muted.TLabel")
        self.notice_state.pack(anchor="w", pady=8)

    def _screen_ui(self):
        self.screen.columnconfigure(0, weight=0)
        self.screen.columnconfigure(1, weight=1)
        preview_card = self._card(self.screen, "240 × 320 实机比例预览", 0, 0, rowspan=2)
        self.preview = tk.Canvas(preview_card, width=WIDTH, height=HEIGHT, bg="black",
                                 highlightthickness=1, highlightbackground=self.CYAN)
        self.preview.pack(padx=10, pady=10)
        ttk.Label(preview_card, text="预览由电脑生成；ESP32 只负责解码与显示",
                  style="Muted.TLabel").pack()

        media = self._card(self.screen, "当前壁纸 / GIF / 视频 / 桌宠", 0, 1)
        row = tk.Frame(media, bg=self.PANEL)
        row.pack(fill="x")
        ttk.Button(row, text="选择主媒体", style="Accent.TButton", command=self.choose_media).pack(side="left")
        ttk.Button(row, text="选择透明桌宠", command=self.choose_pet).pack(side="left", padx=6)
        ttk.Button(row, text="清除桌宠", command=self.clear_pet).pack(side="left")
        self.media_label = ttk.Label(media, text="尚未选择", style="Muted.TLabel")
        self.media_label.pack(anchor="w", pady=8)
        options = tk.Frame(media, bg=self.PANEL)
        options.pack(fill="x")
        self.fit_var = tk.StringVar(value="适应")
        self.bg_var = tk.StringVar(value="黑色")
        self.fps_var = tk.IntVar(value=6)
        self.zoom_var = tk.DoubleVar(value=1.0)
        self.pan_x_var = tk.IntVar(value=0)
        self.pan_y_var = tk.IntVar(value=0)
        self.pet_x_var = tk.IntVar(value=120)
        self.pet_y_var = tk.IntVar(value=300)
        self.pet_scale_var = tk.DoubleVar(value=1.0)
        fields = (
            ("画面", self.fit_var, ("适应", "填充")),
            ("补底", self.bg_var, ("黑色", "白色")),
            ("FPS", self.fps_var, tuple(range(1, MAX_FPS + 1))),
        )
        for title, variable, values in fields:
            group = tk.Frame(options, bg=self.PANEL)
            group.pack(side="left", padx=(0, 12))
            ttk.Label(group, text=title, style="Muted.TLabel").pack(anchor="w")
            ttk.Combobox(group, textvariable=variable, values=values, width=9,
                         state="readonly").pack()
        transform = tk.Frame(media, bg=self.PANEL)
        transform.pack(fill="x", pady=8)
        for title, variable, low, high, resolution in (
            ("缩放 0.25–8×", self.zoom_var, .25, 8, .05),
            ("水平偏移", self.pan_x_var, -240, 240, 1),
            ("垂直偏移", self.pan_y_var, -320, 320, 1),
        ):
            group = tk.Frame(transform, bg=self.PANEL)
            group.pack(side="left", fill="x", expand=True, padx=(0, 10))
            ttk.Label(group, text=title, style="Muted.TLabel").pack(anchor="w")
            tk.Scale(group, variable=variable, from_=low, to=high, resolution=resolution,
                     orient="horizontal", bg=self.PANEL, fg=self.INK,
                     troughcolor="#0f141c", highlightthickness=0, command=lambda _=None: self.preview_media()).pack(fill="x")
        pet_row = tk.Frame(media, bg=self.PANEL)
        pet_row.pack(fill="x")
        for title, variable in (("桌宠 X", self.pet_x_var), ("桌宠 Y", self.pet_y_var),
                                ("桌宠缩放", self.pet_scale_var)):
            ttk.Label(pet_row, text=title, style="Muted.TLabel").pack(side="left", padx=(0, 4))
            ttk.Entry(pet_row, textvariable=variable, width=7).pack(side="left", padx=(0, 12))
        buttons = tk.Frame(media, bg=self.PANEL)
        buttons.pack(fill="x", pady=(10, 0))
        ttk.Button(buttons, text="刷新预览", command=self.preview_media).pack(side="left")
        ttk.Button(buttons, text="处理并上传当前媒体", style="Accent.TButton",
                   command=self.process_upload).pack(side="left", padx=6)
        ttk.Button(buttons, text="播放", command=lambda: self.send("GIF,PLAY")).pack(side="left")
        ttk.Button(buttons, text="停止", command=lambda: self.send("GIF,STOP")).pack(side="left")
        ttk.Button(buttons, text="删除当前 GIF", command=lambda: self.send("GIF,DELETE")).pack(side="left")
        self.media_progress = ttk.Progressbar(media, maximum=100)
        self.media_progress.pack(fill="x", pady=(12, 2))
        self.media_state = ttk.Label(media, text="就绪", style="Muted.TLabel")
        self.media_state.pack(anchor="w")

        controls = self._card(self.screen, "屏幕直接控制", 1, 1)
        command_row = tk.Frame(controls, bg=self.PANEL)
        command_row.pack(fill="x")
        for label, command in (("主页", "DISPLAY,HOME"), ("设置", "DISPLAY,SETTINGS"),
                               ("开发", "DISPLAY,DEV"), ("色卡", "DISPLAY,TEST"),
                               ("颜色反转", "DISPLAY,INVERT"), ("背光开", "DISPLAY,BL,ON"),
                               ("背光关", "DISPLAY,BL,OFF")):
            ttk.Button(command_row, text=label, command=lambda value=command: self.send(value)).pack(side="left", padx=3)
        self.style_preset = tk.IntVar(value=0)
        self.wall_opacity = tk.IntVar(value=82)
        self.panel_opacity = tk.IntVar(value=76)
        self.hud_opacity = tk.IntVar(value=100)
        style_row = tk.Frame(controls, bg=self.PANEL)
        style_row.pack(fill="x", pady=(10, 0))
        for title, variable in (("预设", self.style_preset), ("壁纸透明度", self.wall_opacity),
                                ("面板透明度", self.panel_opacity), ("HUD 透明度", self.hud_opacity)):
            ttk.Label(style_row, text=title, style="Muted.TLabel").pack(side="left", padx=(0, 4))
            ttk.Entry(style_row, textvariable=variable, width=6).pack(side="left", padx=(0, 10))
        ttk.Button(style_row, text="应用界面样式", command=self.apply_style).pack(side="left")

    def _experiment_ui(self):
        self.experiment.columnconfigure(0, weight=0)
        self.experiment.columnconfigure(1, weight=1)
        setup = self._card(self.experiment, "实验控制", 0, 0)
        self.rate_var = tk.IntVar(value=100)
        self.duration_var = tk.IntVar(value=10)
        self.mock_var = tk.BooleanVar(value=False)
        for title, variable in (("采样率 Hz", self.rate_var), ("时长 s", self.duration_var)):
            ttk.Label(setup, text=title, style="Muted.TLabel").pack(anchor="w", pady=(4, 0))
            ttk.Entry(setup, textvariable=variable, width=18).pack(fill="x")
        ttk.Checkbutton(setup, text="Mock 数据", variable=self.mock_var,
                        command=self.set_mock).pack(anchor="w", pady=10)
        ttk.Button(setup, text="开始实验", style="Accent.TButton", command=self.start_experiment).pack(fill="x", pady=3)
        ttk.Button(setup, text="停止并保留", command=lambda: self.send("STOP")).pack(fill="x", pady=3)
        ttk.Button(setup, text="中止", command=lambda: self.send("ABORT")).pack(fill="x", pady=3)
        ttk.Button(setup, text="导出当前 CSV", command=self.export_csv).pack(fill="x", pady=(14, 3))
        self.sample_label = ttk.Label(setup, text="样本 0", style="Muted.TLabel")
        self.sample_label.pack(anchor="w", pady=6)

        live = self._card(self.experiment, "交互式实时六轴数据", 0, 1)
        self.motion_chart = InteractiveMotionChart(live)
        self.motion_chart.pack(fill="both", expand=True)
        self.latest_sample = ttk.Label(live, text="等待 DATA…", style="Muted.TLabel",
                                       font=("Cascadia Mono", 10))
        self.latest_sample.pack(anchor="w", pady=(8, 0))
        self.experiment.rowconfigure(0, weight=1)

    def _console_ui(self):
        toolbar = tk.Frame(self.console, bg=self.BG)
        toolbar.pack(fill="x", pady=(0, 6))
        ttk.Button(toolbar, text="PING", command=lambda: self.send("PING")).pack(side="left")
        ttk.Button(toolbar, text="HELP", command=lambda: self.send("HELP")).pack(side="left", padx=4)
        ttk.Button(toolbar, text="硬件诊断", command=lambda: self.send("DISPLAY,DEV")).pack(side="left")
        ttk.Button(toolbar, text="清空", command=lambda: self.log.delete("1.0", "end")).pack(side="right")
        self.command_var = tk.StringVar()
        entry = ttk.Entry(toolbar, textvariable=self.command_var)
        entry.pack(side="left", fill="x", expand=True, padx=10)
        entry.bind("<Return>", lambda _: self.send_console())
        ttk.Button(toolbar, text="发送", command=self.send_console).pack(side="left")
        self.log = tk.Text(self.console, bg="#080b10", fg="#b9f6ff", insertbackground=self.INK,
                           relief="flat", font=("Cascadia Mono", 9), wrap="none")
        self.log.pack(fill="both", expand=True)

    def _pet_ui(self):
        shell = tk.Frame(self.pet, bg=self.BG)
        shell.pack(fill="both", expand=True)
        canvas = tk.Canvas(shell, bg=self.BG, highlightthickness=0, borderwidth=0)
        scrollbar = ttk.Scrollbar(shell, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        body = tk.Frame(canvas, bg=self.BG)
        body_window = canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda _: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(
            body_window, width=event.width))

        def scroll_pet(event):
            if self.tabs.select() == str(self.pet):
                canvas.yview_scroll(-1 * int(event.delta / 120), "units")

        self.bind_all("<MouseWheel>", scroll_pet, add="+")
        body.columnconfigure(0, weight=0)
        body.columnconfigure(1, weight=3)
        body.columnconfigure(2, weight=2)
        body.rowconfigure(0, weight=1)
        avatar_card = self._card(body, "角色舞台", 0, 0)
        self.pet_avatar = PetAvatarCanvas(avatar_card, width=240, height=230,
                                          background=self.PANEL,
                                          on_activate=self.show_pet_overlay)
        self.pet_avatar.pack(padx=4, pady=4)
        self.pet_state_label = ttk.Label(avatar_card, text="IDLE · 等待交互",
                                         style="Muted.TLabel")
        self.pet_state_label.pack(anchor="center", pady=4)
        self.pet_avatar_source_label = ttk.Label(
            avatar_card, text="形象：内置矢量 · 本机渲染", style="Muted.TLabel", wraplength=230)
        self.pet_avatar_source_label.pack(anchor="center", pady=(0, 5))
        ttk.Button(avatar_card, text="统一桌宠管理", style="Accent.TButton",
                   command=self.show_avatar_library).pack(fill="x", pady=3)
        ttk.Button(avatar_card, text="同步当前角色到设备",
                   command=self.send_avatar_to_screen_studio).pack(fill="x", pady=3)
        self.pet_overlay_button = ttk.Button(avatar_card, text="显示桌面悬浮宠物",
                                             command=self.toggle_pet_overlay)
        self.pet_overlay_button.pack(fill="x", pady=3)
        ttk.Button(avatar_card, text="在设备打开桌宠界面", style="Accent.TButton",
                   command=self.show_device_pet).pack(fill="x", pady=3)
        ttk.Button(avatar_card, text="退出设备桌宠界面",
                   command=self.hide_device_pet).pack(fill="x", pady=3)
        self.pet_device_status = ttk.Label(
            avatar_card, text="设备桌宠：等待连接", style="Muted.TLabel", wraplength=230)
        self.pet_device_status.pack(anchor="w", pady=(5, 0))
        ttk.Label(avatar_card, text="拖动悬浮宠物移动；双击返回本页；右键隐藏。",
                  style="Muted.TLabel", wraplength=230).pack(anchor="w", pady=8)

        chat_card = self._card(body, "对话与实验陪伴", 0, 1)
        self.pet_chat = tk.Text(chat_card, bg="#0f141c", fg=self.INK,
                                insertbackground=self.INK, relief="flat", wrap="word",
                                font=("Microsoft YaHei UI", 10), padx=10, pady=10)
        self.pet_chat.pack(fill="both", expand=True)
        self.pet_chat.tag_configure("user", foreground=self.CYAN, spacing1=7)
        self.pet_chat.tag_configure("pet", foreground=self.INK, spacing1=7)
        self.pet_chat.tag_configure("claude", foreground=self.YELLOW, spacing1=7)
        self.pet_chat.tag_configure("event", foreground=self.MUTED, spacing1=7)
        self.pet_chat.configure(state="disabled")
        input_row = tk.Frame(chat_card, bg=self.PANEL)
        input_row.pack(fill="x", pady=(8, 0))
        self.pet_input = tk.StringVar()
        pet_entry = ttk.Entry(input_row, textvariable=self.pet_input)
        pet_entry.pack(side="left", fill="x", expand=True)
        pet_entry.bind("<Return>", lambda _: self.send_pet_message())
        ttk.Button(input_row, text="发送", style="Accent.TButton",
                   command=self.send_pet_message).pack(side="left", padx=(6, 0))
        self.mic_button = ttk.Button(input_row, text="🎙 说话 6 秒",
                                     command=self.record_pet_voice)
        self.mic_button.pack(side="left", padx=(6, 0))
        self.speech_status = ttk.Label(chat_card, text="麦克风：点击后由电脑录音并转写",
                                       style="Muted.TLabel")
        self.speech_status.pack(anchor="w", pady=(5, 0))
        quick = tk.Frame(chat_card, bg=self.PANEL)
        quick.pack(fill="x", pady=(7, 0))
        quick.columnconfigure((0, 1), weight=1)
        for index, (label, message) in enumerate((
                ("电脑状态", "请根据实时信息告诉我电脑目前的运行情况"),
                ("解释当前状态", "请解释当前设备和实验状态"),
                ("设计一个实验", "请帮我把想法整理成可测量的对照实验"),
                ("检查数据质量", "根据当前上下文提醒我检查实验数据质量"))):
            ttk.Button(quick, text=label,
                       command=lambda value=message: self.send_pet_message(value)).grid(
                           row=index // 2, column=index % 2, sticky="ew", padx=2, pady=2)

        settings_card = self._card(body, "角色与 AI 设置", 0, 2)
        self.pet_name_var = tk.StringVar(value=self.pet_settings.profile.name)
        self.pet_endpoint_var = tk.StringVar(value=self.pet_settings.endpoint)
        self.pet_model_var = tk.StringVar(value=self.pet_settings.model)
        self.pet_key_var = tk.StringVar(value=self.pet_settings.api_key)
        self.pet_memory_var = tk.BooleanVar(value=self.pet_settings.remember)
        self.pet_sync_var = tk.BooleanVar(value=self.pet_settings.sync_device)
        self.pet_auto_var = tk.BooleanVar(value=self.pet_settings.auto_react)
        self.pet_delegate_var = tk.BooleanVar(value=self.pet_settings.delegate_complex)
        self.pet_claude_model_var = tk.StringVar(value=self.pet_settings.claude_model)
        self.memory_sync_var = tk.BooleanVar(value=self.pet_settings.memory_sync_enabled)
        self.memory_repository_var = tk.StringVar(value=self.pet_settings.memory_repository)
        self.memory_branch_var = tk.StringVar(value=self.pet_settings.memory_branch)
        self.memory_token_var = tk.StringVar(value=self.pet_settings.memory_token)
        self.speech_endpoint_var = tk.StringVar(value=self.pet_settings.speech_endpoint)
        self.speech_model_var = tk.StringVar(value=self.pet_settings.speech_model)
        self.speech_key_var = tk.StringVar(value=self.pet_settings.speech_api_key)
        for title, variable, secret in (("角色名称", self.pet_name_var, False),
                                        ("OpenAI 兼容 Endpoint", self.pet_endpoint_var, False),
                                        ("模型", self.pet_model_var, False),
                                        ("API Key（DPAPI 加密）", self.pet_key_var, True)):
            ttk.Label(settings_card, text=title, style="Muted.TLabel").pack(anchor="w", pady=(5, 2))
            ttk.Entry(settings_card, textvariable=variable, show="•" if secret else "").pack(fill="x")
        ttk.Label(settings_card, text="电脑麦克风转写（可单独配置）",
                  style="Muted.TLabel").pack(anchor="w", pady=(8, 2))
        for title, variable, secret in (
                ("语音 Endpoint", self.speech_endpoint_var, False),
                ("语音模型", self.speech_model_var, False),
                ("语音 API Key（DPAPI 加密）", self.speech_key_var, True)):
            ttk.Label(settings_card, text=title, style="Muted.TLabel").pack(anchor="w", pady=(4, 2))
            ttk.Entry(settings_card, textvariable=variable,
                      show="•" if secret else "").pack(fill="x")
        ttk.Label(settings_card, text="角色设定", style="Muted.TLabel").pack(anchor="w", pady=(8, 2))
        self.pet_persona = tk.Text(settings_card, height=4, bg="#0f141c", fg=self.INK,
                                   insertbackground=self.INK, relief="flat", wrap="word",
                                   font=("Microsoft YaHei UI", 9))
        self.pet_persona.insert("1.0", self.pet_settings.profile.persona)
        self.pet_persona.pack(fill="x")
        ttk.Checkbutton(settings_card, text="保存最近对话与用户偏好",
                        variable=self.pet_memory_var).pack(anchor="w", pady=(8, 0))
        ttk.Checkbutton(settings_card, text="把安全的短状态同步到设备屏幕",
                        variable=self.pet_sync_var).pack(anchor="w")
        ttk.Checkbutton(settings_card, text="自动响应连接/实验完成/错误事件",
                        variable=self.pet_auto_var).pack(anchor="w")
        ttk.Checkbutton(settings_card, text="复杂任务自动转交本机 Claude（只读安全模式）",
                        variable=self.pet_delegate_var).pack(anchor="w")
        claude_row = tk.Frame(settings_card, bg=self.PANEL)
        claude_row.pack(fill="x", pady=(5, 0))
        ttk.Label(claude_row, text="Claude 模型", style="Muted.TLabel").pack(side="left")
        ttk.Entry(claude_row, textvariable=self.pet_claude_model_var, width=12).pack(
            side="left", padx=6)
        self.claude_state_label = ttk.Label(
            settings_card,
            text=("Claude：已检测，可受限调用" if self.claude_bridge.available else
                  "Claude：本机未安装，自动使用主 AI"),
            style="Muted.TLabel", wraplength=285)
        self.claude_state_label.pack(anchor="w", pady=(4, 0))
        ttk.Button(settings_card, text="保存角色与 AI 设置", style="Accent.TButton",
                   command=self.save_pet_settings).pack(fill="x", pady=(10, 3))
        ttk.Separator(settings_card).pack(fill="x", pady=9)
        ttk.Label(settings_card, text="跨设备私有记忆", style="Muted.TLabel").pack(anchor="w")
        ttk.Checkbutton(settings_card, text="连接设备后同步私有 GitHub 记忆仓库",
                        variable=self.memory_sync_var).pack(anchor="w", pady=(5, 0))
        for title, variable, secret in (
                ("私有仓库 owner/repository", self.memory_repository_var, False),
                ("分支", self.memory_branch_var, False),
                ("GitHub Token（仅当前 Windows 用户可解密）", self.memory_token_var, True)):
            ttk.Label(settings_card, text=title, style="Muted.TLabel").pack(anchor="w", pady=(5, 2))
            ttk.Entry(settings_card, textvariable=variable,
                      show="•" if secret else "").pack(fill="x")
        self.memory_sync_status = ttk.Label(
            settings_card, text="记忆同步：等待稳定设备 ID", style="Muted.TLabel", wraplength=285)
        self.memory_sync_status.pack(anchor="w", pady=(6, 2))
        ttk.Button(settings_card, text="立即同步当前设备记忆",
                   command=self.sync_memory_now).pack(fill="x", pady=3)
        ttk.Button(settings_card, text="清除桌宠记忆", command=self.clear_pet_memory).pack(fill="x", pady=3)
        ttk.Separator(settings_card).pack(fill="x", pady=9)
        ttk.Label(settings_card, text="完整角色卡（PC / 手机）",
                  style="Muted.TLabel").pack(anchor="w")
        self.role_card_status = ttk.Label(
            settings_card, text="角色卡：选择静态预览后可上传当前 Live2D；完整包按需缓存。",
            style="Muted.TLabel", wraplength=285)
        self.role_card_status.pack(anchor="w", pady=(5, 3))
        role_files = tk.Frame(settings_card, bg=self.PANEL)
        role_files.pack(fill="x")
        ttk.Button(role_files, text="选择预览", command=self.choose_role_preview).pack(
            side="left", fill="x", expand=True, padx=(0, 2))
        ttk.Button(role_files, text="选择语音包", command=self.choose_role_voice).pack(
            side="left", fill="x", expand=True, padx=(2, 0))
        ttk.Button(settings_card, text="上传当前完整角色卡", style="Accent.TButton",
                   command=self.upload_current_role_card).pack(fill="x", pady=3)
        ttk.Button(settings_card, text="同步并选择私有仓库角色卡",
                   command=self.show_role_card_library).pack(fill="x", pady=3)
        ttk.Separator(settings_card).pack(fill="x", pady=9)
        ttk.Label(settings_card, text="手机访问电脑（需明确授权）",
                  style="Muted.TLabel").pack(anchor="w")
        self.mobile_bridge_status = ttk.Label(
            settings_card,
            text="手机桥：关闭。开启后在手机输入这里显示的一次性配对码。",
            style="Muted.TLabel", wraplength=285)
        self.mobile_bridge_status.pack(anchor="w", pady=(5, 3))
        self.mobile_bridge_button = ttk.Button(
            settings_card, text="开启手机桥并生成配对码", command=self.toggle_mobile_bridge)
        self.mobile_bridge_button.pack(fill="x", pady=3)
        ttk.Label(settings_card,
                  text="个人记忆只允许写入私有仓库；Token 不写入仓库。Claude 桥禁用全部工具且不保存会话；"
                       "手机桥仅开放电脑/实验状态和受限 Claude 分析，不开放 Shell、文件或任意设备操作；"
                       "启动/中止实验、网络和固件操作始终由用户确认。",
                  style="Muted.TLabel", wraplength=285).pack(anchor="w", pady=8)
        self._pet_append("event", f"{self.pet_settings.profile.name}：{self.pet_settings.profile.greeting}")

    def show_avatar_library(self):
        if self.avatar_library_window is not None and self.avatar_library_window.winfo_exists():
            self.avatar_library_window.deiconify()
            self.avatar_library_window.lift()
            self.avatar_library_window.focus_force()
            return
        window = tk.Toplevel(self)
        self.avatar_library_window = window
        window.title("统一桌宠管理 · 文件夹与网络")
        window.geometry("680x700")
        window.minsize(610, 560)
        window.configure(bg=self.BG)
        window.transient(self)
        window.protocol("WM_DELETE_WINDOW", self._close_avatar_library)

        shell = tk.Frame(window, bg=self.BG)
        shell.pack(fill="both", expand=True)
        canvas = tk.Canvas(shell, bg=self.BG, highlightthickness=0, borderwidth=0)
        scrollbar = ttk.Scrollbar(shell, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        content = tk.Frame(canvas, bg=self.BG)
        content_window = canvas.create_window((0, 0), window=content, anchor="nw")
        content.bind("<Configure>", lambda _event: canvas.configure(
            scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(
            content_window, width=event.width))
        window.bind("<MouseWheel>", lambda event: canvas.yview_scroll(
            -1 if event.delta > 0 else 1, "units"))

        header = tk.Frame(content, bg=self.BG, padx=18, pady=10)
        header.pack(fill="x")
        tk.Label(header, text="UNIFIED PET / LIBRARY", bg=self.BG, fg=self.INK,
                 font=("Bahnschrift", 17, "bold")).pack(anchor="w")
        tk.Label(header, text="一个角色包统一 AI 身份与桌面舞台；图片/GIF 可交给 240×320 屏幕工作室。",
                 bg=self.BG, fg=self.CYAN, font=("Microsoft YaHei UI", 9)).pack(anchor="w", pady=(4, 0))

        local = ttk.LabelFrame(content, text="本地统一桌宠角色包", style="Card.TLabelframe")
        local.pack(fill="x", padx=18, pady=4)
        self.pet_package_box = ttk.Combobox(local, textvariable=self.pet_package_var,
                                            state="readonly")
        self.pet_package_box.pack(fill="x")
        local_buttons = tk.Frame(local, bg=self.PANEL)
        local_buttons.pack(fill="x", pady=(7, 0))
        ttk.Button(local_buttons, text="选择桌宠 / 库文件夹", style="Accent.TButton",
                   command=self.choose_pet_package_folder).pack(side="left")
        ttk.Button(local_buttons, text="应用所选统一桌宠",
                   command=self.apply_selected_pet_package).pack(side="left", padx=6)
        self.pet_package_status = ttk.Label(
            local, text="可选择含 pet.json 的桌宠文件夹，或包含多个桌宠子文件夹的库。",
            style="Muted.TLabel", wraplength=610)
        self.pet_package_status.pack(anchor="w", pady=(6, 0))

        preset = ttk.LabelFrame(content, text="通用预设 · DiceBear CC0", style="Card.TLabelframe")
        preset.pack(fill="x", padx=18, pady=4)
        ttk.Combobox(preset, textvariable=self.avatar_preset_var,
                     values=tuple(DICEBEAR_CC0_PRESETS), state="readonly").pack(fill="x")
        seed_row = tk.Frame(preset, bg=self.PANEL)
        seed_row.pack(fill="x", pady=(8, 0))
        ttk.Label(seed_row, text="角色种子", style="Muted.TLabel").pack(side="left")
        ttk.Entry(seed_row, textvariable=self.avatar_seed_var).pack(side="left", fill="x",
                                                                    expand=True, padx=8)
        ttk.Button(seed_row, text="生成并应用", style="Accent.TButton",
                   command=self.apply_dicebear_avatar).pack(side="left")

        direct = ttk.LabelFrame(content, text="任意网络图片直链", style="Card.TLabelframe")
        direct.pack(fill="x", padx=18, pady=4)
        ttk.Entry(direct, textvariable=self.avatar_url_var).pack(fill="x")
        direct_buttons = tk.Frame(direct, bg=self.PANEL)
        direct_buttons.pack(fill="x", pady=(8, 0))
        ttk.Button(direct_buttons, text="下载并应用", style="Accent.TButton",
                   command=self.download_network_avatar).pack(side="left")
        ttk.Button(direct_buttons, text="恢复内置矢量形象",
                   command=self.restore_vector_avatar).pack(side="left", padx=6)
        ttk.Button(direct_buttons, text="同步角色 / 送到屏幕工作室",
                   command=self.send_avatar_to_screen_studio).pack(side="left")
        self.avatar_progress = ttk.Progressbar(direct, maximum=100)
        self.avatar_progress.pack(fill="x", pady=(10, 3))
        self.avatar_library_status = ttk.Label(
            direct, text="支持 PNG / JPG / WebP / GIF；HTTPS；最大 12 MiB、2048²、120 帧。",
            style="Muted.TLabel", wraplength=590)
        self.avatar_library_status.pack(anchor="w")

        resources = ttk.LabelFrame(content, text="官方形象与授权入口", style="Card.TLabelframe")
        resources.pack(fill="x", padx=18, pady=(4, 18))
        ttk.Label(resources,
                  text="CC0 预设可直接生成稳定 PNG。Live2D 可直接识别 model3.json / moc3 / "
                       "motion3.json 运行时资源；首次运行前须由用户确认 Cubism SDK 条款。",
                  style="Muted.TLabel", wraplength=590).pack(anchor="w", pady=(0, 8))
        links = (
            ("DiceBear 风格目录", "https://www.dicebear.com/styles/"),
            ("DiceBear 许可证", "https://www.dicebear.com/licenses/"),
            ("VRoid Studio", "https://vroid.com/en/studio"),
            ("VRoid Hub", "https://hub.vroid.com/en"),
            ("Live2D 示例与条款", "https://www.live2d.com/en/learn/sample/"),
            ("Live2D 文件类型", "https://docs.live2d.com/en/cubism-editor-manual/"
                                "file-type-and-extension/"),
            ("Cubism SDK 许可", "https://www.live2d.com/en/sdk/license/"),
            ("可扩展应用许可", "https://www.live2d.com/en/sdk/license/expandable/"),
            ("LabCapsule 统一桌宠手册",
             "https://github.com/81823650800wzy-sketch/LabCapsule/blob/main/docs/"
             "V1.0.0_UNIFIED_ASSISTANT_GUIDE_ZH.md"),
        )
        link_grid = tk.Frame(resources, bg=self.PANEL)
        link_grid.pack(fill="x")
        for index, (label, url) in enumerate(links):
            ttk.Button(link_grid, text=label,
                       command=lambda target=url: webbrowser.open(target)).grid(
                           row=index // 3, column=index % 3, sticky="ew", padx=3, pady=3)
        ttk.Button(link_grid, text="Live2D 播放层第三方许可",
                   command=self._show_live2d_notices).grid(
                       row=len(links) // 3, column=len(links) % 3,
                       sticky="ew", padx=3, pady=3)
        for index in range(3):
            link_grid.columnconfigure(index, weight=1)
        ttk.Label(resources,
                  text="安全提示：请粘贴图片文件本身的地址，不要粘贴网页、ZIP 或带账户凭据的链接。"
                       "下载失败时，已缓存的当前形象不会被覆盖。",
                  style="Muted.TLabel", wraplength=590).pack(anchor="w", pady=(10, 0))
        self._scan_default_pet_folders()

    def _show_live2d_notices(self):
        notice_path = ROOT / "live2d_web" / "THIRD_PARTY_NOTICES.md"
        try:
            contents = notice_path.read_text(encoding="utf-8")
        except OSError as error:
            messagebox.showerror("无法读取第三方许可", str(error))
            return
        window = tk.Toplevel(self)
        window.title("Live2D 播放层第三方许可")
        window.geometry("720x600")
        window.configure(bg=self.BG)
        text_box = tk.Text(window, bg="#0f141c", fg=self.INK, insertbackground=self.INK,
                           wrap="word", padx=16, pady=16, font=("Consolas", 9))
        text_box.insert("1.0", contents)
        text_box.configure(state="disabled")
        scrollbar = ttk.Scrollbar(window, orient="vertical", command=text_box.yview)
        text_box.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        text_box.pack(fill="both", expand=True)

    def _close_avatar_library(self):
        if self.avatar_library_window is not None:
            self.avatar_library_window.destroy()
        self.avatar_library_window = None

    def _set_avatar_status(self, text: str, progress: int | None = None):
        if (self.avatar_library_window is not None
                and self.avatar_library_window.winfo_exists()):
            self.avatar_library_status.configure(text=text)
            if progress is not None:
                self.avatar_progress["value"] = progress

    def _set_pet_package_choices(self, packages: list[PetPackage], errors: list[str],
                                 source: str):
        self.pet_package_choices = {package.display_name: package for package in packages}
        values = tuple(self.pet_package_choices)
        self.pet_package_box["values"] = values
        if values:
            self.pet_package_var.set(values[0])
            detail = f"识别到 {len(values)} 个桌宠 · {source}"
        else:
            self.pet_package_var.set("")
            detail = f"未识别到桌宠 · {source}"
        if errors:
            detail += "；" + "；".join(errors[:3])
        self.pet_package_status.configure(text=detail)

    def _scan_default_pet_folders(self):
        roots = [PET_SELECTION_PATH.parent / "pets", ROOT.parent / "pets"]
        if getattr(sys, "frozen", False):
            roots.append(Path(sys.executable).resolve().parent / "pets")
        selected = selected_pet_package()
        if selected is not None:
            roots.insert(0, Path(selected.folder).parent)
        packages: list[PetPackage] = []
        errors: list[str] = []
        seen: set[tuple[str, str]] = set()
        for root in roots:
            if not root.is_dir():
                continue
            found, found_errors = discover_pet_packages(root)
            for package in found:
                key = package.package_id, package.folder
                if key not in seen:
                    seen.add(key)
                    packages.append(package)
            errors.extend(found_errors)
        self._set_pet_package_choices(packages, errors, "默认桌宠目录")
        if selected is not None:
            match = next((label for label, package in self.pet_package_choices.items()
                          if package.package_id == selected.package_id
                          and package.folder == selected.folder), None)
            if match:
                self.pet_package_var.set(match)

    def choose_pet_package_folder(self):
        folder = filedialog.askdirectory(title="选择桌宠角色包或桌宠库文件夹")
        if not folder:
            return
        packages, errors = discover_pet_packages(folder)
        self._set_pet_package_choices(packages, errors, folder)
        if not packages:
            messagebox.showwarning(
                "没有可用桌宠",
                "请选择包含 pet.json 的角色包，或仅含一个 PNG/JPG/WebP/GIF / "
                "Live2D model3.json 的文件夹。")

    def apply_selected_pet_package(self):
        package = self.pet_package_choices.get(self.pet_package_var.get())
        if package is None:
            messagebox.showwarning("未选择桌宠", "请先选择桌宠文件夹并在列表中选择一个角色包。")
            return
        if self.avatar_download_active:
            self.pet_package_status.configure(text="已有形象正在处理，请稍候。")
            return
        if package.visual_kind == "live2d":
            self._apply_live2d_package(package)
            return
        self.avatar_download_active = True
        self.pet_package_status.configure(text=f"正在校验并载入 {package.name}…")

        def worker():
            try:
                asset = avatar_asset_for_package(package)
                self.events.put(("pet_package_done", (package, decode_avatar(asset, 240))))
            except Exception as error:
                self.events.put(("pet_package_error", str(error)))

        threading.Thread(target=worker, daemon=True, name="pet-package-load").start()

    def _apply_pet_package_decoded(self, package: PetPackage, decoded: DecodedAvatar,
                                   persist: bool = True):
        self._stop_live2d_players()
        clear_cached_avatar(AVATAR_CACHE_DIR)
        self._apply_avatar_decoded(decoded, f"{package.name} · 统一角色包")
        self.active_pet_package = package
        self._apply_pet_package_profile(package)
        if self.role_profile_override is not None:
            profile = self.role_profile_override
            self.role_profile_override = None
            self.pet_settings.profile = profile
            self.pet_runtime.update_settings(self.pet_settings)
            self.pet_name_var.set(profile.name)
            self.pet_persona.delete("1.0", "end")
            self.pet_persona.insert("1.0", profile.persona)
        if persist:
            save_selected_pet(package)
        license_text = f" · {package.license}" if package.license else ""
        if hasattr(self, "pet_package_status"):
            self.pet_package_status.configure(
                text=f"已应用 {package.name} [{package.package_id}]{license_text}；"
                     "三个舞台使用同一主形象。")
        self._pet_append("event", f"统一桌宠“{package.name}”已应用：形象、名称、人格和欢迎语同步。")

    def _apply_pet_package_profile(self, package: PetPackage):
        profile = CharacterProfile(name=package.name, persona=package.persona,
                                   greeting=package.greeting)
        self.pet_settings.profile = profile
        self.pet_settings.avatar_url = ""
        self.pet_settings.avatar_source_name = package.name
        self.pet_runtime.update_settings(self.pet_settings)
        self.pet_name_var.set(profile.name)
        self.pet_persona.delete("1.0", "end")
        self.pet_persona.insert("1.0", profile.persona)

    def _apply_live2d_package(self, package: PetPackage):
        if has_live2d_consent():
            self._activate_live2d_package(package)
            return
        self._show_live2d_consent(package)

    def _show_live2d_consent(self, package: PetPackage):
        if self.live2d_license_window is not None and self.live2d_license_window.winfo_exists():
            self.live2d_license_window.deiconify()
            self.live2d_license_window.lift()
            return
        window = tk.Toplevel(self)
        self.live2d_license_window = window
        window.title("启用 Live2D Cubism 运行时")
        window.geometry("620x460")
        window.minsize(560, 420)
        window.configure(bg=self.BG)
        window.transient(self)
        window.grab_set()

        def close_window():
            if window.winfo_exists():
                window.grab_release()
                window.destroy()
            self.live2d_license_window = None

        window.protocol("WM_DELETE_WINDOW", close_window)
        body = tk.Frame(window, bg=self.BG, padx=24, pady=20)
        body.pack(fill="both", expand=True)
        tk.Label(body, text="LIVE2D / RUNTIME CONSENT", bg=self.BG, fg=self.INK,
                 font=("Bahnschrift", 18, "bold")).pack(anchor="w")
        tk.Label(
            body,
            text=(f"即将用 Live2D Cubism Web 运行时打开“{package.name}”。\n\n"
                  "LabCapsule 不随应用分发 Cubism Core；播放器会在启动时从 Live2D 官方地址"
                  "载入固定版本 Core。模型文件只通过本机 127.0.0.1 提供，不上传到网络。\n\n"
                  "Hiyori 等示例模型仍受各自条款约束；允许本机开发测试不等同于允许重新分发。"
                  "若产品允许用户任意选择模型，正式发布前还需核对 Expandable Application 许可。"),
            bg=self.BG, fg=self.MUTED, justify="left", wraplength=560,
            font=("Microsoft YaHei UI", 10)).pack(anchor="w", pady=(14, 12))
        links = tk.Frame(body, bg=self.BG)
        links.pack(fill="x")
        for label, url in (
            ("查看文件类型手册", "https://docs.live2d.com/en/cubism-editor-manual/"
                                 "file-type-and-extension/"),
            ("查看 SDK 许可", "https://www.live2d.com/en/sdk/license/"),
            ("查看可扩展应用许可", "https://www.live2d.com/en/sdk/license/expandable/"),
        ):
            ttk.Button(links, text=label, command=lambda target=url: webbrowser.open(target)).pack(
                side="left", padx=(0, 6))
        accepted = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            body, variable=accepted,
            text="我已阅读并同意适用于当前开发测试的 Live2D / Cubism 条款，且有权使用所选模型",
        ).pack(anchor="w", pady=(18, 8))
        feedback = ttk.Label(body, text="必须由你亲自勾选后才能启用。",
                             style="Muted.TLabel")
        feedback.pack(anchor="w")

        def confirm():
            if not accepted.get():
                feedback.configure(text="尚未勾选确认；播放器没有启动。", foreground=self.RED)
                return
            try:
                save_live2d_consent()
            except Exception as error:
                messagebox.showerror("无法保存许可确认", str(error), parent=window)
                return
            close_window()
            self._activate_live2d_package(package)

        actions = tk.Frame(body, bg=self.BG)
        actions.pack(fill="x", side="bottom")
        ttk.Button(actions, text="取消", command=close_window).pack(side="right")
        ttk.Button(actions, text="确认并启动", style="Accent.TButton",
                   command=confirm).pack(side="right", padx=8)

    def _activate_live2d_package(self, package: PetPackage, persist: bool = True,
                                 autolaunch: bool = True):
        if package.visual_kind != "live2d" or not package.live2d_model_path:
            raise ValueError("角色包不是有效的 Live2D 运行时模型")
        self._stop_live2d_players()
        clear_cached_avatar(AVATAR_CACHE_DIR)
        self.avatar_decoded = None
        self.active_pet_package = package
        self.pet_avatar.clear_custom_avatar()
        if self.pet_overlay is not None:
            self.pet_overlay.destroy()
            self.pet_overlay = None
        self._apply_pet_package_profile(package)
        if self.role_profile_override is not None:
            profile = self.role_profile_override
            self.role_profile_override = None
            self.pet_settings.profile = profile
            self.pet_runtime.update_settings(self.pet_settings)
            self.pet_name_var.set(profile.name)
            self.pet_persona.delete("1.0", "end")
            self.pet_persona.insert("1.0", profile.persona)
        self.avatar_url_var.set("")
        self.pet_avatar_source_label.configure(
            text=f"形象：Live2D · {package.live2d_motion_count} 个动作 · 独立 GPU 舞台")
        if persist:
            save_selected_pet(package)
        if hasattr(self, "pet_package_status"):
            self.pet_package_status.configure(
                text=f"已应用 {package.name} [{package.package_id}] · Live2D · "
                     f"{package.live2d_motion_count} 个动作")
        self._set_avatar_status("Live2D 模型已通过路径和依赖校验；运行时仅监听本机。", 100)
        self._set_pet_state("happy", "LIVE2D READY")
        self._pet_append("event", f"Live2D 桌宠“{package.name}”已应用；点击模型可触发动作。")
        if autolaunch:
            self._launch_live2d_player(package, "stage")

    def _cleanup_live2d_processes(self):
        self.live2d_processes = [item for item in self.live2d_processes
                                 if item[1].poll() is None]

    def _launch_live2d_player(self, package: PetPackage, mode: str):
        self._cleanup_live2d_processes()
        try:
            command = player_command(package.live2d_model_path, mode, ROOT, sys.executable,
                                     control_path=CONTROL_PATH)
            flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            process = subprocess.Popen(command, creationflags=flags)
            self.live2d_processes.append((mode, process))
            self._append_log(f"> Live2D {mode} 已启动：{package.name}")
        except Exception as error:
            messagebox.showerror("Live2D 播放器启动失败", str(error))

    def _stop_live2d_players(self, mode: str | None = None):
        kept: list[tuple[str, subprocess.Popen]] = []
        for player_mode, process in self.live2d_processes:
            if process.poll() is not None:
                continue
            if mode is None or player_mode == mode:
                try:
                    process.terminate()
                except OSError:
                    pass
            else:
                kept.append((player_mode, process))
        self.live2d_processes = kept

    def _restore_selected_pet_or_avatar(self):
        package = selected_pet_package()
        if package is None:
            self._restore_cached_avatar()
            return

        if package.visual_kind == "live2d":
            if has_live2d_consent():
                self._activate_live2d_package(package, persist=False)
            else:
                self._append_log("! 已保存 Live2D 桌宠等待用户确认 Cubism 条款")
                self._restore_cached_avatar()
            return

        def worker():
            try:
                asset = avatar_asset_for_package(package)
                self.events.put(("pet_package_restore_done", (package, decode_avatar(asset, 240))))
            except Exception as error:
                self.events.put(("pet_package_restore_error", str(error)))

        threading.Thread(target=worker, daemon=True, name="pet-package-restore").start()

    def apply_dicebear_avatar(self):
        label = self.avatar_preset_var.get()
        style = DICEBEAR_CC0_PRESETS.get(label)
        if style is None:
            messagebox.showwarning("预设无效", "请选择一个 DiceBear CC0 预设。")
            return
        self.avatar_url_var.set(dicebear_url(style, self.avatar_seed_var.get()))
        self.download_network_avatar(label)

    def download_network_avatar(self, source_name: str = "自定义网络形象"):
        if self.avatar_download_active:
            self._set_avatar_status("已有形象正在下载，请稍候。")
            return
        url = self.avatar_url_var.get().strip()
        self.avatar_download_active = True
        self._set_avatar_status("正在安全下载并检查图片…", 0)

        def worker():
            try:
                asset = download_avatar(
                    url, AVATAR_CACHE_DIR,
                    progress=lambda value: self.events.put(("avatar_progress", value)))
                decoded = decode_avatar(asset, 240)
                self.events.put(("avatar_done", (decoded, source_name)))
            except Exception as error:
                self.events.put(("avatar_error", str(error)))

        threading.Thread(target=worker, daemon=True, name="avatar-download").start()

    def _restore_cached_avatar(self):
        def worker():
            asset = load_cached_avatar(AVATAR_CACHE_DIR)
            if asset is None:
                return
            try:
                self.events.put(("avatar_restore_done", decode_avatar(asset, 240)))
            except Exception as error:
                self.events.put(("avatar_restore_error", str(error)))
        threading.Thread(target=worker, daemon=True, name="avatar-cache-load").start()

    def _apply_avatar_decoded(self, decoded: DecodedAvatar, source_name: str):
        self.avatar_decoded = decoded
        self.pet_avatar.set_custom_avatar(decoded.frames, decoded.durations_ms)
        if self.pet_overlay is not None:
            self.pet_overlay.set_custom_avatar(decoded.frames, decoded.durations_ms)
        self.pet_avatar_source_label.configure(
            text=f"形象：{source_name} · {decoded.asset.format} / {decoded.asset.frames} 帧")
        self.avatar_url_var.set(decoded.asset.source_url)
        self.pet_settings.avatar_url = decoded.asset.source_url
        self.pet_settings.avatar_source_name = source_name
        self._set_avatar_status(
            f"已应用：{decoded.asset.width}×{decoded.asset.height}、{decoded.asset.frames} 帧、"
            f"{decoded.asset.bytes / 1024:.1f} KiB\n{display_url(decoded.asset.final_url)}", 100)
        self._set_pet_state("happy", "AVATAR READY")

    def restore_vector_avatar(self):
        self._stop_live2d_players()
        clear_cached_avatar(AVATAR_CACHE_DIR)
        clear_selected_pet()
        self.avatar_decoded = None
        self.active_pet_package = None
        self.avatar_url_var.set("")
        self.pet_settings.avatar_url = ""
        self.pet_settings.avatar_source_name = "内置矢量形象"
        self.pet_avatar.clear_custom_avatar()
        if self.pet_overlay is not None:
            self.pet_overlay.clear_custom_avatar()
        self.pet_avatar_source_label.configure(text="形象：内置矢量 · 本机渲染")
        self._set_avatar_status("已恢复内置矢量形象；网络缓存已清除。", 0)
        self._set_pet_state("idle", "VECTOR AVATAR")

    def send_avatar_to_screen_studio(self):
        if self.active_pet_package is not None and self.active_pet_package.visual_kind == "live2d":
            self.capture_live2d_device_proxy()
            return
        if self.avatar_decoded is None:
            messagebox.showinfo("当前是内置形象",
                                "内置矢量形象不是媒体文件。请先下载网络 PNG / GIF 形象。")
            return
        self.media_path = self.avatar_decoded.asset.path
        self.pet_path = ""
        self.media_label.configure(text=f"网络形象 · {Path(self.media_path).name}")
        self.tabs.select(self.settings)
        self.open_settings_section("screen")
        self.preview_media()
        self.media_state.configure(text="网络形象已载入；确认预览后可通过当前链路上传，不会自动写入设备。")

    def capture_live2d_device_proxy(self):
        package = self.active_pet_package
        if package is None or package.visual_kind != "live2d":
            messagebox.showwarning("没有 Live2D", "请先应用一个 Live2D 角色包。")
            return
        if not has_live2d_consent():
            messagebox.showwarning("尚未确认许可", "请先在角色库中完成 Live2D/Cubism 条款确认。")
            return
        if not self.link.connected:
            messagebox.showwarning("设备未连接", "请先通过 USB、局域网或 BLE 连接设备。")
            return
        self.avatar_download_active = True
        self._set_avatar_status("正在由 GPU 渲染同一 Hiyori 的 240×320 设备代理…", 2)
        cache = APP_DIR / "pet-proxies" / package.package_id

        def worker():
            process = None
            try:
                cache.mkdir(parents=True, exist_ok=True)
                for stale in list(cache.glob("frame-*.png")) + [cache / "capture.json"]:
                    if stale.is_file():
                        stale.unlink()
                command = player_command(package.live2d_model_path, "capture", ROOT,
                                         sys.executable, capture_path=cache)
                flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
                process = subprocess.Popen(command, creationflags=flags)
                self.live2d_processes.append(("capture", process))
                return_code = process.wait(timeout=90)
                self._cleanup_live2d_processes()
                if return_code != 0:
                    raise RuntimeError(f"Live2D 捕获子进程退出码 {return_code}")
                metadata = json.loads((cache / "capture.json").read_text(encoding="utf-8"))
                if metadata.get("complete") is not True:
                    raise RuntimeError("Live2D 捕获未完成")
                paths = sorted(cache.glob("frame-*.png"))
                if len(paths) != int(metadata.get("frames", 0)):
                    raise RuntimeError("Live2D 捕获帧数量不完整")
                frames: list[Image.Image] = []
                for path in paths:
                    with Image.open(path) as source:
                        frames.append(source.convert("RGBA").copy())
                fps = max(1, min(MAX_FPS, round(1000 / int(metadata["durationMs"]))))
                result = build_clip_from_frames(
                    frames, fps=fps,
                    progress=lambda value: self.events.put(("avatar_progress", value)))
                temporary = cache / "device-proxy.tmp"
                final = cache / "device-proxy.lcg"
                temporary.write_bytes(result.payload)
                temporary.replace(final)
                self.events.put(("media_state", f"Hiyori 代理 {len(result.payload):,} B，通过当前链路写入设备…"))
                self.link.upload("CLIP", result.payload,
                                 lambda value: self.events.put(("avatar_progress", value)))
                self.link.send(f"PET,IDENTITY,{package.package_id},PROXY")
                self.link.send("PET,SHOW")
                self.events.put(("live2d_proxy_done", (package, result, final)))
            except subprocess.TimeoutExpired as error:
                if process is not None:
                    process.terminate()
                self.events.put(("live2d_proxy_error", f"Live2D 捕获超过 90 秒：{error}"))
            except Exception as error:
                self.events.put(("live2d_proxy_error", str(error)))

        threading.Thread(target=worker, daemon=True, name="live2d-device-proxy").start()

    def refresh_ports(self):
        mode = self.transport_var.get()
        if mode == "局域网 WiFi":
            self.port_box.configure(state="normal")
            self.port_box["values"] = ()
            if not self.port_var.get() or self.port_var.get().upper().startswith("COM"):
                self.port_var.set("http://")
            self.scan_button.configure(text="校验地址")
            return
        if mode == "蓝牙 BLE":
            self.port_box.configure(state="normal")
            self.port_box["values"] = ("LabCapsule",)
            self.port_var.set("LabCapsule")
            self.scan_button.configure(text="连接时扫描")
            return
        self.port_box.configure(state="readonly")
        self.scan_button.configure(text="重新扫描")
        ports = list(list_ports.comports())
        values = [f"{item.device} — {item.description}" for item in ports]
        self.port_box["values"] = values
        preferred = next((value for value in values if value.upper().startswith("COM8 ")), None)
        if preferred or values:
            self.port_var.set(preferred or values[0])

    def on_transport_changed(self, _event=None):
        selected = self.transport_var.get()
        if self.link.connected:
            self.link.close()
        self.transport_mode = selected
        self.link = self._make_link(selected)
        self.refresh_ports()
        if selected == "局域网 WiFi":
            self.network_label.configure(
                text="输入设备 STA 地址；不会加入 LabCapsule 无网络热点")
        elif selected == "蓝牙 BLE":
            self.network_label.configure(text="BLE 不占用 WiFi；大文件建议 USB/局域网")
        else:
            self.network_label.configure(text="USB 最稳定；不会更改电脑联网")

    def toggle_connect(self):
        if self.link.connected:
            self.link.close()
            return
        name = self.port_var.get().strip()
        if self.transport_var.get() == "USB 数据线":
            name = name.split(" — ", 1)[0].strip()
        if not name:
            messagebox.showwarning("缺少连接目标", "请选择串口、输入局域网地址或使用 BLE 扫描。")
            return
        try:
            self.link.connect(name)
        except Exception as error:
            messagebox.showerror("连接失败", str(error))

    def send(self, command: str):
        try:
            self.link.send(command)
            self._append_log(f"> {command}")
        except Exception as error:
            self._append_log(f"! {error}")

    def send_console(self):
        command = self.command_var.get().strip()
        if command:
            self.send(command)
            self.command_var.set("")

    def _append_log(self, line: str):
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log.insert("end", f"[{stamp}] {line}\n")
        self.log.see("end")

    def _pet_append(self, kind: str, text: str):
        if not hasattr(self, "pet_chat"):
            return
        prefix = {"user": "你", "pet": self.pet_settings.profile.name,
                  "claude": "Claude", "event": "系统"}.get(kind, "系统")
        self.pet_chat.configure(state="normal")
        self.pet_chat.insert("end", f"{prefix}  {text}\n",
                             kind if kind in {"user", "pet", "claude", "event"} else "event")
        self.pet_chat.configure(state="disabled")
        self.pet_chat.see("end")

    def _set_pet_state(self, emotion: str, caption: str, action: str = ""):
        self.pet_emotion = emotion
        motion = pet_state_command(emotion, action).rsplit(",", 1)[-1]
        if hasattr(self, "pet_avatar"):
            self.pet_avatar.set_state(emotion, caption)
            self.pet_state_label.configure(text=f"{emotion.upper()} · {caption[:36]}")
        if self.pet_overlay is not None:
            self.pet_overlay.set_state(emotion, caption)
        if self.active_pet_package is not None and self.active_pet_package.visual_kind == "live2d":
            try:
                write_live2d_action(emotion, motion, CONTROL_PATH)
            except OSError as error:
                self._append_log(f"! Live2D 动作同步失败：{error}")

    def show_device_pet(self):
        if not self.link.connected:
            self.pet_device_status.configure(text="设备桌宠：请先连接设备")
            return
        self.device_pet_enabled = True
        self._sync_pet_reply_to_device(self.last_pet_reply)

    def hide_device_pet(self):
        self.device_pet_enabled = False
        self.pending_pet_device_reply = None
        if self.link.connected:
            self.send("PET,HIDE")
        self.pet_device_status.configure(text="设备桌宠：已退出")

    def _sync_pet_reply_to_device(self, reply: PetReply):
        if not self.device_pet_enabled or not self.link.connected or self.device_recording:
            return
        if not self.device_firmware_version:
            self.pending_pet_device_reply = reply
            self.pet_device_status.configure(text="设备桌宠：等待固件握手…")
            return
        if not self.device_firmware_version.startswith(("0.11.", "1.0.")):
            self.pet_device_status.configure(
                text=f"设备桌宠：固件 {self.device_firmware_version} 不支持，请更新 V1")
            return
        if self.pet_device_sync_active:
            self.pending_pet_device_reply = reply
            return
        self.pet_device_sync_active = True
        self.pending_pet_device_reply = None
        self.pet_device_status.configure(text="设备桌宠：正在同步中文气泡…")

        def worker():
            try:
                payload = render_pet_bubble(reply.text)
                self.link.send("DISPLAY,PET")
                self.link.send(pet_state_command(reply.emotion, reply.action))
                self.link.upload("PETBUBBLE", payload,
                                 lambda value: self.events.put(("pet_device_progress", value)))
                self.events.put(("pet_device_done", reply))
            except Exception as error:
                self.events.put(("pet_device_error", str(error)))

        threading.Thread(target=worker, daemon=True, name="pet-device-sync").start()

    def show_pet_overlay(self):
        if self.active_pet_package is not None and self.active_pet_package.visual_kind == "live2d":
            self._launch_live2d_player(self.active_pet_package, "overlay")
            self.pet_overlay_button.configure(text="关闭 Live2D 悬浮舞台")
            return
        if self.pet_overlay is None:
            self.pet_overlay = PetOverlay(self, self.focus_pet_tab)
            if self.avatar_decoded is not None:
                self.pet_overlay.set_custom_avatar(self.avatar_decoded.frames,
                                                   self.avatar_decoded.durations_ms)
        self.pet_overlay.set_state(self.pet_emotion, self.pet_settings.profile.name)
        self.pet_overlay.show()
        self.pet_overlay_button.configure(text="隐藏桌面悬浮宠物")

    def hide_pet_overlay(self):
        if self.active_pet_package is not None and self.active_pet_package.visual_kind == "live2d":
            self._stop_live2d_players("overlay")
            self.pet_overlay_button.configure(text="显示 Live2D 悬浮舞台")
            return
        if self.pet_overlay is not None:
            self.pet_overlay.hide()
        self.pet_overlay_button.configure(text="显示桌面悬浮宠物")

    def toggle_pet_overlay(self):
        if self.active_pet_package is not None and self.active_pet_package.visual_kind == "live2d":
            self._cleanup_live2d_processes()
            if any(mode == "overlay" for mode, _process in self.live2d_processes):
                self.hide_pet_overlay()
            else:
                self.show_pet_overlay()
            return
        if self.pet_overlay is None or self.pet_overlay.window.state() == "withdrawn":
            self.show_pet_overlay()
        else:
            self.hide_pet_overlay()

    def focus_pet_tab(self):
        self.deiconify()
        self.lift()
        self.focus_force()
        self.tabs.select(self.pet)

    def save_pet_settings(self):
        try:
            self.pet_settings = PetSettings(
                endpoint=self.pet_endpoint_var.get().strip(),
                model=self.pet_model_var.get().strip(),
                api_key=self.pet_key_var.get().strip(),
                temperature=self.pet_settings.temperature,
                remember=self.pet_memory_var.get(),
                sync_device=self.pet_sync_var.get(),
                auto_react=self.pet_auto_var.get(),
                delegate_complex=self.pet_delegate_var.get(),
                claude_model=self.pet_claude_model_var.get().strip()[:80] or "sonnet",
                avatar_url=self.avatar_url_var.get().strip(),
                avatar_source_name=self.pet_settings.avatar_source_name,
                memory_sync_enabled=self.memory_sync_var.get(),
                memory_repository=self.memory_repository_var.get().strip(),
                memory_branch=self.memory_branch_var.get().strip() or "main",
                memory_token=self.memory_token_var.get().strip(),
                speech_endpoint=self.speech_endpoint_var.get().strip(),
                speech_model=self.speech_model_var.get().strip(),
                speech_api_key=self.speech_key_var.get().strip(),
                profile=CharacterProfile(
                    name=self.pet_name_var.get().strip()[:24] or "胶囊零号",
                    persona=self.pet_persona.get("1.0", "end").strip()[:2400],
                    greeting=self.pet_settings.profile.greeting,
                ),
            )
            self.pet_settings.save()
            self.pet_runtime.update_settings(self.pet_settings)
            self.claude_bridge = ClaudeBridge(self.pet_settings.claude_model)
            self.claude_state_label.configure(
                text=("Claude：已检测，可受限调用" if self.claude_bridge.available else
                      "Claude：本机未安装，自动使用主 AI"))
            self._pet_append("event", "角色与 AI 设置已保存；API Key 由当前 Windows 用户 DPAPI 加密。")
            self._set_pet_state("success", "SETTINGS SAVED")
            if self.pet_settings.memory_sync_enabled and self.device_id:
                self.sync_memory_now()
        except Exception as error:
            messagebox.showerror("AI 设置保存失败", str(error))

    def clear_pet_memory(self):
        self.pet_runtime.memory.clear()
        self._pet_append("event", "本地桌宠对话和长期偏好已清除。")
        self._set_pet_state("idle", "MEMORY CLEARED")

    def sync_memory_now(self):
        if self.memory_sync_active:
            return
        if not self.device_id:
            self.memory_sync_status.configure(text="记忆同步：请先连接并识别 LabCapsule")
            return
        remote = MemoryRemote(self.memory_repository_var.get().strip(),
                              self.memory_token_var.get().strip(),
                              self.memory_branch_var.get().strip() or "main")
        self.memory_sync_active = True
        self.memory_sync_status.configure(
            text=f"记忆同步：正在校验私有仓库 · {self.device_id}")

        def worker():
            try:
                client = GitHubMemoryClient(remote)
                client.require_private_repository()
                remote_snapshot, sha = client.pull(self.device_id)
                local = empty_snapshot(self.device_id, self.device_character_id)
                local["revision"] = self.memory_revision
                local["facts"] = list(self.pet_runtime.memory.facts)
                local["recentSessions"] = self.experiment_store.recent(self.device_id)
                merged = merge_snapshots(local, remote_snapshot)
                if self.device_character_id:
                    merged["characterId"] = self.device_character_id
                client.push(merged, sha)
                self.events.put(("memory_sync_done", merged))
            except Exception as error:
                self.events.put(("memory_sync_error", str(error)))

        threading.Thread(target=worker, daemon=True, name="memory-sync").start()

    def _role_card_remote(self) -> RoleCardRemote:
        return RoleCardRemote(self.memory_repository_var.get().strip(),
                              self.memory_token_var.get().strip(),
                              self.memory_branch_var.get().strip() or "main")

    def choose_role_preview(self):
        value = filedialog.askopenfilename(
            title="选择角色卡静态预览",
            filetypes=(("图片", "*.png;*.jpg;*.jpeg;*.webp"), ("全部文件", "*.*")))
        if value:
            self.role_preview_path = value
            self.role_card_status.configure(text=f"角色卡预览：{Path(value).name}")

    def choose_role_voice(self):
        value = filedialog.askopenfilename(
            title="选择可选语音包",
            filetypes=(("语音/压缩包", "*.wav;*.mp3;*.ogg;*.zip;*.json"),
                       ("全部文件", "*.*")))
        if value:
            self.role_voice_path = value
            self.role_card_status.configure(text=f"语音包：{Path(value).name}")

    def upload_current_role_card(self):
        package = self.active_pet_package
        if package is None or package.visual_kind != "live2d":
            messagebox.showwarning("无法创建角色卡", "请先在桌宠管理中选择并应用 Live2D 角色。")
            return
        if not self.role_preview_path:
            messagebox.showwarning("缺少静态预览", "请先选择角色卡静态预览图。")
            return
        self.role_card_status.configure(text="角色卡：正在打包并校验 Live2D 依赖…")
        persona = self.pet_persona.get("1.0", "end").strip()
        remote = self._role_card_remote()

        def worker():
            try:
                cache = APP_DIR / "rolecards" / "cache"
                cache.mkdir(parents=True, exist_ok=True)
                bundle = cache / f"{package.package_id}.upload.zip"
                item = build_role_card(package, persona, self.role_preview_path,
                                       self.role_voice_path or None, bundle)
                client = GitHubRoleCardClient(remote)
                catalog = client.publish(
                    bundle, item,
                    lambda value: self.events.put(("role_card_upload_progress", value)))
                final = cache / f"{item['id']}-{item['sha256']}.zip"
                bundle.replace(final)
                self.events.put(("role_card_upload_done", (catalog, final)))
            except Exception as error:
                self.events.put(("role_card_error", str(error)))

        threading.Thread(target=worker, daemon=True, name="role-card-upload").start()

    def sync_role_card_catalog(self):
        self.role_card_status.configure(text="角色卡：正在读取私有仓库索引…")
        remote = self._role_card_remote()

        def worker():
            try:
                client = GitHubRoleCardClient(remote)
                client.require_private_repository()
                catalog, _sha = client.pull_catalog()
                self.events.put(("role_card_catalog_done", catalog))
            except Exception as error:
                self.events.put(("role_card_error", str(error)))

        threading.Thread(target=worker, daemon=True, name="role-card-catalog").start()

    def show_role_card_library(self):
        if self.role_card_window is not None and self.role_card_window.winfo_exists():
            self.role_card_window.deiconify()
            self.role_card_window.lift()
            self.sync_role_card_catalog()
            return
        window = tk.Toplevel(self)
        self.role_card_window = window
        window.title("私有角色卡 · PC / 手机同步")
        window.geometry("920x430")
        window.minsize(720, 380)
        window.configure(bg=self.BG)
        window.transient(self)
        window.protocol("WM_DELETE_WINDOW", lambda: (window.destroy(),
                                                       setattr(self, "role_card_window", None)))
        header = tk.Frame(window, bg=self.BG, padx=18, pady=12)
        header.pack(fill="x")
        tk.Label(header, text="ROLE CARDS / PRIVATE CACHE", bg=self.BG, fg=self.INK,
                 font=("Bahnschrift", 17, "bold")).pack(side="left")
        self.role_replace_visual_var = tk.BooleanVar(value=True)
        self.role_replace_persona_var = tk.BooleanVar(value=True)
        self.role_replace_voice_var = tk.BooleanVar(value=True)
        for text, variable in (("形象", self.role_replace_visual_var),
                               ("人设", self.role_replace_persona_var),
                               ("语音包", self.role_replace_voice_var)):
            ttk.Checkbutton(header, text=text, variable=variable).pack(side="right", padx=5)
        ttk.Button(header, text="刷新", command=self.sync_role_card_catalog).pack(side="right", padx=8)
        shell = tk.Frame(window, bg=self.BG)
        shell.pack(fill="both", expand=True, padx=18, pady=(0, 16))
        self.role_card_canvas = tk.Canvas(shell, bg=self.BG, height=300,
                                          highlightthickness=0)
        scrollbar = ttk.Scrollbar(shell, orient="horizontal",
                                  command=self.role_card_canvas.xview)
        self.role_card_canvas.configure(xscrollcommand=scrollbar.set)
        self.role_card_canvas.pack(fill="both", expand=True)
        scrollbar.pack(fill="x")
        self.role_card_strip = tk.Frame(self.role_card_canvas, bg=self.BG)
        self.role_card_canvas.create_window((0, 0), window=self.role_card_strip, anchor="nw")
        self.role_card_strip.bind("<Configure>", lambda _event:
                                  self.role_card_canvas.configure(
                                      scrollregion=self.role_card_canvas.bbox("all")))
        self._render_role_card_library()
        self.sync_role_card_catalog()

    def _render_role_card_library(self):
        if self.role_card_window is None or not self.role_card_window.winfo_exists():
            return
        for child in self.role_card_strip.winfo_children():
            child.destroy()
        self.role_card_photos.clear()
        cards = self.role_card_catalog.get("cards", [])
        if not cards:
            tk.Label(self.role_card_strip, text="私有仓库中暂无角色卡，或索引尚未刷新。",
                     bg=self.BG, fg=self.MUTED, padx=30, pady=100).pack(side="left")
            return
        for item in cards[:30]:
            frame = tk.Frame(self.role_card_strip, bg=self.PANEL, width=190, height=285,
                             padx=10, pady=10, highlightthickness=1,
                             highlightbackground=self.PANEL_2)
            frame.pack(side="left", padx=(0, 10), fill="y")
            frame.pack_propagate(False)
            try:
                raw = base64.b64decode(item.get("previewBase64", ""), validate=True)
                with Image.open(io.BytesIO(raw)) as source:
                    image = source.convert("RGB")
                    image.thumbnail((170, 190), Image.Resampling.LANCZOS)
                photo = ImageTk.PhotoImage(image)
                self.role_card_photos.append(photo)
                tk.Label(frame, image=photo, bg=self.PANEL).pack()
            except Exception:
                tk.Label(frame, text="NO PREVIEW", bg=self.PANEL_2, fg=self.MUTED,
                         width=20, height=10).pack()
            tk.Label(frame, text=str(item.get("name", "未命名角色"))[:28], bg=self.PANEL,
                     fg=self.INK, font=("Microsoft YaHei UI", 10, "bold")).pack(pady=(7, 2))
            cached = APP_DIR / "rolecards" / "cache" / \
                     f"{item.get('id')}-{item.get('sha256')}.zip"
            state = "已缓存，可离线切换" if cached.is_file() else \
                    f"按需下载 · {int(item.get('size', 0)) // 1024} KiB"
            tk.Label(frame, text=state, bg=self.PANEL, fg=self.MUTED,
                     font=("Microsoft YaHei UI", 8)).pack()
            ttk.Button(frame, text="按勾选项应用",
                       command=lambda value=dict(item): self.download_role_card(value)).pack(
                           fill="x", side="bottom")

    def download_role_card(self, item: dict):
        visual = self.role_replace_visual_var.get()
        persona = self.role_replace_persona_var.get()
        voice = self.role_replace_voice_var.get()
        if not any((visual, persona, voice)):
            messagebox.showwarning("没有替换项", "请至少勾选形象、人设或语音包之一。")
            return
        self.role_card_status.configure(text=f"角色卡：正在准备 {item.get('name', '')}…")
        remote = self._role_card_remote()

        def worker():
            try:
                cache = APP_DIR / "rolecards" / "cache"
                digest = str(item["sha256"])
                bundle = cache / f"{item['id']}-{digest}.zip"
                valid_cache = False
                if bundle.is_file():
                    digest_state = hashlib.sha256()
                    with bundle.open("rb") as stream:
                        for chunk in iter(lambda: stream.read(64 * 1024), b""):
                            digest_state.update(chunk)
                    current = digest_state.hexdigest()
                    valid_cache = current == digest
                if not valid_cache:
                    client = GitHubRoleCardClient(remote)
                    client.download(item, bundle,
                                    lambda value: self.events.put(("role_card_download_progress", value)))
                destination = APP_DIR / "pets" / "synced" / str(item["id"])
                manifest = apply_role_card(bundle, destination, True, True, True)
                package = load_pet_package(destination)
                self.events.put(("role_card_apply_done",
                                 (package, manifest, visual, persona, voice)))
            except Exception as error:
                self.events.put(("role_card_error", str(error)))

        threading.Thread(target=worker, daemon=True, name="role-card-download").start()

    def _apply_synced_role_card(self, package: PetPackage, manifest: dict,
                                visual: bool, persona: bool, voice: bool):
        previous_profile = self.pet_settings.profile
        if visual:
            if not persona:
                self.role_profile_override = previous_profile
            self._apply_live2d_package(package)
        elif persona:
            self._apply_pet_package_profile(package)
        if voice:
            voice_entry = str(manifest.get("voiceFile", ""))
            selection = {"roleId": manifest.get("id", ""), "voiceFile": voice_entry,
                         "voicePath": str((Path(package.folder) /
                                           voice_entry.replace("voice/", "", 1)).resolve())
                         if voice_entry.startswith("voice/") else "",
                         "updatedAt": datetime.now().astimezone().isoformat()}
            target = APP_DIR / "role_voice_selection.json"
            target.write_text(json.dumps(selection, ensure_ascii=False, indent=2), encoding="utf-8")
        self.pet_settings.save()
        self.role_card_status.configure(
            text=f"角色卡：已应用 {manifest.get('name', package.name)} · 本地缓存可离线使用")
        self._render_role_card_library()

    def _mobile_bridge_context(self) -> dict:
        """Snapshot only plain fields; safe to call from the HTTP worker thread."""
        return {
            "studioVersion": APP_VERSION,
            "computer": dict(self.host_snapshot),
            "labcapsule": {
                "connected": bool(self.link.connected),
                "transport": str(getattr(self.link, "kind", "usb")),
                "state": self.device_state,
                "recording": self.device_recording,
                "configuredRateHz": self.device_rate,
                "configuredDurationSeconds": self.device_duration,
                "firmwareVersion": self.device_firmware_version,
                "deviceId": self.device_id,
                "deviceAlias": self.device_alias,
                "characterId": self.device_character_id,
                "staConnected": self.device_sta_connected,
                "staIp": self.device_sta_ip,
                "sampleCount": len(self.samples),
                "latestSample": self.last_sample,
            },
            "permissions": ["computer.status", "labcapsule.context", "claude.delegate"],
        }

    def _mobile_bridge_ask(self, question: str) -> dict:
        result = self.claude_bridge.process(question, self._mobile_bridge_context())
        if not result.ok:
            raise RuntimeError(result.error or "电脑端 Claude 没有返回回答")
        return {"reply": result.text, "elapsedSeconds": round(result.elapsed_s, 2),
                "model": self.claude_bridge.model}

    def toggle_mobile_bridge(self):
        if self.mobile_bridge is not None:
            self.mobile_bridge.stop()
            self.mobile_bridge = None
            self.mobile_bridge_status.configure(
                text="手机桥：已关闭；现有授权不会被网络端使用。")
            self.mobile_bridge_button.configure(text="开启手机桥并生成配对码")
            return
        try:
            server = MobileBridgeServer(APP_DIR / "mobile_bridge_authorized.json",
                                        self._mobile_bridge_context, self._mobile_bridge_ask)
            info = server.start()
            self.mobile_bridge = server
            self.mobile_bridge_status.configure(
                text=f"手机桥：已开启\n地址 {info.url}\n一次性配对码 {info.pairing_code}"
                     "（10 分钟有效）\n首次开启可能出现 Windows 防火墙局域网提示。")
            self.mobile_bridge_button.configure(text="关闭手机桥")
            self._pet_append("event", "手机桥已开启；只有输入当前配对码的手机可读取允许列表中的状态。")
        except Exception as error:
            messagebox.showerror("手机桥开启失败", str(error))

    def _device_context(self) -> dict:
        return {
            "connected": self.link.connected,
            "transport": getattr(self.link, "kind", "usb"),
            "port": self.link.port.port if self.link.connected and self.link.port else "",
            "state": self.device_state,
            "recording": self.device_recording,
            "configured_rate_hz": self.device_rate,
            "configured_duration_s": self.device_duration,
            "firmware_version": self.device_firmware_version,
            "device_id": self.device_id,
            "device_alias": self.device_alias,
            "character_id": self.device_character_id,
            "character_proxy": self.device_pet_proxy,
            "memory_revision": self.memory_revision,
            "network": {"staConnected": self.device_sta_connected,
                        "staIp": self.device_sta_ip},
            "samples": len(self.samples),
            "latest_sample": self.last_sample,
            "motion_summary": self.motion_chart.summary(),
            "chart_channels": [name for name, variable in self.motion_chart.channel_vars.items()
                               if variable.get()],
            "chart_window": self.motion_chart.window_var.get(),
            "computer": dict(self.host_snapshot),
            "experiment": {
                "status": self.device_state,
                "recording": self.device_recording,
                "received_samples": len(self.samples),
                "summary": self.motion_chart.summary(),
            },
        }

    def send_pet_message(self, preset: str | None = None):
        text = (preset if preset is not None else self.pet_input.get()).strip()
        if not text:
            return
        self.pet_input.set("")
        self._pet_append("user", text)
        self._set_pet_state("thinking", "THINKING")
        context = self._device_context()
        def worker():
            reply = self.pet_runtime.chat(text, context)
            should_delegate = (self.pet_settings.delegate_complex and
                               self.claude_bridge.should_delegate(
                                   text, reply.delegate_to_claude))
            if should_delegate:
                self.events.put(("claude_started", None))
                task = reply.delegate_prompt or text
                result = self.claude_bridge.process(task, context, reply.text)
                if result.ok:
                    reply = PetReply(result.text, "speaking", True, source="claude",
                                     action="TALK")
                    self.pet_runtime.memory.append("assistant", result.text)
                    self.events.put(("claude_finished", result.elapsed_s))
                else:
                    reply.text += f"\n（Claude 转交未完成：{result.error}）"
                    self.events.put(("claude_error", result.error))
            self.events.put(("pet_reply", reply))
        threading.Thread(target=worker, daemon=True, name="pet-agent").start()

    def record_pet_voice(self):
        if self.mic_button.instate(["disabled"]):
            return
        endpoint = self.speech_endpoint_var.get().strip()
        model = self.speech_model_var.get().strip()
        api_key = self.speech_key_var.get().strip()
        if not api_key:
            messagebox.showwarning(
                "未配置语音转写",
                "请在右侧填写语音 Endpoint、模型和 API Key。语音密钥与对话密钥可不同。")
            return
        self.mic_button.state(["disabled"])
        self.speech_status.configure(text="麦克风：正在录音 6 秒…")
        self._set_pet_state("curious", "LISTENING", "TILT")

        def worker():
            try:
                wav = record_wav(6.0)
                self.events.put(("speech_uploading", len(wav)))
                text = transcribe_wav(wav, endpoint, model, api_key, "zh")
                self.events.put(("speech_done", text))
            except Exception as error:
                self.events.put(("speech_error", str(error)))

        threading.Thread(target=worker, daemon=True, name="pet-microphone").start()

    @staticmethod
    def _ascii_device_notice(reply: PetReply) -> str:
        ascii_text = " ".join(re.findall(r"[A-Za-z0-9][A-Za-z0-9 .:\-]{1,}", reply.text))[:30]
        if len(ascii_text.strip()) >= 3:
            return ascii_text.strip()
        return {
            "happy": "PET HAPPY", "curious": "PET CURIOUS", "thinking": "PET THINKING",
            "speaking": "PET MESSAGE", "experiment": "WATCHING EXPERIMENT",
            "success": "EXPERIMENT COMPLETE", "warning": "CHECK DEVICE LOG",
            "sleeping": "PET SLEEPING", "idle": "PET ONLINE",
        }.get(reply.emotion, "PET ONLINE")

    def _handle_pet_reply(self, reply: PetReply):
        self.last_pet_reply = reply
        self._pet_append("claude" if reply.source == "claude" else "pet", reply.text)
        self._set_pet_state(reply.emotion, reply.text, reply.action)
        if (self.pet_settings.sync_device and self.device_pet_enabled and self.link.connected
                and not self.device_recording):
            self._sync_pet_reply_to_device(reply)
        self.after(4500, lambda: self._set_pet_state("idle", "LINK READY")
                   if self.pet_emotion == reply.emotion else None)

    def _pet_event(self, event: str, detail: str = ""):
        if not self.pet_settings.auto_react:
            return
        reply = self.pet_runtime.react_event(event, detail)
        if reply:
            self.last_pet_reply = reply
            self._pet_append("event", reply.text)
            self._set_pet_state(reply.emotion, event.replace("_", " ").upper(), reply.action)
            if (reply.device_notice and self.pet_settings.sync_device and self.device_pet_enabled
                    and self.link.connected
                    and not self.device_recording):
                self._sync_pet_reply_to_device(reply)

    def _accept_device_identity(self, device_id: str) -> None:
        if not re.fullmatch(r"lc-[0-9a-f]{12}", device_id):
            self._append_log(f"! 忽略无效设备 ID：{device_id[:40]}")
            return
        changed = device_id != self.device_id
        self.device_id = device_id
        try:
            self.pet_runtime.memory.bind_device(device_id)
        except Exception as error:
            self._append_log(f"! 设备记忆分区失败：{error}")
        port = self.link.port.port if self.link.connected and self.link.port else "设备"
        self.connection_label.configure(text=f"● {port} · {device_id}", fg=self.CYAN)
        if changed:
            self._pet_append("event", f"已识别硬件 {device_id}；已切换到该设备的独立记忆分区。")
        if (self.pet_settings.memory_sync_enabled and
                self.memory_synced_device != device_id and not self.memory_sync_active):
            self.sync_memory_now()

    def _apply_transport_status(self, payload: dict) -> None:
        device = payload.get("device", payload)
        network = payload.get("network", {})
        if not isinstance(device, dict):
            return
        version = str(device.get("version", ""))[:40]
        if version:
            self.device_firmware_version = version
        device_id = str(device.get("deviceId", ""))
        if device_id:
            self._accept_device_identity(device_id)
        self.device_state = str(device.get("state", self.device_state)).upper()
        self.device_recording = self.device_state == "RECORDING"
        try:
            self.device_rate = int(device.get("rate", self.device_rate))
            self.device_duration = int(device.get("duration", self.device_duration))
        except (TypeError, ValueError):
            pass
        pet = device.get("pet", {})
        if isinstance(pet, dict):
            self.device_character_id = str(
                pet.get("characterId", self.device_character_id))[:64]
            self.device_pet_proxy = bool(pet.get("proxy", self.device_pet_proxy))
        else:
            self.device_character_id = str(
                device.get("characterId", self.device_character_id))[:64]
            self.device_pet_proxy = bool(device.get("petProxy", self.device_pet_proxy))
        if isinstance(network, dict):
            self.device_sta_connected = bool(network.get("staConnected", False))
            self.device_sta_ip = str(network.get("staIp", "0.0.0.0"))[:48]
            self.network_label.configure(
                text=(f"外部 WiFi：已连接 · {self.device_sta_ip}" if self.device_sta_connected
                      else "外部 WiFi：未连接 · ESP32-S3 仅支持 2.4 GHz"),
                fg=self.CYAN if self.device_sta_connected else self.YELLOW)
        if hasattr(self, "pet_device_status") and self.device_firmware_version:
            self.pet_device_status.configure(
                text=f"设备桌宠：{self.device_firmware_version} · "
                     f"{self.device_character_id or '未设置角色'}")

    def _handle_line(self, line: str):
        self._append_log(line)
        if line.startswith("TRANSPORT_JSON,"):
            try:
                self._apply_transport_status(json.loads(line.split(",", 1)[1]))
            except (json.JSONDecodeError, TypeError, ValueError) as error:
                self._append_log(f"! 设备状态 JSON 无效：{error}")
        elif line.startswith("NETWORK,"):
            try:
                network = json.loads(line.split(",", 1)[1])
                self._apply_transport_status({"device": {}, "network": network})
            except (json.JSONDecodeError, TypeError, ValueError) as error:
                self._append_log(f"! 网络状态 JSON 无效：{error}")
        elif line.startswith("PONG,LABCAPSULE,"):
            fields = line.split(",")
            self.device_firmware_version = fields[2].strip() if len(fields) > 2 else ""
            values = parse_key_value_fields(fields[3:])
            if values.get("DEVICE"):
                self._accept_device_identity(values["DEVICE"])
            if self.device_firmware_version.startswith(("0.11.", "1.0.")):
                self.pet_device_status.configure(
                    text=f"设备桌宠：{self.device_firmware_version} 协议就绪")
                pending = self.pending_pet_device_reply or self.last_pet_reply
                self.pending_pet_device_reply = None
                if self.device_pet_enabled and self.pet_settings.sync_device:
                    self._sync_pet_reply_to_device(pending)
            else:
                self.pet_device_status.configure(
                    text=f"设备桌宠：需更新固件（当前 {self.device_firmware_version}）")
        elif line.startswith("IDENTITY,"):
            values = parse_key_value_fields(line.split(",")[1:])
            if values.get("DEVICE"):
                self._accept_device_identity(values["DEVICE"])
            self.device_alias = values.get("ALIAS", self.device_alias)
            self.device_character_id = values.get("CHARACTER", self.device_character_id)
            self.device_pet_proxy = values.get("PROXY", "OFF").upper() == "ON"
            if hasattr(self, "memory_sync_status") and not self.pet_settings.memory_sync_enabled:
                self.memory_sync_status.configure(
                    text=f"记忆同步：{self.device_id or '设备已识别'} · 未启用远程同步")
        elif line.startswith("PET,VIEW="):
            values = parse_key_value_fields(line.split(",")[1:])
            self.device_character_id = values.get("CHARACTER", self.device_character_id)
            self.device_pet_proxy = values.get("PROXY", "OFF").upper() == "ON"
        elif line.startswith("OK,PET,IDENTITY,"):
            fields = line.split(",")
            if len(fields) >= 5:
                self.device_character_id = fields[3].strip()[:64]
                self.device_pet_proxy = fields[4].strip().upper() == "PROXY"
        elif line.startswith("STATUS,"):
            fields = line.split(",")
            if len(fields) > 1:
                self.device_state = fields[1]
            values = parse_key_value_fields(fields[2:])
            try:
                self.device_rate = int(values.get("RATE", self.device_rate))
                self.device_duration = int(values.get("DURATION", self.device_duration))
            except ValueError:
                pass
        elif line.startswith("OK,START"):
            if self.device_state != "RECORDING":
                self.samples.clear()
                self.motion_chart.clear()
            self.experiment_started_at = datetime.now().astimezone().isoformat(
                timespec="seconds")
            self.experiment_session_saved = False
            self.device_state = "RECORDING"
            self.device_recording = True
            self._pet_event("experiment_start")
        elif line.startswith("OK,COMPLETE") or line.startswith("OK,STOP"):
            self.device_state = "COMPLETE"
            self.device_recording = False
            self._finalize_experiment_session(False)
            self._pet_event("experiment_complete")
        elif line.startswith("OK,ABORT"):
            self.device_state = "ABORTED"
            self.device_recording = False
            self._finalize_experiment_session(True)
            self._pet_event("experiment_abort")
        elif (line.startswith("ERR,") and not line.startswith("ERR,UPLOAD,PETBUBBLE")
              and time.monotonic() - self.last_pet_error_at > 8):
            self.last_pet_error_at = time.monotonic()
            self._pet_event("device_error", line[:100])
        if line == "PET,INPUT,TALK":
            self.focus_pet_tab()
            self.send_pet_message("请简要介绍当前电脑、设备和实验状态")
        elif line == "PET,INPUT,NEXT_ACTION":
            self._set_pet_state("happy", "HELLO", "BOUNCE")
        if (line.startswith("STATUS,") or line.startswith("PONG,") or
                line.startswith("GIF,") or line.startswith("PET,") or
                line.startswith("NETWORK,") or line.startswith("TRANSPORT_JSON,")):
            self.device_status.insert("end", line + "\n")
            self.device_status.see("end")
        if line.startswith("DATA,"):
            parsed = parse_motion_data_line(line)
            if parsed is not None:
                fields, timestamp_us, values = parsed
                self.samples.append(fields)
                self.last_sample = tuple(fields)
                self.motion_chart.add_sample(timestamp_us, values)
                self.latest_sample.configure(text="  ".join(
                    name + "=" + value for name, value in zip(
                        ("t", "AX", "AY", "AZ", "GX", "GY", "GZ"), fields
                    )
                ))
                self.sample_label.configure(text=f"样本 {len(self.samples):,}")

    def _heartbeat(self):
        cpu = round(psutil.cpu_percent())
        memory = psutil.virtual_memory()
        disk_usage = psutil.disk_usage(Path.home().anchor or "C:\\")
        ram = round(memory.percent)
        disk = round(disk_usage.percent)
        temperature = -1
        try:
            readings = psutil.sensors_temperatures()
            values = [item.current for group in readings.values() for item in group if item.current]
            if values:
                temperature = round(values[0])
        except Exception:
            pass
        battery = None
        try:
            battery = psutil.sensors_battery()
        except Exception:
            pass
        self.host_snapshot = {
            "os": f"{platform.system()} {platform.release()}",
            "cpu_percent": cpu,
            "logical_cpus": psutil.cpu_count(logical=True) or 0,
            "memory_percent": ram,
            "memory_used_gb": round(memory.used / (1024 ** 3), 2),
            "memory_total_gb": round(memory.total / (1024 ** 3), 2),
            "disk_percent": disk,
            "disk_free_gb": round(disk_usage.free / (1024 ** 3), 2),
            "temperature_c": temperature if temperature >= 0 else None,
            "battery_percent": round(battery.percent) if battery else None,
            "power_plugged": bool(battery.power_plugged) if battery else None,
            "uptime_seconds": max(0, round(time.time() - psutil.boot_time())),
            "captured_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        for key, value in (("cpu", cpu), ("ram", ram), ("disk", disk)):
            self.metric_labels[key].configure(text=f"{value}%")
        if self.link.connected:
            now = time.monotonic()
            if (not self.device_firmware_version and
                    now - self.last_handshake_at >= 2.0):
                self.last_handshake_at = now
                self.send("PING")
                self.send("STATUS")
                self.send("IDENTITY")
            self.send(f"HOST,{cpu},{ram},{disk},{temperature}")
            if self.notification_enabled and now - self.last_notification_poll >= 5:
                self.last_notification_poll = now
                threading.Thread(target=self._poll_notifications, daemon=True).start()
        self.after(2000, self._heartbeat)

    def enable_notifications(self):
        self.notice_state.configure(text="正在请求 Windows 权限…")
        def worker():
            enabled = self.notification_bridge.enable()
            self.events.put(("notice", enabled))
        threading.Thread(target=worker, daemon=True).start()

    def _poll_notifications(self):
        for title, body in self.notification_bridge.poll():
            self.events.put(("system_notice", (title, body)))

    def _notice_command(self, title: str, body: str):
        clean = lambda value: value.replace(",", " ").replace("\r", " ").replace("\n", " ")[:32]
        self.send(f"NOTICE,{clean(title)},{clean(body)}")
        self.send("MODE,IDLE")

    def send_manual_notice(self):
        self._notice_command(self.notice_title.get(), self.notice_body.get())

    def choose_media(self):
        path = filedialog.askopenfilename(title="选择图片、GIF 或视频", filetypes=[
            ("媒体", "*.png *.jpg *.jpeg *.webp *.bmp *.gif *.mp4 *.avi *.mov *.mkv *.webm"),
            ("全部", "*.*"),
        ])
        if path:
            self.media_path = path
            self.media_label.configure(text=Path(path).name)
            self.preview_media()

    def choose_pet(self):
        path = filedialog.askopenfilename(title="选择透明 PNG/GIF 桌宠",
                                          filetypes=[("桌宠", "*.png *.webp *.gif"), ("全部", "*.*")])
        if path:
            self.pet_path = path
            self.media_label.configure(text=f"{Path(self.media_path).name or '空背景'} + {Path(path).name}")
            self.preview_media()

    def clear_pet(self):
        self.pet_path = ""
        self.preview_media()

    def preview_media(self):
        if not self.media_path:
            return
        try:
            frames, _ = load_frames(self.media_path, int(self.fps_var.get()))
            pet = None
            if self.pet_path:
                pet_frames, _ = load_frames(self.pet_path, int(self.fps_var.get()))
                pet = pet_frames[0]
            frame = compose_frame(frames[0], self.fit_var.get(), self.bg_var.get(),
                                  float(self.zoom_var.get()), int(self.pan_x_var.get()),
                                  int(self.pan_y_var.get()), pet, int(self.pet_x_var.get()),
                                  int(self.pet_y_var.get()), float(self.pet_scale_var.get()))
            self.preview_photo = ImageTk.PhotoImage(frame)
            self.preview.delete("all")
            self.preview.create_image(0, 0, anchor="nw", image=self.preview_photo)
        except Exception as error:
            self.media_state.configure(text=f"预览失败：{error}")

    def process_upload(self):
        if not self.media_path:
            messagebox.showwarning("缺少媒体", "请先选择主媒体。")
            return
        if not self.link.connected:
            messagebox.showwarning("未连接", "请先通过 USB、局域网或 BLE 连接设备。")
            return
        self.media_state.configure(text="电脑端裁剪、解码与压缩中…")
        self.media_progress["value"] = 0
        settings = dict(path=self.media_path, fps=int(self.fps_var.get()), mode=self.fit_var.get(),
                        background=self.bg_var.get(), zoom=float(self.zoom_var.get()),
                        pan_x=int(self.pan_x_var.get()), pan_y=int(self.pan_y_var.get()),
                        pet_path=self.pet_path or None, pet_x=int(self.pet_x_var.get()),
                        pet_y=int(self.pet_y_var.get()), pet_scale=float(self.pet_scale_var.get()))
        def worker():
            try:
                result = build_media(**settings,
                    progress=lambda value: self.events.put(("progress", value)))
                kind = "WALLPAPER" if result.frames == 1 and not self.pet_path else "CLIP"
                self.events.put(("media_state", f"已压缩 {len(result.payload):,} B，通过当前链路写入设备…"))
                self.link.upload(kind, result.payload,
                                 lambda value: self.events.put(("progress", value)))
                self.events.put(("media_done", (result, kind)))
            except Exception as error:
                self.events.put(("media_error", str(error)))
        threading.Thread(target=worker, daemon=True, name="media-upload").start()

    def apply_style(self):
        self.send(f"STYLE,{self.style_preset.get()},{self.wall_opacity.get()},"
                  f"{self.panel_opacity.get()},{self.hud_opacity.get()}")

    def set_mock(self):
        self.send("MOCK," + ("ON" if self.mock_var.get() else "OFF"))

    def start_experiment(self):
        self.samples.clear()
        self.motion_chart.clear()
        self.experiment_started_at = datetime.now().astimezone().isoformat(timespec="seconds")
        self.experiment_session_saved = False
        try:
            self.device_rate = int(self.rate_var.get())
            self.device_duration = int(self.duration_var.get())
        except ValueError:
            pass
        self.send("MODE,EXPERIMENT")
        self.send(f"START,{self.rate_var.get()},{self.duration_var.get()}")

    def export_csv(self):
        if not self.samples:
            messagebox.showinfo("暂无数据", "开始实验并收到 DATA 后再导出。")
            return
        path = filedialog.asksaveasfilename(defaultextension=".csv",
                                            initialfile=f"labcapsule-{datetime.now():%Y%m%d-%H%M%S}.csv")
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle)
            writer.writerow(("timestamp_us", "ax_g", "ay_g", "az_g", "gx_dps", "gy_dps", "gz_dps"))
            writer.writerows(self.samples)
        messagebox.showinfo("导出完成", path)

    def _finalize_experiment_session(self, aborted: bool):
        if self.experiment_session_saved or not self.samples or not self.device_id:
            return
        self.experiment_session_saved = True
        samples = [list(row) for row in self.samples]
        summary = self.motion_chart.summary()
        device_id = self.device_id
        started_at = self.experiment_started_at
        rate = self.device_rate
        duration = self.device_duration

        def worker():
            try:
                session = self.experiment_store.save(
                    device_id, samples, rate, duration, started_at, aborted, summary)
                self.events.put(("session_saved", session))
            except Exception as error:
                self.events.put(("session_save_error", str(error)))

        threading.Thread(target=worker, daemon=True, name="experiment-save").start()

    def _pump(self):
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "line":
                    self._handle_line(str(payload))
                elif kind == "state":
                    state, port = payload
                    self.connection_label.configure(text=f"● {port if state else '未连接'}",
                                                    fg=self.CYAN if state else self.RED)
                    self.connect_button.configure(text="断开" if state else "连接")
                    if state:
                        self.device_firmware_version = ""
                        self.device_id = ""
                        self.device_alias = ""
                        self.device_character_id = ""
                        self.device_pet_proxy = False
                        self.device_sta_connected = False
                        self.device_sta_ip = "0.0.0.0"
                        self.memory_synced_device = ""
                        self.last_handshake_at = 0.0
                        self.pet_device_status.configure(text="设备桌宠：正在握手…")
                    else:
                        self.device_firmware_version = ""
                        self.device_id = ""
                        self.device_alias = ""
                        self.device_character_id = ""
                        self.device_pet_proxy = False
                        self.device_sta_connected = False
                        self.device_sta_ip = "0.0.0.0"
                        self.memory_synced_device = ""
                        self.device_pet_enabled = False
                        self.pet_device_sync_active = False
                        self.pending_pet_device_reply = None
                        self.pet_device_status.configure(text="设备桌宠：等待连接")
                    self._pet_event("connected" if state else "disconnected")
                elif kind == "progress":
                    self.media_progress["value"] = int(payload)
                elif kind == "media_state":
                    self.media_state.configure(text=str(payload))
                elif kind == "media_done":
                    result, upload_kind = payload
                    self.media_state.configure(text=f"完成：{result.source_kind} / {result.frames} 帧 / "
                                                    f"{result.fps:g} FPS / {upload_kind}；可脱离电脑播放")
                elif kind == "media_error":
                    self.media_state.configure(text=f"失败：{payload}")
                    messagebox.showerror("媒体处理/上传失败", str(payload))
                elif kind == "session_saved":
                    session = payload
                    self._pet_append(
                        "event", f"实验已自动保存：{session['sampleCount']} 个样本 · "
                                 f"{session['id']}")
                    if self.pet_settings.memory_sync_enabled:
                        self.memory_synced_device = ""
                        self.sync_memory_now()
                elif kind == "session_save_error":
                    self._append_log(f"! 实验自动保存失败：{payload}")
                elif kind == "live2d_proxy_done":
                    self.avatar_download_active = False
                    package, result, path = payload
                    self._set_avatar_status(
                        f"同一角色已同步：{result.frames} 帧 / {result.fps:g} FPS / "
                        f"{len(result.payload) / 1024:.1f} KiB", 100)
                    self.pet_device_status.configure(
                        text=f"设备桌宠：{package.name} 代理已持久化，可脱离电脑播放")
                    self._pet_append("event", f"{package.name} 的同源 Live2D 代理已写入设备：{path}")
                elif kind == "live2d_proxy_error":
                    self.avatar_download_active = False
                    self._set_avatar_status(f"Live2D 设备代理失败：{payload}", 0)
                    messagebox.showerror("Live2D 设备同步失败", str(payload))
                elif kind == "notice":
                    self.notification_enabled = bool(payload)
                    self.notice_state.configure(text="系统通知镜像已启用" if payload else
                                                "未获授权或缺少 winsdk；可继续手动发送")
                elif kind == "system_notice":
                    title, body = payload
                    self._notice_command(title, body)
                elif kind == "pet_reply":
                    self._handle_pet_reply(payload)
                elif kind == "claude_started":
                    self.claude_state_label.configure(text="Claude：正在受限处理复杂任务…")
                    self._set_pet_state("thinking", "CLAUDE WORKING", "THINK")
                elif kind == "claude_finished":
                    self.claude_state_label.configure(
                        text=f"Claude：处理完成 · {float(payload):.1f} 秒 · 无工具权限")
                elif kind == "claude_error":
                    self.claude_state_label.configure(text=f"Claude：转交失败 · {str(payload)[:70]}")
                elif kind == "speech_uploading":
                    self.speech_status.configure(
                        text=f"麦克风：录音完成 {int(payload) / 1024:.0f} KiB，电脑正在转写…")
                    self._set_pet_state("thinking", "TRANSCRIBING", "THINK")
                elif kind == "speech_done":
                    self.mic_button.state(["!disabled"])
                    self.speech_status.configure(text=f"麦克风：识别为“{str(payload)[:48]}”")
                    self.send_pet_message(str(payload))
                elif kind == "speech_error":
                    self.mic_button.state(["!disabled"])
                    self.speech_status.configure(text=f"麦克风：失败 · {str(payload)[:100]}")
                    self._set_pet_state("warning", "VOICE ERROR", "ALERT")
                elif kind == "memory_sync_done":
                    self.memory_sync_active = False
                    snapshot = payload
                    self.memory_revision = int(snapshot.get("revision", 0))
                    self.memory_synced_device = self.device_id
                    self.pet_runtime.memory.merge_facts(list(snapshot.get("facts", [])))
                    remote_character = str(snapshot.get("characterId", ""))
                    if remote_character and not self.device_character_id:
                        self.device_character_id = remote_character
                    self.memory_sync_status.configure(
                        text=f"记忆同步：完成 · {self.device_id} · r{self.memory_revision} · "
                             f"{len(snapshot.get('facts', []))} 条长期记忆")
                    self._pet_append("event", "私有记忆已按硬件 ID 合并；API/Wi-Fi 密钥未上传。")
                elif kind == "memory_sync_error":
                    self.memory_sync_active = False
                    self.memory_sync_status.configure(
                        text=f"记忆同步：失败 · {str(payload)[:110]}")
                    self._append_log(f"! 私有记忆同步失败：{payload}")
                elif kind == "role_card_upload_progress":
                    self.role_card_status.configure(text=f"角色卡：正在上传 {int(payload)}%")
                elif kind == "role_card_download_progress":
                    self.role_card_status.configure(text=f"角色卡：正在下载 {int(payload)}%")
                elif kind == "role_card_upload_done":
                    catalog, cached = payload
                    self.role_card_catalog = catalog
                    self.role_card_status.configure(
                        text=f"角色卡：已上传并缓存 · {Path(cached).stat().st_size // 1024} KiB")
                    self._render_role_card_library()
                elif kind == "role_card_catalog_done":
                    self.role_card_catalog = payload
                    self.role_card_status.configure(
                        text=f"角色卡：已同步 {len(payload.get('cards', []))} 个 · 完整包按需下载")
                    self._render_role_card_library()
                elif kind == "role_card_apply_done":
                    package, manifest, visual, persona, voice = payload
                    self._apply_synced_role_card(package, manifest, visual, persona, voice)
                elif kind == "role_card_error":
                    self.role_card_status.configure(text=f"角色卡失败：{str(payload)[:120]}")
                    messagebox.showerror("角色卡操作失败", str(payload))
                elif kind == "pet_device_progress":
                    self.pet_device_status.configure(text=f"设备桌宠：同步 {int(payload)}%")
                elif kind == "pet_device_done":
                    self.pet_device_sync_active = False
                    self.pet_device_status.configure(
                        text=f"设备桌宠：已显示 · {payload.emotion.upper()} / 中文气泡")
                    if not self.device_pet_enabled and self.link.connected:
                        self.send("PET,HIDE")
                        continue
                    pending = self.pending_pet_device_reply
                    self.pending_pet_device_reply = None
                    if pending is not None:
                        self._sync_pet_reply_to_device(pending)
                elif kind == "pet_device_error":
                    self.pet_device_sync_active = False
                    self.pet_device_status.configure(text=f"设备桌宠：同步失败 · {str(payload)[:80]}")
                    if not self.device_pet_enabled:
                        continue
                    pending = self.pending_pet_device_reply
                    self.pending_pet_device_reply = None
                    if pending is not None:
                        self._sync_pet_reply_to_device(pending)
                elif kind == "avatar_progress":
                    self._set_avatar_status("正在下载并验证网络形象…", int(payload))
                elif kind == "avatar_done":
                    self.avatar_download_active = False
                    decoded, source_name = payload
                    self._stop_live2d_players()
                    self.active_pet_package = None
                    clear_selected_pet()
                    self._apply_avatar_decoded(decoded, str(source_name))
                    self._pet_append("event", "网络形象已通过格式、尺寸和哈希校验，并保存为当前单份缓存。")
                elif kind == "avatar_error":
                    self.avatar_download_active = False
                    self._set_avatar_status(f"导入失败：{payload}（原形象保持不变）", 0)
                    messagebox.showerror("网络形象导入失败", str(payload))
                elif kind == "avatar_restore_done":
                    self.active_pet_package = None
                    self._apply_avatar_decoded(payload, "缓存网络形象")
                elif kind == "avatar_restore_error":
                    self._append_log(f"! 网络形象缓存不可用：{payload}")
                elif kind == "pet_package_done":
                    self.avatar_download_active = False
                    package, decoded = payload
                    self._apply_pet_package_decoded(package, decoded)
                elif kind == "pet_package_error":
                    self.avatar_download_active = False
                    if hasattr(self, "pet_package_status"):
                        self.pet_package_status.configure(text=f"角色包载入失败：{payload}")
                    messagebox.showerror("桌宠角色包载入失败", str(payload))
                elif kind == "pet_package_restore_done":
                    package, decoded = payload
                    self._apply_pet_package_decoded(package, decoded, persist=False)
                elif kind == "pet_package_restore_error":
                    clear_selected_pet()
                    self._append_log(f"! 已保存的桌宠角色包不可用：{payload}")
                    self._restore_cached_avatar()
        except queue.Empty:
            pass
        self.after(50, self._pump)

    def close_app(self):
        if self.mobile_bridge is not None:
            self.mobile_bridge.stop()
            self.mobile_bridge = None
        self.link.close()
        self._stop_live2d_players()
        if self.live2d_license_window is not None and self.live2d_license_window.winfo_exists():
            self.live2d_license_window.destroy()
        if self.avatar_library_window is not None and self.avatar_library_window.winfo_exists():
            self.avatar_library_window.destroy()
        if self.role_card_window is not None and self.role_card_window.winfo_exists():
            self.role_card_window.destroy()
        if self.pet_overlay is not None:
            self.pet_overlay.destroy()
        self.destroy()


if __name__ == "__main__":
    if "--live2d-player" in sys.argv:
        from live2d_player import run_player_guarded

        marker = sys.argv.index("--live2d-player")
        try:
            model_argument = sys.argv[marker + 1]
        except IndexError as error:
            raise SystemExit("缺少 Live2D model3.json 路径") from error
        mode_argument = "stage"
        if "--mode" in sys.argv:
            mode_argument = sys.argv[sys.argv.index("--mode") + 1]
        control_argument = None
        if "--control" in sys.argv:
            try:
                control_argument = sys.argv[sys.argv.index("--control") + 1]
            except IndexError as error:
                raise SystemExit("缺少 Live2D control.json 路径") from error
        capture_argument = None
        if "--capture-output" in sys.argv:
            try:
                capture_argument = sys.argv[sys.argv.index("--capture-output") + 1]
            except IndexError as error:
                raise SystemExit("缺少 Live2D capture 输出路径") from error
        raise SystemExit(run_player_guarded(model_argument, mode_argument, control_argument,
                                            capture_argument))
    Studio().mainloop()
