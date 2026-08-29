"""Phone/PC-side media processing for the 240x320 LabCapsule display.

The ESP32 only decodes RGB332/RLE332/delta332 and draws pixels.  Resizing,
cropping, video decoding, compositing and compression deliberately stay here.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import struct
from typing import Callable, Iterable

from PIL import Image, ImageSequence


WIDTH = 240
HEIGHT = 320
MAX_FPS = 8
MAX_FRAMES = 240
MAX_CLIP_BYTES = 6 * 1024 * 1024
CLIP_MAGIC = 0x4C434734
CLIP_VERSION = 1


@dataclass
class FramePacket:
    encoding: int
    x: int
    y: int
    width: int
    height: int
    data: bytes


@dataclass
class MediaResult:
    payload: bytes
    frames: int
    fps: float
    source_kind: str


def _resample():
    return getattr(Image, "Resampling", Image).LANCZOS


def compose_frame(
    image: Image.Image,
    mode: str = "适应",
    background: str = "黑色",
    zoom: float = 1.0,
    pan_x: int = 0,
    pan_y: int = 0,
    pet: Image.Image | None = None,
    pet_x: int = 120,
    pet_y: int = 240,
    pet_scale: float = 1.0,
) -> Image.Image:
    """Render one screen frame. Zoom may be below 1, leaving padded margins."""
    fill = (255, 255, 255, 255) if background == "白色" else (0, 0, 0, 255)
    canvas = Image.new("RGBA", (WIDTH, HEIGHT), fill)
    source = image.convert("RGBA")
    cover = mode == "填充"
    base = max(WIDTH / source.width, HEIGHT / source.height) if cover else min(
        WIDTH / source.width, HEIGHT / source.height
    )
    scale = max(0.05, base * max(0.25, min(8.0, zoom)))
    target = (
        max(1, round(source.width * scale)),
        max(1, round(source.height * scale)),
    )
    source = source.resize(target, _resample())
    left = (WIDTH - source.width) // 2 + int(pan_x)
    top = (HEIGHT - source.height) // 2 + int(pan_y)
    canvas.alpha_composite(source, (left, top))
    if pet is not None:
        sprite = pet.convert("RGBA")
        size = (
            max(1, round(sprite.width * max(0.1, pet_scale))),
            max(1, round(sprite.height * max(0.1, pet_scale))),
        )
        sprite = sprite.resize(size, _resample())
        canvas.alpha_composite(sprite, (int(pet_x - size[0] / 2), int(pet_y - size[1])))
    return canvas.convert("RGB")


def rgb565(frame: Image.Image) -> bytes:
    output = bytearray(WIDTH * HEIGHT * 2)
    offset = 0
    for red, green, blue in frame.convert("RGB").getdata():
        value = ((red & 0xF8) << 8) | ((green & 0xFC) << 3) | (blue >> 3)
        output[offset] = value >> 8
        output[offset + 1] = value & 0xFF
        offset += 2
    return bytes(output)


def rgb332(frame: Image.Image) -> bytes:
    return bytes(
        (red & 0xE0) | ((green & 0xE0) >> 3) | (blue >> 6)
        for red, green, blue in frame.convert("RGB").getdata()
    )


def _rle(raw: bytes) -> bytes:
    output = bytearray()
    index = 0
    while index < len(raw):
        run = 1
        while index + run < len(raw) and run < 255 and raw[index + run] == raw[index]:
            run += 1
        output.extend((run, raw[index]))
        index += run
    return bytes(output)


def encode_frame(current: bytes, previous: bytes | None) -> FramePacket:
    if previous is None or len(previous) != len(current):
        min_x, min_y, max_x, max_y = 0, 0, WIDTH - 1, HEIGHT - 1
    else:
        changed = [index for index, value in enumerate(current) if value != previous[index]]
        if not changed:
            return FramePacket(1, 0, 0, 0, 0, b"")
        xs = [index % WIDTH for index in changed]
        ys = [index // WIDTH for index in changed]
        min_x, max_x, min_y, max_y = min(xs), max(xs), min(ys), max(ys)

    width, height = max_x - min_x + 1, max_y - min_y + 1
    raw = b"".join(
        current[y * WIDTH + min_x : y * WIDTH + min_x + width]
        for y in range(min_y, max_y + 1)
    )
    rle = _rle(raw)
    delta = bytearray()
    if previous is not None and len(previous) == len(current):
        local = 0
        pixels = width * height
        while local < pixels:
            skip = 0
            while local < pixels:
                global_index = (min_y + local // width) * WIDTH + min_x + local % width
                if current[global_index] != previous[global_index] or skip == 65535:
                    break
                skip += 1
                local += 1
            if skip == 65535 and local < pixels:
                delta.extend((0xFF, 0xFF, 0))
                continue
            start = local
            run = 0
            while local < pixels and run < 255:
                global_index = (min_y + local // width) * WIDTH + min_x + local % width
                if current[global_index] == previous[global_index]:
                    break
                local += 1
                run += 1
            if run == 0:
                continue
            delta.extend((skip & 0xFF, skip >> 8, run))
            for point in range(start, start + run):
                global_index = (min_y + point // width) * WIDTH + min_x + point % width
                delta.append(current[global_index])
    if len(delta) >= 4 and len(delta) < len(raw) and len(delta) < len(rle):
        return FramePacket(3, min_x, min_y, width, height, bytes(delta))
    if len(rle) < len(raw):
        return FramePacket(2, min_x, min_y, width, height, rle)
    return FramePacket(1, min_x, min_y, width, height, raw)


def _write_packet(output: BytesIO, packet: FramePacket) -> None:
    output.write(
        struct.pack(
            ">BHHHHI",
            packet.encoding,
            packet.x,
            packet.y,
            packet.width,
            packet.height,
            len(packet.data),
        )
    )
    output.write(packet.data)


def _gif_frames(path: Path, fps: int) -> list[Image.Image]:
    source = Image.open(path)
    decoded: list[tuple[Image.Image, int]] = []
    total = 0
    for frame in ImageSequence.Iterator(source):
        duration = max(20, int(frame.info.get("duration", source.info.get("duration", 100))))
        decoded.append((frame.convert("RGBA"), duration))
        total += duration
        if len(decoded) >= 600:
            break
    if not decoded:
        raise ValueError("GIF 没有可解码帧")
    interval = max(1000 // fps, (total + MAX_FRAMES - 1) // MAX_FRAMES)
    output: list[Image.Image] = []
    cursor = 0
    for timestamp in range(0, max(interval, total), interval):
        while cursor + 1 < len(decoded) and timestamp >= sum(item[1] for item in decoded[: cursor + 1]):
            cursor += 1
        output.append(decoded[cursor][0].copy())
        if len(output) >= MAX_FRAMES:
            break
    return output


def _video_frames(path: Path, fps: int) -> list[Image.Image]:
    try:
        import imageio.v2 as imageio
    except ImportError as error:
        raise RuntimeError("视频解码需安装 imageio 和 imageio-ffmpeg") from error
    reader = imageio.get_reader(str(path))
    metadata = reader.get_meta_data()
    source_fps = float(metadata.get("fps", fps) or fps)
    stride = max(1, round(source_fps / fps))
    output: list[Image.Image] = []
    try:
        for index, array in enumerate(reader):
            if index % stride:
                continue
            output.append(Image.fromarray(array).convert("RGBA"))
            if len(output) >= MAX_FRAMES:
                break
    finally:
        reader.close()
    if not output:
        raise ValueError("视频没有可解码帧")
    return output


def load_frames(path: str | Path, fps: int) -> tuple[list[Image.Image], str]:
    source = Path(path)
    suffix = source.suffix.lower()
    if suffix == ".gif":
        return _gif_frames(source, fps), "GIF"
    if suffix in {".mp4", ".avi", ".mov", ".mkv", ".webm"}:
        return _video_frames(source, fps), "视频"
    return [Image.open(source).convert("RGBA")], "图片"


def build_media(
    path: str | Path,
    fps: int = 6,
    mode: str = "适应",
    background: str = "黑色",
    zoom: float = 1.0,
    pan_x: int = 0,
    pan_y: int = 0,
    pet_path: str | Path | None = None,
    pet_x: int = 120,
    pet_y: int = 300,
    pet_scale: float = 1.0,
    progress: Callable[[int], None] | None = None,
) -> MediaResult:
    fps = max(1, min(MAX_FPS, int(fps)))
    frames, source_kind = load_frames(path, fps)
    pet_frames: list[Image.Image] = []
    if pet_path:
        pet_frames, _ = load_frames(pet_path, fps)
    rendered: list[Image.Image] = []
    count = max(len(frames), len(pet_frames) or 0)
    count = max(1, min(MAX_FRAMES, count))
    for index in range(count):
        base = frames[index % len(frames)]
        pet = pet_frames[index % len(pet_frames)] if pet_frames else None
        rendered.append(
            compose_frame(base, mode, background, zoom, pan_x, pan_y, pet,
                          pet_x, pet_y, pet_scale)
        )
        if progress:
            progress(round((index + 1) * 35 / count))

    if len(rendered) == 1 and not pet_frames:
        return MediaResult(rgb565(rendered[0]), 1, 0.0, "图片")

    quantized = [rgb332(frame) for frame in rendered]
    bootstrap = encode_frame(quantized[0], None)
    packets: list[FramePacket] = []
    previous = quantized[0]
    for index in range(1, len(quantized)):
        packets.append(encode_frame(quantized[index], previous))
        previous = quantized[index]
        if progress:
            progress(35 + round(index * 55 / len(quantized)))
    packets.append(encode_frame(quantized[0], previous))

    output = BytesIO()
    output.write(struct.pack(">IIII", CLIP_MAGIC, CLIP_VERSION, 1000 // fps, len(packets)))
    _write_packet(output, bootstrap)
    for packet in packets:
        _write_packet(output, packet)
    payload = output.getvalue()
    if len(payload) > MAX_CLIP_BYTES:
        raise ValueError(
            f"处理后为 {len(payload) / 1024 / 1024:.2f} MiB，超过设备 6 MiB 上限；"
            "请降低 FPS、缩短视频或减少全屏高频变化"
        )
    if progress:
        progress(95)
    return MediaResult(payload, len(rendered), fps, source_kind)
