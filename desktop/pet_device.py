"""Low-bandwidth rendering helpers for the 240x320 device pet screen.

The ESP32 animates the character locally.  The desktop only rasterizes the
Unicode speech text into a compact one-bit mask, so Chinese replies do not
require a large CJK font in firmware or a full-screen serial video stream.
"""

from __future__ import annotations

from pathlib import Path
import re

from PIL import Image, ImageDraw, ImageFont


PET_BUBBLE_WIDTH = 216
PET_BUBBLE_HEIGHT = 64
PET_BUBBLE_BYTES = PET_BUBBLE_WIDTH * PET_BUBBLE_HEIGHT // 8
MAX_DEVICE_REPLY_CHARS = 180

EMOTION_ACTIONS = {
    "idle": "IDLE",
    "happy": "BOUNCE",
    "curious": "TILT",
    "thinking": "THINK",
    "speaking": "TALK",
    "experiment": "SCAN",
    "success": "CELEBRATE",
    "warning": "ALERT",
    "sleeping": "SLEEP",
}

_SECRET_PATTERN = re.compile(
    r"(?i)(api[_ -]?key|token|secret|password|密码|密钥)\s*[:=：]?\s*([^\s,;，；]{4,})"
)


def _font_candidates() -> tuple[Path, ...]:
    return (
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/msyhbd.ttc"),
        Path("C:/Windows/Fonts/simhei.ttf"),
        Path("C:/Windows/Fonts/arial.ttf"),
    )


def device_font(size: int = 15, font_path: str | Path | None = None):
    candidates = (Path(font_path),) if font_path else _font_candidates()
    for candidate in candidates:
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


def sanitize_device_reply(text: str) -> str:
    clean = _SECRET_PATTERN.sub(lambda match: f"{match.group(1)}：[已隐藏]", str(text))
    clean = " ".join(clean.replace("\r", " ").replace("\n", " ").split())
    return clean[:MAX_DEVICE_REPLY_CHARS]


def _wrap_pixels(draw: ImageDraw.ImageDraw, text: str, font, max_width: int,
                 max_lines: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for character in text:
        candidate = current + character
        width = draw.textbbox((0, 0), candidate, font=font)[2]
        if current and width > max_width:
            lines.append(current.rstrip())
            current = character.lstrip()
            if len(lines) == max_lines:
                break
        else:
            current = candidate
    if len(lines) < max_lines and current:
        lines.append(current.rstrip())
    consumed = "".join(lines)
    if len(consumed) < len(text) and lines:
        tail = lines[-1]
        while tail and draw.textbbox((0, 0), tail + "…", font=font)[2] > max_width:
            tail = tail[:-1]
        lines[-1] = tail + "…"
    return lines


def render_pet_bubble(text: str, font_path: str | Path | None = None) -> bytes:
    """Render a Chinese-capable reply as an MSB-first 1-bit row-major mask."""
    clean = sanitize_device_reply(text) or "我在。"
    image = Image.new("1", (PET_BUBBLE_WIDTH, PET_BUBBLE_HEIGHT), 0)
    draw = ImageDraw.Draw(image)
    font = device_font(15, font_path)
    lines = _wrap_pixels(draw, clean, font, PET_BUBBLE_WIDTH - 8, 3)
    line_height = max(16, draw.textbbox((0, 0), "国Ag", font=font)[3] + 2)
    total_height = line_height * len(lines)
    y = max(1, (PET_BUBBLE_HEIGHT - total_height) // 2)
    for line in lines:
        draw.text((4, y), line, fill=1, font=font)
        y += line_height

    pixels = image.load()
    output = bytearray(PET_BUBBLE_BYTES)
    for y in range(PET_BUBBLE_HEIGHT):
        for x in range(PET_BUBBLE_WIDTH):
            if pixels[x, y]:
                bit_index = y * PET_BUBBLE_WIDTH + x
                output[bit_index >> 3] |= 0x80 >> (bit_index & 7)
    return bytes(output)


def pet_state_command(emotion: str, action: str = "") -> str:
    safe_emotion = emotion.lower() if emotion.lower() in EMOTION_ACTIONS else "speaking"
    safe_action = re.sub(r"[^A-Z_]", "", action.upper())[:16]
    if safe_action not in set(EMOTION_ACTIONS.values()):
        safe_action = EMOTION_ACTIONS[safe_emotion]
    return f"PET,STATE,{safe_emotion.upper()},{safe_action}"
