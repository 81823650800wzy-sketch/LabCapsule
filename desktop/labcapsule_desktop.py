"""LabCapsule Studio V0.8 - interactive data and AI companion for Windows.

The app intentionally never changes the computer's Wi-Fi connection.  It uses
the CH343/native USB serial link for telemetry, experiments and media upload.
"""

from __future__ import annotations

import asyncio
import csv
from datetime import datetime
import math
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
from media_codec import HEIGHT, MAX_FPS, WIDTH, build_media, compose_frame, load_frames
from pet_agent import CharacterProfile, PetAgentRuntime, PetAvatarCanvas, PetOverlay, PetReply, PetSettings
from pet_packages import (PET_SELECTION_PATH, PetPackage, avatar_asset_for_package, clear_selected_pet,
                          discover_pet_packages, save_selected_pet, selected_pet_package)
from live2d_runtime import has_live2d_consent, player_command, save_live2d_consent


APP_VERSION = "0.10.0"
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


class SerialLink:
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
            self.port.write((safe + "\n").encode("utf-8"))

    def upload(self, kind: str, payload: bytes, progress) -> None:
        if not self.connected:
            raise RuntimeError("设备未连接")
        crc = zlib.crc32(payload) & 0xFFFFFFFF
        self.ready_event.clear()
        self.done_event.clear()
        self.upload_error = ""
        with self.write_lock:
            assert self.port
            header = f"UPLOAD,{kind},{len(payload)},{crc:08X}\n".encode("ascii")
            self.port.write(header)
            if not self.ready_event.wait(8):
                raise TimeoutError("设备未进入 USB 上传模式")
            for offset in range(0, len(payload), 1024):
                if self.stop_event.is_set():
                    raise RuntimeError("连接已断开")
                self.port.write(payload[offset : offset + 1024])
                progress(min(99, round((offset + 1024) * 100 / len(payload))))
            self.port.flush()
        if not self.done_event.wait(25):
            raise TimeoutError("设备未确认媒体校验结果")
        if self.upload_error:
            raise RuntimeError(self.upload_error)
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
        self.link = SerialLink(
            lambda line: self.events.put(("line", line)),
            lambda state, port: self.events.put(("state", (state, port))),
        )
        self.notification_bridge = WindowsNotificationBridge()
        self.notification_enabled = False
        self.last_notification_poll = 0.0
        self.samples: list[list[str]] = []
        self.device_state = "READY"
        self.device_recording = False
        self.last_sample: tuple[str, ...] | None = None
        self.last_pet_error_at = 0.0
        self.media_path = ""
        self.pet_path = ""
        self.preview_photo = None
        self.pet_settings = PetSettings.load()
        self.pet_runtime = PetAgentRuntime(self.pet_settings)
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

    def _layout(self):
        header = tk.Frame(self, bg=self.BG)
        header.pack(fill="x", padx=20, pady=(16, 8))
        tk.Label(header, text="LABCAPSULE / STUDIO", bg=self.BG, fg=self.INK,
                 font=("Bahnschrift", 19, "bold")).pack(side="left")
        tk.Label(header, text=" USB FIRST · LOCAL MEDIA · MOTION LAB ", bg=self.YELLOW,
                 fg="#111318", font=("Bahnschrift", 9, "bold"), padx=8, pady=3).pack(side="left", padx=14)
        self.connection_label = tk.Label(header, text="● 未连接", bg=self.BG, fg=self.RED,
                                         font=("Microsoft YaHei UI", 10, "bold"))
        self.connection_label.pack(side="right")

        connect = tk.Frame(self, bg=self.PANEL, padx=12, pady=10)
        connect.pack(fill="x", padx=20, pady=(0, 10))
        tk.Label(connect, text="数据线设备", bg=self.PANEL, fg=self.MUTED).pack(side="left")
        self.port_var = tk.StringVar()
        self.port_box = ttk.Combobox(connect, textvariable=self.port_var, width=42, state="readonly")
        self.port_box.pack(side="left", padx=10)
        ttk.Button(connect, text="重新扫描", command=self.refresh_ports).pack(side="left", padx=4)
        self.connect_button = ttk.Button(connect, text="连接", style="Accent.TButton",
                                         command=self.toggle_connect)
        self.connect_button.pack(side="left", padx=4)
        tk.Label(connect, text="不会连接或切换设备热点，不影响电脑联网", bg=self.PANEL,
                 fg=self.CYAN).pack(side="right")

        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        self.dashboard = tk.Frame(self.tabs, bg=self.BG)
        self.screen = tk.Frame(self.tabs, bg=self.BG)
        self.experiment = tk.Frame(self.tabs, bg=self.BG)
        self.pet = tk.Frame(self.tabs, bg=self.BG)
        self.console = tk.Frame(self.tabs, bg=self.BG)
        self.tabs.add(self.dashboard, text="状态中心")
        self.tabs.add(self.screen, text="屏幕工作室")
        self.tabs.add(self.experiment, text="实验与数据")
        self.tabs.add(self.pet, text="AI 桌宠")
        self.tabs.add(self.console, text="诊断日志")
        self._dashboard_ui()
        self._screen_ui()
        self._experiment_ui()
        self._pet_ui()
        self._console_ui()

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
        self.pet.columnconfigure(0, weight=0)
        self.pet.columnconfigure(1, weight=3)
        self.pet.columnconfigure(2, weight=2)
        self.pet.rowconfigure(0, weight=1)
        avatar_card = self._card(self.pet, "角色舞台", 0, 0)
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
        ttk.Button(avatar_card, text="将当前形象送到屏幕工作室",
                   command=self.send_avatar_to_screen_studio).pack(fill="x", pady=3)
        self.pet_overlay_button = ttk.Button(avatar_card, text="显示桌面悬浮宠物",
                                             command=self.toggle_pet_overlay)
        self.pet_overlay_button.pack(fill="x", pady=3)
        ttk.Label(avatar_card, text="拖动悬浮宠物移动；双击返回本页；右键隐藏。",
                  style="Muted.TLabel", wraplength=230).pack(anchor="w", pady=8)

        chat_card = self._card(self.pet, "对话与实验陪伴", 0, 1)
        self.pet_chat = tk.Text(chat_card, bg="#0f141c", fg=self.INK,
                                insertbackground=self.INK, relief="flat", wrap="word",
                                font=("Microsoft YaHei UI", 10), padx=10, pady=10)
        self.pet_chat.pack(fill="both", expand=True)
        self.pet_chat.tag_configure("user", foreground=self.CYAN, spacing1=7)
        self.pet_chat.tag_configure("pet", foreground=self.INK, spacing1=7)
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
        quick = tk.Frame(chat_card, bg=self.PANEL)
        quick.pack(fill="x", pady=(7, 0))
        for label, message in (("解释当前状态", "请解释当前设备和实验状态"),
                               ("设计一个实验", "请帮我把想法整理成可测量的对照实验"),
                               ("检查数据质量", "根据当前上下文提醒我检查实验数据质量")):
            ttk.Button(quick, text=label,
                       command=lambda value=message: self.send_pet_message(value)).pack(side="left", padx=2)

        settings_card = self._card(self.pet, "角色与 AI 设置", 0, 2)
        self.pet_name_var = tk.StringVar(value=self.pet_settings.profile.name)
        self.pet_endpoint_var = tk.StringVar(value=self.pet_settings.endpoint)
        self.pet_model_var = tk.StringVar(value=self.pet_settings.model)
        self.pet_key_var = tk.StringVar(value=self.pet_settings.api_key)
        self.pet_memory_var = tk.BooleanVar(value=self.pet_settings.remember)
        self.pet_sync_var = tk.BooleanVar(value=self.pet_settings.sync_device)
        self.pet_auto_var = tk.BooleanVar(value=self.pet_settings.auto_react)
        for title, variable, secret in (("角色名称", self.pet_name_var, False),
                                        ("OpenAI 兼容 Endpoint", self.pet_endpoint_var, False),
                                        ("模型", self.pet_model_var, False),
                                        ("API Key（DPAPI 加密）", self.pet_key_var, True)):
            ttk.Label(settings_card, text=title, style="Muted.TLabel").pack(anchor="w", pady=(5, 2))
            ttk.Entry(settings_card, textvariable=variable, show="•" if secret else "").pack(fill="x")
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
        ttk.Button(settings_card, text="保存角色与 AI 设置", style="Accent.TButton",
                   command=self.save_pet_settings).pack(fill="x", pady=(10, 3))
        ttk.Button(settings_card, text="清除桌宠记忆", command=self.clear_pet_memory).pack(fill="x", pady=3)
        ttk.Label(settings_card,
                  text="模型没有系统命令权限；启动/中止实验、网络和固件操作始终由用户确认。",
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
        ttk.Button(direct_buttons, text="送到屏幕工作室",
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
             "V0.10.0_UNIFIED_PET_PACKAGE_TEST_ZH.md"),
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
            command = player_command(package.live2d_model_path, mode, ROOT, sys.executable)
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
            messagebox.showinfo(
                "Live2D 与设备屏幕",
                "ESP32-S3 屏幕不能直接运行 moc3。请从 Live2D 编辑器导出或录制已授权的 GIF / "
                "序列帧，再由屏幕工作室裁剪、压缩并写入设备。")
            return
        if self.avatar_decoded is None:
            messagebox.showinfo("当前是内置形象",
                                "内置矢量形象不是媒体文件。请先下载网络 PNG / GIF 形象。")
            return
        self.media_path = self.avatar_decoded.asset.path
        self.pet_path = ""
        self.media_label.configure(text=f"网络形象 · {Path(self.media_path).name}")
        self.tabs.select(self.screen)
        self.preview_media()
        self.media_state.configure(text="网络形象已载入；确认预览后可通过 USB 上传，不会自动写入设备。")

    def refresh_ports(self):
        ports = list(list_ports.comports())
        values = [f"{item.device} — {item.description}" for item in ports]
        self.port_box["values"] = values
        preferred = next((value for value in values if value.upper().startswith("COM8 ")), None)
        if preferred or values:
            self.port_var.set(preferred or values[0])

    def toggle_connect(self):
        if self.link.connected:
            self.link.close()
            return
        name = self.port_var.get().split(" — ", 1)[0].strip()
        if not name:
            messagebox.showwarning("未发现设备", "请连接数据 USB-C 后重新扫描。")
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
                  "event": "系统"}.get(kind, "系统")
        self.pet_chat.configure(state="normal")
        self.pet_chat.insert("end", f"{prefix}  {text}\n", kind if kind in {"user", "pet", "event"} else "event")
        self.pet_chat.configure(state="disabled")
        self.pet_chat.see("end")

    def _set_pet_state(self, emotion: str, caption: str):
        self.pet_emotion = emotion
        if hasattr(self, "pet_avatar"):
            self.pet_avatar.set_state(emotion, caption)
            self.pet_state_label.configure(text=f"{emotion.upper()} · {caption[:36]}")
        if self.pet_overlay is not None:
            self.pet_overlay.set_state(emotion, caption)

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
                avatar_url=self.avatar_url_var.get().strip(),
                avatar_source_name=self.pet_settings.avatar_source_name,
                profile=CharacterProfile(
                    name=self.pet_name_var.get().strip()[:24] or "胶囊零号",
                    persona=self.pet_persona.get("1.0", "end").strip()[:2400],
                    greeting=self.pet_settings.profile.greeting,
                ),
            )
            self.pet_settings.save()
            self.pet_runtime.update_settings(self.pet_settings)
            self._pet_append("event", "角色与 AI 设置已保存；API Key 由当前 Windows 用户 DPAPI 加密。")
            self._set_pet_state("success", "SETTINGS SAVED")
        except Exception as error:
            messagebox.showerror("AI 设置保存失败", str(error))

    def clear_pet_memory(self):
        self.pet_runtime.memory.clear()
        self._pet_append("event", "本地桌宠对话和长期偏好已清除。")
        self._set_pet_state("idle", "MEMORY CLEARED")

    def _device_context(self) -> dict:
        return {
            "connected": self.link.connected,
            "port": self.link.port.port if self.link.connected and self.link.port else "",
            "state": self.device_state,
            "recording": self.device_recording,
            "samples": len(self.samples),
            "latest_sample": self.last_sample,
            "motion_summary": self.motion_chart.summary(),
            "chart_channels": [name for name, variable in self.motion_chart.channel_vars.items()
                               if variable.get()],
            "chart_window": self.motion_chart.window_var.get(),
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
            self.events.put(("pet_reply", reply))
        threading.Thread(target=worker, daemon=True, name="pet-agent").start()

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
        self._pet_append("pet", reply.text)
        self._set_pet_state(reply.emotion, reply.text)
        if (reply.device_notice and self.pet_settings.sync_device and self.link.connected
                and not self.device_recording):
            self.send(f"NOTICE,AI PET,{self._ascii_device_notice(reply)}")
        self.after(4500, lambda: self._set_pet_state("idle", "LINK READY")
                   if self.pet_emotion == reply.emotion else None)

    def _pet_event(self, event: str, detail: str = ""):
        if not self.pet_settings.auto_react:
            return
        reply = self.pet_runtime.react_event(event, detail)
        if reply:
            self._pet_append("event", reply.text)
            self._set_pet_state(reply.emotion, event.replace("_", " ").upper())
            if (reply.device_notice and self.pet_settings.sync_device and self.link.connected
                    and not self.device_recording):
                self.send(f"NOTICE,AI PET,{self._ascii_device_notice(reply)}")

    def _handle_line(self, line: str):
        self._append_log(line)
        if line.startswith("STATUS,"):
            fields = line.split(",")
            if len(fields) > 1:
                self.device_state = fields[1]
        elif line.startswith("OK,START"):
            self.device_state = "RECORDING"
            self.device_recording = True
            self._pet_event("experiment_start")
        elif line.startswith("OK,COMPLETE") or line.startswith("OK,STOP"):
            self.device_state = "COMPLETE"
            self.device_recording = False
            self._pet_event("experiment_complete")
        elif line.startswith("OK,ABORT"):
            self.device_state = "ABORTED"
            self.device_recording = False
            self._pet_event("experiment_abort")
        elif line.startswith("ERR,") and time.monotonic() - self.last_pet_error_at > 8:
            self.last_pet_error_at = time.monotonic()
            self._pet_event("device_error", line[:100])
        if line.startswith("STATUS,") or line.startswith("PONG,") or line.startswith("GIF,"):
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
        ram = round(psutil.virtual_memory().percent)
        disk = round(psutil.disk_usage(Path.home().anchor or "C:\\").percent)
        temperature = -1
        try:
            readings = psutil.sensors_temperatures()
            values = [item.current for group in readings.values() for item in group if item.current]
            if values:
                temperature = round(values[0])
        except Exception:
            pass
        for key, value in (("cpu", cpu), ("ram", ram), ("disk", disk)):
            self.metric_labels[key].configure(text=f"{value}%")
        if self.link.connected:
            self.send(f"HOST,{cpu},{ram},{disk},{temperature}")
            now = time.monotonic()
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
            messagebox.showwarning("未连接", "请先通过数据线连接设备。")
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
                self.events.put(("media_state", f"已压缩 {len(result.payload):,} B，USB 写入设备…"))
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
                elif kind == "notice":
                    self.notification_enabled = bool(payload)
                    self.notice_state.configure(text="系统通知镜像已启用" if payload else
                                                "未获授权或缺少 winsdk；可继续手动发送")
                elif kind == "system_notice":
                    title, body = payload
                    self._notice_command(title, body)
                elif kind == "pet_reply":
                    self._handle_pet_reply(payload)
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
        self.link.close()
        self._stop_live2d_players()
        if self.live2d_license_window is not None and self.live2d_license_window.winfo_exists():
            self.live2d_license_window.destroy()
        if self.avatar_library_window is not None and self.avatar_library_window.winfo_exists():
            self.avatar_library_window.destroy()
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
        mode_argument = "overlay" if "--mode" in sys.argv and sys.argv[
            sys.argv.index("--mode") + 1] == "overlay" else "stage"
        raise SystemExit(run_player_guarded(model_argument, mode_argument))
    Studio().mainloop()
