"""Safe discovery and structural validation for Live2D Cubism runtime models."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from PIL import Image, UnidentifiedImageError


MAX_MODEL_JSON_BYTES = 1024 * 1024
MAX_MOC_BYTES = 64 * 1024 * 1024
MAX_TEXTURE_BYTES = 32 * 1024 * 1024
MAX_AUX_JSON_BYTES = 8 * 1024 * 1024
MAX_TEXTURES = 16
MAX_MOTIONS = 256
MAX_TEXTURE_DIMENSION = 8192


@dataclass(frozen=True)
class Live2DAsset:
    model_path: str
    name: str
    moc_path: str
    texture_paths: tuple[str, ...]
    physics_path: str = ""
    pose_path: str = ""
    display_info_path: str = ""
    motion_paths: tuple[str, ...] = ()
    motion_groups: tuple[str, ...] = ()

    @property
    def motion_count(self) -> int:
        return len(self.motion_paths)


def _contained_file(folder: Path, value: object, label: str, max_bytes: int) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} 不能为空")
    candidate = (folder / value).resolve()
    try:
        candidate.relative_to(folder.resolve())
    except ValueError as error:
        raise ValueError(f"{label} 不能位于 model3 文件夹之外") from error
    if not candidate.is_file():
        raise ValueError(f"{label} 不存在：{value}")
    size = candidate.stat().st_size
    if size < 1 or size > max_bytes:
        raise ValueError(f"{label} 大小无效或超过 {max_bytes // (1024 * 1024) or 1} MiB")
    return candidate


def _read_json(path: Path, label: str, max_bytes: int) -> dict:
    if path.stat().st_size > max_bytes:
        raise ValueError(f"{label} 过大")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} 不是有效 UTF-8 JSON：{error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} 根节点必须是对象")
    return value


def inspect_live2d_model(path_value: str | Path) -> Live2DAsset:
    model_path = Path(path_value).expanduser().resolve()
    if not model_path.is_file() or not model_path.name.lower().endswith(".model3.json"):
        raise ValueError("Live2D 主文件必须是存在的 .model3.json")
    model = _read_json(model_path, "model3.json", MAX_MODEL_JSON_BYTES)
    if model.get("Version") != 3:
        raise ValueError("当前只支持 Version=3 的 Cubism model3.json")
    references = model.get("FileReferences")
    if not isinstance(references, dict):
        raise ValueError("model3.json 缺少 FileReferences")
    folder = model_path.parent
    moc = _contained_file(folder, references.get("Moc"), "Moc", MAX_MOC_BYTES)
    textures = references.get("Textures")
    if not isinstance(textures, list) or not 1 <= len(textures) <= MAX_TEXTURES:
        raise ValueError(f"Textures 必须包含 1–{MAX_TEXTURES} 个纹理")
    texture_paths: list[str] = []
    for index, value in enumerate(textures):
        texture = _contained_file(folder, value, f"Textures[{index}]", MAX_TEXTURE_BYTES)
        try:
            with Image.open(texture) as image:
                if image.format != "PNG":
                    raise ValueError(f"Textures[{index}] 必须是 PNG")
                width, height = image.size
                if (width < 1 or height < 1 or width > MAX_TEXTURE_DIMENSION
                        or height > MAX_TEXTURE_DIMENSION):
                    raise ValueError(f"Textures[{index}] 尺寸超过 {MAX_TEXTURE_DIMENSION}×{MAX_TEXTURE_DIMENSION}")
                image.verify()
        except (UnidentifiedImageError, OSError) as error:
            raise ValueError(f"Textures[{index}] 无法解码：{error}") from error
        texture_paths.append(str(texture))

    auxiliary: dict[str, str] = {}
    for key, label in (("Physics", "Physics"), ("Pose", "Pose"),
                       ("DisplayInfo", "DisplayInfo")):
        if references.get(key):
            target = _contained_file(folder, references[key], label, MAX_AUX_JSON_BYTES)
            _read_json(target, label, MAX_AUX_JSON_BYTES)
            auxiliary[key] = str(target)

    motions = references.get("Motions", {})
    if not isinstance(motions, dict):
        raise ValueError("Motions 必须是对象")
    motion_paths: list[str] = []
    motion_groups: list[str] = []
    for group, entries in motions.items():
        if not isinstance(group, str) or not isinstance(entries, list):
            raise ValueError("每个动作组必须是数组")
        if entries:
            motion_groups.append(group)
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError(f"动作组 {group} 含无效条目")
            motion = _contained_file(folder, entry.get("File"),
                                     f"Motions.{group}", MAX_AUX_JSON_BYTES)
            _read_json(motion, f"Motions.{group}", MAX_AUX_JSON_BYTES)
            motion_paths.append(str(motion))
            if len(motion_paths) > MAX_MOTIONS:
                raise ValueError(f"动作数量超过 {MAX_MOTIONS}")

    name = model_path.name[:-len(".model3.json")]
    return Live2DAsset(
        model_path=str(model_path), name=name, moc_path=str(moc),
        texture_paths=tuple(texture_paths), physics_path=auxiliary.get("Physics", ""),
        pose_path=auxiliary.get("Pose", ""),
        display_info_path=auxiliary.get("DisplayInfo", ""),
        motion_paths=tuple(motion_paths), motion_groups=tuple(motion_groups),
    )


def find_live2d_models(folder_value: str | Path, max_depth: int = 3,
                       max_results: int = 16) -> list[Path]:
    """Find model3.json files without following links or walking arbitrary depth."""
    root = Path(folder_value).expanduser().resolve()
    if not root.is_dir():
        return []
    results: list[Path] = []
    pending: list[tuple[Path, int]] = [(root, 0)]
    while pending:
        folder, depth = pending.pop(0)
        try:
            entries = sorted(folder.iterdir(), key=lambda item: item.name.lower())
        except OSError:
            continue
        for entry in entries:
            if entry.is_file() and entry.name.lower().endswith(".model3.json"):
                results.append(entry.resolve())
                if len(results) > max_results:
                    raise ValueError(f"Live2D 模型超过 {max_results} 个；请缩小所选文件夹")
            elif depth < max_depth and entry.is_dir() and not entry.is_symlink():
                pending.append((entry, depth + 1))
    return results
