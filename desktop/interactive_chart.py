"""Interactive, decimated real-time chart for LabCapsule motion samples."""

from __future__ import annotations

from bisect import bisect_left
from collections import deque
from dataclasses import dataclass
import math
import tkinter as tk
from tkinter import ttk


CHANNELS = {
    "AX": ("ax", "#67e8f9", "g"),
    "AY": ("ay", "#a78bfa", "g"),
    "AZ": ("az", "#facc15", "g"),
    "|A|": ("a_mag", "#fb7185", "g"),
    "GX": ("gx", "#34d399", "°/s"),
    "GY": ("gy", "#60a5fa", "°/s"),
    "GZ": ("gz", "#f472b6", "°/s"),
    "|G|": ("g_mag", "#fb923c", "°/s"),
}


@dataclass(slots=True)
class MotionPoint:
    timestamp_us: int
    elapsed_s: float
    ax: float
    ay: float
    az: float
    gx: float
    gy: float
    gz: float
    a_mag: float
    g_mag: float


class InteractiveMotionChart(ttk.Frame):
    """Canvas chart with hover coordinates, zoom, pan and live following."""

    BG = "#0f141c"
    GRID = "#263343"
    AXIS = "#64748b"
    TEXT = "#cbd5e1"
    TOOLTIP = "#05070a"

    def __init__(self, parent, max_points: int = 100_000):
        super().__init__(parent)
        self.points: deque[MotionPoint] = deque(maxlen=max_points)
        self.timestamps: deque[float] = deque(maxlen=max_points)
        self.origin_us: int | None = None
        self.channel_vars = {name: tk.BooleanVar(value=name in {"AX", "AY", "AZ", "|A|"})
                             for name in CHANNELS}
        self.follow_var = tk.BooleanVar(value=True)
        self.auto_y_var = tk.BooleanVar(value=True)
        self.window_var = tk.StringVar(value="10 s")
        self._view_x: tuple[float, float] | None = None
        self._view_y: dict[str, tuple[float, float]] = {}
        self._plot_rect = (60.0, 18.0, 700.0, 280.0)
        self._visible_points: list[MotionPoint] = []
        self._draw_pending = False
        self._drag_start: tuple[float, float] | None = None
        self._drag_view_x: tuple[float, float] | None = None
        self._drag_view_y: dict[str, tuple[float, float]] | None = None
        self._build_toolbar()
        self.canvas = tk.Canvas(self, bg=self.BG, highlightthickness=0, cursor="crosshair")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda _: self.request_draw())
        self.canvas.bind("<Motion>", self._hover)
        self.canvas.bind("<Leave>", lambda _: self._clear_cursor())
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.canvas.bind("<ButtonPress-1>", self._drag_begin)
        self.canvas.bind("<B1-Motion>", self._drag_move)
        self.canvas.bind("<ButtonRelease-1>", self._drag_end)
        self.canvas.bind("<Double-Button-1>", lambda _: self.reset_view())

    def _build_toolbar(self):
        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x", pady=(0, 6))
        for name, (_, color, _) in CHANNELS.items():
            check = tk.Checkbutton(
                toolbar, text=name, variable=self.channel_vars[name], command=self.request_draw,
                bg="#151a22", fg=color, activebackground="#151a22", activeforeground=color,
                selectcolor="#0b0e13", highlightthickness=0, padx=4,
            )
            check.pack(side="left")
        ttk.Label(toolbar, text="窗口").pack(side="left", padx=(12, 4))
        window = ttk.Combobox(toolbar, textvariable=self.window_var,
                              values=("2 s", "5 s", "10 s", "30 s", "60 s", "全部"),
                              width=6, state="readonly")
        window.pack(side="left")
        window.bind("<<ComboboxSelected>>", lambda _: self.reset_view())
        ttk.Checkbutton(toolbar, text="实时跟随", variable=self.follow_var,
                        command=self.request_draw).pack(side="left", padx=(10, 2))
        ttk.Checkbutton(toolbar, text="Y 自动", variable=self.auto_y_var,
                        command=self.request_draw).pack(side="left", padx=2)
        ttk.Button(toolbar, text="复位视图", command=self.reset_view).pack(side="right")
        self.readout = ttk.Label(toolbar, text="移动鼠标查看坐标")
        self.readout.pack(side="right", padx=10)

    def add_sample(self, timestamp_us: int, values: tuple[float, float, float, float, float, float]):
        if self.origin_us is None:
            self.origin_us = timestamp_us
        elapsed = (timestamp_us - self.origin_us) / 1_000_000.0
        ax, ay, az, gx, gy, gz = values
        point = MotionPoint(timestamp_us, elapsed, ax, ay, az, gx, gy, gz,
                            math.sqrt(ax * ax + ay * ay + az * az),
                            math.sqrt(gx * gx + gy * gy + gz * gz))
        self.points.append(point)
        self.timestamps.append(elapsed)
        self.request_draw()

    def clear(self):
        self.points.clear()
        self.timestamps.clear()
        self.origin_us = None
        self._view_x = None
        self._view_y.clear()
        self.request_draw()

    def summary(self, limit: int = 5000) -> dict:
        """Return bounded read-only statistics suitable for AI context."""
        points = list(self.points)[-max(16, limit):]
        if not points:
            return {"samples": 0}
        duration = max(0.0, points[-1].elapsed_s - points[0].elapsed_s)
        rate = (len(points) - 1) / duration if duration > 0 and len(points) > 1 else 0.0
        stats = {}
        for label, (key, _color, unit) in CHANNELS.items():
            values = [getattr(point, key) for point in points]
            stats[label] = {
                "min": round(min(values), 6),
                "max": round(max(values), 6),
                "rms": round(math.sqrt(math.fsum(value * value for value in values) /
                                      len(values)), 6),
                "last": round(values[-1], 6),
                "unit": unit,
            }
        return {"samples": len(points), "duration_s": round(duration, 6),
                "estimated_rate_hz": round(rate, 3), "channels": stats}

    def request_draw(self):
        if self._draw_pending:
            return
        self._draw_pending = True
        self.after(33, self._scheduled_draw)

    def _scheduled_draw(self):
        self._draw_pending = False
        self.draw()

    def _window_seconds(self) -> float | None:
        value = self.window_var.get()
        if value == "全部":
            return None
        try:
            return float(value.split()[0])
        except (ValueError, IndexError):
            return 10.0

    def _selected(self):
        selected = [(name, *CHANNELS[name]) for name, variable in self.channel_vars.items()
                    if variable.get()]
        return selected or [("|A|", *CHANNELS["|A|"])]

    def _x_range(self) -> tuple[float, float]:
        if not self.points:
            return 0.0, 10.0
        first, last = self.points[0].elapsed_s, self.points[-1].elapsed_s
        window = self._window_seconds()
        if self.follow_var.get():
            if window is None:
                return first, max(first + .001, last)
            return max(first, last - window), max(first + .001, last)
        if self._view_x is not None:
            return self._view_x
        if window is None:
            return first, max(first + .001, last)
        return max(first, last - window), max(first + .001, last)

    def _points_in_range(self, x_min: float, x_max: float) -> list[MotionPoint]:
        times = list(self.timestamps)
        points = list(self.points)
        left = max(0, bisect_left(times, x_min) - 1)
        right = min(len(points), bisect_left(times, x_max) + 2)
        return points[left:right]

    def _y_ranges(self, visible: list[MotionPoint], selected) -> dict[str, tuple[float, float]]:
        result = {}
        units = list(dict.fromkeys(unit for _label, _key, _color, unit in selected))
        for unit in units:
            if not self.auto_y_var.get() and unit in self._view_y:
                result[unit] = self._view_y[unit]
                continue
            keys = [key for _label, key, _color, item_unit in selected if item_unit == unit]
            values = [getattr(point, key) for point in visible for key in keys]
            if not values:
                result[unit] = (-1.0, 1.0)
                continue
            low, high = min(values), max(values)
            if math.isclose(low, high):
                padding = max(.1, abs(low) * .1)
            else:
                padding = (high - low) * .12
            result[unit] = (low - padding, high + padding)
        return result

    @staticmethod
    def _ticks(low: float, high: float, count: int = 6):
        span = max(1e-9, high - low)
        raw = span / max(2, count)
        magnitude = 10 ** math.floor(math.log10(raw))
        step = min((1, 2, 5, 10), key=lambda value: abs(value * magnitude - raw)) * magnitude
        start = math.ceil(low / step) * step
        result = []
        value = start
        while value <= high + step * .1 and len(result) < 20:
            result.append(value)
            value += step
        return result

    @staticmethod
    def _decimate_extrema(points: list[MotionPoint], key: str,
                          buckets: int) -> list[MotionPoint]:
        """Reduce draw vertices while retaining local minimum/maximum peaks."""
        if len(points) <= max(4, buckets * 2):
            return points
        bucket_count = max(2, buckets)
        result = [points[0]]
        size = (len(points) - 2) / bucket_count
        for bucket in range(bucket_count):
            start = 1 + int(bucket * size)
            end = 1 + int((bucket + 1) * size)
            chunk = points[start:max(start + 1, end)]
            if not chunk:
                continue
            low = min(chunk, key=lambda point: getattr(point, key))
            high = max(chunk, key=lambda point: getattr(point, key))
            for point in sorted((low, high), key=lambda item: item.elapsed_s):
                if point is not result[-1]:
                    result.append(point)
        if result[-1] is not points[-1]:
            result.append(points[-1])
        return result

    def draw(self):
        canvas = self.canvas
        canvas.delete("all")
        width, height = max(240, canvas.winfo_width()), max(180, canvas.winfo_height())
        left, top, right, bottom = 62.0, 18.0, width - 62.0, height - 42.0
        self._plot_rect = left, top, right, bottom
        x_min, x_max = self._x_range()
        selected = self._selected()
        visible = self._points_in_range(x_min, x_max)
        self._visible_points = visible
        y_ranges = self._y_ranges(visible, selected)
        self._view_y = y_ranges

        for value in self._ticks(x_min, x_max, 7):
            x = self._map_x(value, x_min, x_max)
            canvas.create_line(x, top, x, bottom, fill=self.GRID)
            canvas.create_text(x, bottom + 17, text=f"{value:.3g}s", fill=self.TEXT,
                               font=("Cascadia Mono", 8))
        for axis_index, (unit, (y_min, y_max)) in enumerate(y_ranges.items()):
            axis_x = left if axis_index == 0 else right
            anchor = "e" if axis_index == 0 else "w"
            offset = -7 if axis_index == 0 else 7
            for value in self._ticks(y_min, y_max, 6):
                y = self._map_y(value, y_min, y_max)
                if axis_index == 0:
                    canvas.create_line(left, y, right, y, fill=self.GRID)
                else:
                    canvas.create_line(right - 4, y, right, y, fill=self.AXIS)
                canvas.create_text(axis_x + offset, y, text=f"{value:.3g}", fill=self.TEXT,
                                   anchor=anchor, font=("Cascadia Mono", 8))
            canvas.create_text(axis_x + offset, top + 2, text=unit, fill=self.AXIS,
                               anchor=("se" if axis_index == 0 else "sw"),
                               font=("Cascadia Mono", 8, "bold"))
        canvas.create_rectangle(left, top, right, bottom, outline=self.AXIS)
        canvas.create_text(left, bottom + 34, anchor="w", fill=self.AXIS,
                           text="滚轮缩放时间 · Ctrl+滚轮缩放数值 · 拖动平移 · 双击复位",
                           font=("Microsoft YaHei UI", 8))
        if len(visible) < 2:
            canvas.create_text((left + right) / 2, (top + bottom) / 2,
                               text="等待实验数据…", fill=self.AXIS,
                               font=("Microsoft YaHei UI", 12))
            return

        for label, key, color, _unit in selected:
            y_min, y_max = y_ranges[_unit]
            sampled = self._decimate_extrema(visible, key, max(50, int(right - left)))
            coordinates = []
            for point in sampled:
                coordinates.extend((self._map_x(point.elapsed_s, x_min, x_max),
                                    self._map_y(getattr(point, key), y_min, y_max)))
            if len(coordinates) >= 4:
                canvas.create_line(*coordinates, fill=color, width=2, smooth=False,
                                   tags=("series", label))

    def _map_x(self, value, low, high):
        left, _, right, _ = self._plot_rect
        return left + (value - low) * (right - left) / max(1e-12, high - low)

    def _map_y(self, value, low, high):
        _, top, _, bottom = self._plot_rect
        return bottom - (value - low) * (bottom - top) / max(1e-12, high - low)

    def _unmap_x(self, pixel, low, high):
        left, _, right, _ = self._plot_rect
        return low + (pixel - left) * (high - low) / max(1, right - left)

    def _unmap_y(self, pixel, low, high):
        _, top, _, bottom = self._plot_rect
        return high - (pixel - top) * (high - low) / max(1, bottom - top)

    def _inside(self, x, y):
        left, top, right, bottom = self._plot_rect
        return left <= x <= right and top <= y <= bottom

    def _hover(self, event):
        self.canvas.delete("cursor")
        if not self._inside(event.x, event.y) or not self._visible_points:
            return
        x_min, x_max = self._x_range()
        target = self._unmap_x(event.x, x_min, x_max)
        times = [point.elapsed_s for point in self._visible_points]
        index = bisect_left(times, target)
        candidates = self._visible_points[max(0, index - 1): min(len(times), index + 2)]
        point = min(candidates, key=lambda item: abs(item.elapsed_s - target))
        selected = self._selected()
        label, key, color, unit = min(
            selected,
            key=lambda item: abs(self._map_y(getattr(point, item[1]),
                                             *self._view_y.get(item[3], (-1, 1))) - event.y),
        )
        y_min, y_max = self._view_y.get(unit, (-1, 1))
        x = self._map_x(point.elapsed_s, x_min, x_max)
        value = getattr(point, key)
        y = self._map_y(value, y_min, y_max)
        self.canvas.create_line(x, self._plot_rect[1], x, self._plot_rect[3],
                                fill="#94a3b8", dash=(3, 3), tags="cursor")
        self.canvas.create_line(self._plot_rect[0], y, self._plot_rect[2], y,
                                fill="#94a3b8", dash=(3, 3), tags="cursor")
        self.canvas.create_oval(x - 4, y - 4, x + 4, y + 4, fill=color,
                                outline="white", tags="cursor")
        text = f"t={point.elapsed_s:.6f} s  timestamp={point.timestamp_us} µs  {label}={value:.6f} {unit}"
        self.readout.configure(text=text)
        box_x = min(self._plot_rect[2] - 248, max(self._plot_rect[0] + 6, event.x + 12))
        box_y = max(self._plot_rect[1] + 6, event.y - 45)
        self.canvas.create_rectangle(box_x, box_y, box_x + 242, box_y + 34,
                                     fill=self.TOOLTIP, outline=color, tags="cursor")
        self.canvas.create_text(box_x + 7, box_y + 7, anchor="nw", fill=self.TEXT,
                                text=f"X {point.elapsed_s:.6f} s\nY {label} {value:.6f} {unit}",
                                font=("Cascadia Mono", 8), tags="cursor")

    def _clear_cursor(self):
        self.canvas.delete("cursor")
        self.readout.configure(text="移动鼠标查看坐标")

    def _wheel(self, event):
        if not self._inside(event.x, event.y) or not self.points:
            return
        factor = 0.8 if event.delta > 0 else 1.25
        x_min, x_max = self._x_range()
        if event.state & 0x0004:  # Control
            ranges = self._view_y or {"g": (-1.0, 1.0)}
            zoomed = {}
            for unit, (y_min, y_max) in ranges.items():
                anchor = self._unmap_y(event.y, y_min, y_max)
                zoomed[unit] = (anchor + (y_min - anchor) * factor,
                                anchor + (y_max - anchor) * factor)
            self._view_y = zoomed
            self.auto_y_var.set(False)
        else:
            anchor = self._unmap_x(event.x, x_min, x_max)
            span = max(.02, (x_max - x_min) * factor)
            ratio = (anchor - x_min) / max(1e-12, x_max - x_min)
            self._view_x = anchor - span * ratio, anchor + span * (1 - ratio)
            self.follow_var.set(False)
        self.request_draw()

    def _drag_begin(self, event):
        if not self._inside(event.x, event.y):
            return
        self._drag_start = event.x, event.y
        self._drag_view_x = self._x_range()
        self._drag_view_y = dict(self._view_y or {"g": (-1.0, 1.0)})
        self.follow_var.set(False)

    def _drag_move(self, event):
        if not self._drag_start or not self._drag_view_x or not self._drag_view_y:
            return
        left, top, right, bottom = self._plot_rect
        dx = event.x - self._drag_start[0]
        dy = event.y - self._drag_start[1]
        x_low, x_high = self._drag_view_x
        x_shift = -dx * (x_high - x_low) / max(1, right - left)
        self._view_x = x_low + x_shift, x_high + x_shift
        self._view_y = {
            unit: (
                y_low + dy * (y_high - y_low) / max(1, bottom - top),
                y_high + dy * (y_high - y_low) / max(1, bottom - top),
            )
            for unit, (y_low, y_high) in self._drag_view_y.items()
        }
        self.auto_y_var.set(False)
        self.request_draw()

    def _drag_end(self, _event):
        self._drag_start = None
        self._drag_view_x = None
        self._drag_view_y = None

    def reset_view(self):
        self._view_x = None
        self._view_y.clear()
        self.follow_var.set(True)
        self.auto_y_var.set(True)
        self.request_draw()
