"""Safe network avatar download, validation, caching and frame decoding.

The desktop app performs all expensive work.  The ESP32 only receives a
separately prepared 240 x 320 screen asset when the user explicitly requests
it from Screen Studio.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Callable
from urllib import request
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from PIL import Image, ImageSequence, UnidentifiedImageError


APP_DIR = Path(os.environ.get("APPDATA", Path.home())) / "LabCapsule"
AVATAR_CACHE_DIR = APP_DIR / "avatar"
MAX_DOWNLOAD_BYTES = 12 * 1024 * 1024
MAX_DIMENSION = 2048
MAX_PIXELS = 4_194_304
MAX_FRAMES = 120
MAX_TOTAL_SOURCE_PIXELS = 180_000_000
ALLOWED_FORMATS = {"PNG": "png", "JPEG": "jpg", "WEBP": "webp", "GIF": "gif"}
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}

# These styles are listed in DiceBear's CC0 1.0 group as of API 10.x.
DICEBEAR_CC0_PRESETS = {
    "像素伙伴 · Pixel Art (CC0)": "pixel-art",
    "线稿角色 · Lorelei (CC0)": "lorelei",
    "拇指角色 · Thumbs (CC0)": "thumbs",
    "抽象图形 · Shapes (CC0)": "shapes",
}
DICEBEAR_API_VERSION = "10.x"


@dataclass(frozen=True)
class AvatarAsset:
    path: str
    source_url: str
    final_url: str
    sha256: str
    format: str
    content_type: str
    bytes: int
    width: int
    height: int
    frames: int


@dataclass
class DecodedAvatar:
    asset: AvatarAsset
    frames: list[Image.Image]
    durations_ms: list[int]


def validate_avatar_url(value: str) -> str:
    """Return a normalized URL or raise before any network access."""
    url = value.strip()
    if not url or len(url) > 2048:
        raise ValueError("形象地址为空或过长")
    parsed = urlparse(url)
    if parsed.username or parsed.password:
        raise ValueError("形象地址不能包含用户名或密码")
    if not parsed.hostname:
        raise ValueError("形象地址缺少主机名")
    hostname = parsed.hostname.lower().rstrip(".")
    if parsed.scheme == "http" and hostname not in LOCAL_HOSTS:
        raise ValueError("网络形象必须使用 HTTPS；HTTP 仅允许本机测试地址")
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("仅支持 HTTP(S) 图片地址")
    if parsed.fragment:
        parsed = parsed._replace(fragment="")
    return urlunparse(parsed)


def display_url(value: str) -> str:
    """Hide common signed-URL secrets before showing a URL in status text."""
    try:
        parsed = urlparse(value)
        secret_names = re.compile(r"(?i)(token|key|secret|signature|credential|password|auth)")
        query = [(key, "[已隐藏]" if secret_names.search(key) else item)
                 for key, item in parse_qsl(parsed.query, keep_blank_values=True)]
        return urlunparse(parsed._replace(query=urlencode(query)))
    except Exception:
        return value[:160]


def dicebear_url(style: str, seed: str = "LabCapsule") -> str:
    if style not in DICEBEAR_CC0_PRESETS.values():
        raise ValueError("未知或未列入 CC0 白名单的 DiceBear 风格")
    clean_seed = seed.strip()[:64] or "LabCapsule"
    return (f"https://api.dicebear.com/{DICEBEAR_API_VERSION}/{style}/png?"
            + urlencode({"seed": clean_seed, "size": 256}))


def _inspect_image(blob: bytes) -> tuple[str, int, int, int]:
    try:
        with Image.open(BytesIO(blob)) as image:
            image_format = (image.format or "").upper()
            if image_format not in ALLOWED_FORMATS:
                raise ValueError("只支持 PNG、JPG、WebP 或 GIF 形象")
            width, height = image.size
            frames = int(getattr(image, "n_frames", 1))
            if width < 1 or height < 1:
                raise ValueError("图片尺寸无效")
            if width > MAX_DIMENSION or height > MAX_DIMENSION or width * height > MAX_PIXELS:
                raise ValueError(f"图片过大；上限 {MAX_DIMENSION}×{MAX_DIMENSION} / {MAX_PIXELS:,} 像素")
            if frames < 1 or frames > MAX_FRAMES:
                raise ValueError(f"动画帧数为 {frames}；上限 {MAX_FRAMES} 帧")
            if width * height * frames > MAX_TOTAL_SOURCE_PIXELS:
                raise ValueError("动画解码量过大，请先降低尺寸或帧数")
            image.seek(0)
            image.load()
            return image_format, width, height, frames
    except (UnidentifiedImageError, OSError) as error:
        raise ValueError(f"文件不是可解码的图片：{error}") from error


def inspect_local_avatar(path: str | Path) -> AvatarAsset:
    """Validate a local image with the same limits used for network avatars."""
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise ValueError("桌宠主形象文件不存在")
    size = source.stat().st_size
    if size < 1:
        raise ValueError("桌宠主形象为空文件")
    if size > MAX_DOWNLOAD_BYTES:
        raise ValueError(f"桌宠主形象超过 {MAX_DOWNLOAD_BYTES // 1024 // 1024} MiB 上限")
    blob = source.read_bytes()
    image_format, width, height, frames = _inspect_image(blob)
    content_types = {
        "PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp", "GIF": "image/gif",
    }
    return AvatarAsset(
        path=str(source), source_url="", final_url="",
        sha256=hashlib.sha256(blob).hexdigest(), format=image_format,
        content_type=content_types[image_format], bytes=len(blob),
        width=width, height=height, frames=frames,
    )


def download_avatar(
    url: str,
    cache_dir: str | Path = AVATAR_CACHE_DIR,
    progress: Callable[[int], None] | None = None,
    timeout: float = 30,
) -> AvatarAsset:
    """Download and atomically make one validated asset the current avatar."""
    source_url = validate_avatar_url(url)
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    call = request.Request(source_url, headers={
        "User-Agent": "LabCapsule-Studio/0.9 (+https://github.com/81823650800wzy-sketch/LabCapsule)",
        "Accept": "image/png,image/jpeg,image/webp,image/gif;q=0.9",
    })
    chunks: list[bytes] = []
    received = 0
    with request.urlopen(call, timeout=timeout) as response:
        final_url = validate_avatar_url(response.geturl())
        content_type = response.headers.get_content_type().lower()
        declared = response.headers.get("Content-Length")
        if declared:
            try:
                if int(declared) > MAX_DOWNLOAD_BYTES:
                    raise ValueError(f"下载文件超过 {MAX_DOWNLOAD_BYTES // 1024 // 1024} MiB 上限")
            except ValueError as error:
                if "超过" in str(error):
                    raise
        if not (content_type.startswith("image/") or content_type == "application/octet-stream"):
            raise ValueError(f"服务器返回的不是图片（{content_type}）")
        while True:
            block = response.read(64 * 1024)
            if not block:
                break
            received += len(block)
            if received > MAX_DOWNLOAD_BYTES:
                raise ValueError(f"下载文件超过 {MAX_DOWNLOAD_BYTES // 1024 // 1024} MiB 上限")
            chunks.append(block)
            if progress:
                expected = int(declared) if declared and declared.isdigit() else MAX_DOWNLOAD_BYTES
                progress(min(95, max(1, round(received * 95 / max(1, expected)))))
    blob = b"".join(chunks)
    if not blob:
        raise ValueError("服务器返回了空文件")
    image_format, width, height, frames = _inspect_image(blob)
    digest = hashlib.sha256(blob).hexdigest()
    suffix = ALLOWED_FORMATS[image_format]
    final_path = cache / f"{digest}.{suffix}"
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix="avatar-", suffix=".tmp", dir=cache,
                                         delete=False) as temporary:
            temporary.write(blob)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        temporary_path.replace(final_path)
        asset = AvatarAsset(
            path=str(final_path), source_url=source_url, final_url=final_url,
            sha256=digest, format=image_format, content_type=content_type,
            bytes=len(blob), width=width, height=height, frames=frames,
        )
        metadata_tmp = cache / "current.json.tmp"
        metadata_tmp.write_text(json.dumps(asdict(asset), ensure_ascii=False, indent=2),
                                encoding="utf-8")
        metadata_tmp.replace(cache / "current.json")
        for item in cache.iterdir():
            if item.is_file() and item not in {final_path, cache / "current.json"}:
                try:
                    item.unlink()
                except OSError:
                    pass
        if progress:
            progress(100)
        return asset
    finally:
        if temporary_path and temporary_path.exists():
            try:
                temporary_path.unlink()
            except OSError:
                pass


def load_cached_avatar(cache_dir: str | Path = AVATAR_CACHE_DIR) -> AvatarAsset | None:
    metadata_path = Path(cache_dir) / "current.json"
    if not metadata_path.exists():
        return None
    try:
        raw = json.loads(metadata_path.read_text(encoding="utf-8"))
        asset = AvatarAsset(**raw)
        path = Path(asset.path)
        if not path.is_file() or path.parent.resolve() != Path(cache_dir).resolve():
            return None
        blob = path.read_bytes()
        if len(blob) != asset.bytes or hashlib.sha256(blob).hexdigest() != asset.sha256:
            return None
        image_format, width, height, frames = _inspect_image(blob)
        if (image_format, width, height, frames) != (
                asset.format, asset.width, asset.height, asset.frames):
            return None
        return asset
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None


def clear_cached_avatar(cache_dir: str | Path = AVATAR_CACHE_DIR) -> None:
    cache = Path(cache_dir)
    if not cache.exists():
        return
    for item in cache.iterdir():
        if item.is_file():
            try:
                item.unlink()
            except OSError:
                pass


def decode_avatar(asset: AvatarAsset, target_size: int = 220) -> DecodedAvatar:
    """Decode and downscale frames for Tk on the PC, preserving GIF timing."""
    target_size = max(64, min(512, int(target_size)))
    frames: list[Image.Image] = []
    durations: list[int] = []
    with Image.open(asset.path) as source:
        for frame in ImageSequence.Iterator(source):
            rgba = frame.convert("RGBA")
            rgba.thumbnail((target_size, target_size), Image.Resampling.LANCZOS)
            frames.append(rgba.copy())
            duration = int(frame.info.get("duration", source.info.get("duration", 100)) or 100)
            durations.append(max(33, min(2000, duration)))
            if len(frames) >= MAX_FRAMES:
                break
    if not frames:
        raise ValueError("形象没有可显示的帧")
    if len(frames) == 1:
        durations[0] = 1000
    return DecodedAvatar(asset, frames, durations)
