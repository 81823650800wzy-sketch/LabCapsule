"""Unified LabCapsule pet-package discovery and selection persistence."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re

from avatar_assets import AvatarAsset, inspect_local_avatar
from live2d_models import find_live2d_models, inspect_live2d_model


APP_DIR = Path(os.environ.get("APPDATA", Path.home())) / "LabCapsule"
PET_SELECTION_PATH = APP_DIR / "selected_pet.json"
MANIFEST_NAME = "pet.json"
SUPPORTED_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
PACKAGE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
MAX_MANIFEST_BYTES = 64 * 1024
MAX_TEXT_BYTES = 16 * 1024


@dataclass(frozen=True)
class PetPackage:
    package_id: str
    name: str
    folder: str
    avatar_path: str
    persona: str
    greeting: str
    author: str = ""
    license: str = ""
    homepage: str = ""
    inferred: bool = False
    visual_kind: str = "raster"
    live2d_model_path: str = ""
    live2d_motion_count: int = 0

    @property
    def display_name(self) -> str:
        suffix = (f" · Live2D · {self.live2d_motion_count} 动作"
                  if self.visual_kind == "live2d" else "")
        if self.inferred:
            suffix += " · 自动识别"
        return f"{self.name} [{self.package_id}]{suffix}"

    @property
    def visual_source_path(self) -> str:
        return self.live2d_model_path if self.visual_kind == "live2d" else self.avatar_path


def _contained_file(folder: Path, value: str, label: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}不能为空")
    candidate = (folder / value).resolve()
    try:
        candidate.relative_to(folder.resolve())
    except ValueError as error:
        raise ValueError(f"{label}不能指向角色包文件夹之外") from error
    if not candidate.is_file():
        raise ValueError(f"{label}不存在：{value}")
    return candidate


def _read_text_file(folder: Path, value: str, label: str) -> str:
    path = _contained_file(folder, value, label)
    if path.stat().st_size > MAX_TEXT_BYTES:
        raise ValueError(f"{label}超过 {MAX_TEXT_BYTES // 1024} KiB 上限")
    try:
        return path.read_text(encoding="utf-8").strip()
    except UnicodeDecodeError as error:
        raise ValueError(f"{label}必须是 UTF-8 文本") from error


def _inferred_package(folder: Path) -> PetPackage:
    images = sorted(item for item in folder.iterdir()
                    if item.is_file() and item.suffix.lower() in SUPPORTED_SUFFIXES)
    model_files = find_live2d_models(folder)
    if images and model_files:
        raise ValueError(f"{folder} 同时包含图片和 Live2D；请添加 {MANIFEST_NAME} 指定主形象")
    if not images and not model_files:
        raise ValueError(f"{folder} 中没有 {MANIFEST_NAME} 或受支持的形象文件")
    if len(images) > 1:
        raise ValueError(f"{folder} 中有多个形象文件；请添加 {MANIFEST_NAME} 明确指定主形象")
    if len(model_files) > 1:
        raise ValueError(f"{folder} 中有多个 Live2D 模型；请选择更具体的文件夹")
    live2d = inspect_live2d_model(model_files[0]) if model_files else None
    if images:
        inspect_local_avatar(images[0])
    digest_source = model_files[0] if model_files else images[0]
    digest = hashlib.sha256(digest_source.read_bytes()).hexdigest()[:12]
    persona_path = folder / "persona.txt"
    greeting_path = folder / "greeting.txt"
    raw_name = folder.name[:24] or "本地桌宠"
    inferred_name = {
        "hiyori": "Hiyori",
        "hiyori-free": "Hiyori Free",
        "hiyori-pro": "Hiyori Pro",
    }.get(raw_name.lower().replace("_", "-"), raw_name)
    persona = (
        f"你是名为“{inferred_name}”的 LabCapsule 数字实验伙伴。"
        "保持友善、严谨，不编造传感器数据，也不未经确认操作实验或设备。"
    )
    greeting = "链路就绪。今天想观察什么现象？"
    if persona_path.is_file():
        persona = _read_text_file(folder, "persona.txt", "persona.txt")[:2400]
    if greeting_path.is_file():
        greeting = _read_text_file(folder, "greeting.txt", "greeting.txt")[:160]
    return PetPackage(
        package_id=f"{'live2d' if live2d else 'raster'}-{digest}",
        name=inferred_name,
        folder=str(folder.resolve()), avatar_path=str(images[0].resolve()) if images else "",
        persona=persona, greeting=greeting, inferred=True,
        visual_kind="live2d" if live2d else "raster",
        live2d_model_path=live2d.model_path if live2d else "",
        live2d_motion_count=live2d.motion_count if live2d else 0,
    )


def load_pet_package(folder: str | Path) -> PetPackage:
    root = Path(folder).expanduser().resolve()
    if not root.is_dir():
        raise ValueError("桌宠角色包文件夹不存在")
    manifest_path = root / MANIFEST_NAME
    if not manifest_path.is_file():
        return _inferred_package(root)
    if manifest_path.stat().st_size > MAX_MANIFEST_BYTES:
        raise ValueError("pet.json 过大")
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"pet.json 不是有效 UTF-8 JSON：{error}") from error
    if not isinstance(raw, dict):
        raise ValueError("pet.json 根节点必须是对象")
    if raw.get("schemaVersion") != 1:
        raise ValueError("pet.json schemaVersion 必须为 1")
    package_id = str(raw.get("id", "")).strip()
    if not PACKAGE_ID.fullmatch(package_id):
        raise ValueError("桌宠 id 只能使用小写字母、数字、点、下划线和连字符，最长 64 字符")
    name = str(raw.get("name", "")).strip()
    if not name or len(name) > 24:
        raise ValueError("桌宠 name 必须为 1–24 个字符")
    avatar_value = raw.get("avatar")
    live2d_value = raw.get("live2dModel")
    if bool(avatar_value) == bool(live2d_value):
        raise ValueError("pet.json 必须且只能指定 avatar 或 live2dModel")
    avatar: Path | None = None
    live2d = None
    if avatar_value:
        avatar = _contained_file(root, avatar_value, "avatar")
        if avatar.suffix.lower() not in SUPPORTED_SUFFIXES:
            raise ValueError("avatar 只支持 PNG、JPG、WebP 或 GIF")
        inspect_local_avatar(avatar)
    else:
        model_path = _contained_file(root, live2d_value, "live2dModel")
        live2d = inspect_live2d_model(model_path)
    persona = (
        f"你是名为“{name}”的 LabCapsule 数字实验伙伴。保持友善、严谨，"
        "不编造传感器数据，也不未经确认操作实验或设备。"
    )
    persona_file = raw.get("personaFile", "")
    if persona_file:
        persona = _read_text_file(root, persona_file, "personaFile")[:2400]
    greeting = str(raw.get("greeting", "链路就绪。今天想观察什么现象？")).strip()[:160]
    return PetPackage(
        package_id=package_id, name=name, folder=str(root),
        avatar_path=str(avatar) if avatar else "",
        persona=persona, greeting=greeting or "链路就绪。今天想观察什么现象？",
        author=str(raw.get("author", "")).strip()[:80],
        license=str(raw.get("license", "")).strip()[:120],
        homepage=str(raw.get("homepage", "")).strip()[:500],
        visual_kind="live2d" if live2d else "raster",
        live2d_model_path=live2d.model_path if live2d else "",
        live2d_motion_count=live2d.motion_count if live2d else 0,
    )


def discover_pet_packages(folder: str | Path) -> tuple[list[PetPackage], list[str]]:
    """Recognize one package folder or immediate child package folders."""
    root = Path(folder).expanduser().resolve()
    if not root.is_dir():
        return [], ["桌宠库文件夹不存在"]
    root_has_images = any(item.suffix.lower() in SUPPORTED_SUFFIXES
                          for item in root.iterdir() if item.is_file())
    root_has_models = bool(find_live2d_models(root, max_depth=0))
    candidates = [root] if ((root / MANIFEST_NAME).is_file() or root_has_images
                            or root_has_models) else [
        item for item in sorted(root.iterdir(), key=lambda item: item.name.lower()) if item.is_dir()
    ]
    packages: list[PetPackage] = []
    errors: list[str] = []
    seen_ids: set[str] = set()
    for candidate in candidates:
        try:
            package = load_pet_package(candidate)
            if package.package_id in seen_ids:
                raise ValueError(f"重复桌宠 id：{package.package_id}")
            seen_ids.add(package.package_id)
            packages.append(package)
        except ValueError as error:
            # Ignore ordinary unrelated directories, but report directories that look like packages.
            looks_like_package = ((candidate / MANIFEST_NAME).exists()
                                  or any(item.suffix.lower() in SUPPORTED_SUFFIXES
                                         for item in candidate.iterdir() if item.is_file())
                                  or bool(find_live2d_models(candidate)))
            if looks_like_package:
                errors.append(f"{candidate.name}: {error}")
    return packages, errors


def selected_pet_package(selection_path: str | Path = PET_SELECTION_PATH) -> PetPackage | None:
    path = Path(selection_path)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        package = load_pet_package(str(raw["folder"]))
        saved_id = str(raw.get("id", ""))
        if package.package_id != saved_id and not saved_id.startswith("local-"):
            return None
        if package.package_id != saved_id:
            # V0.x inferred packages used an absolute-path based ``local-*`` id.
            # Replace it with the model-content id so Windows, Android and the
            # physical display all address the same character on every host.
            save_selected_pet(package, path)
        return package
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None


def save_selected_pet(package: PetPackage,
                      selection_path: str | Path = PET_SELECTION_PATH) -> None:
    path = Path(selection_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"id": package.package_id, "folder": package.folder},
                                    ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def clear_selected_pet(selection_path: str | Path = PET_SELECTION_PATH) -> None:
    path = Path(selection_path)
    if path.exists():
        path.unlink()


def avatar_asset_for_package(package: PetPackage) -> AvatarAsset:
    if package.visual_kind == "live2d":
        raise ValueError(
            "已识别 Live2D 模型和动作；真实播放需要经许可的 Cubism Core 运行时")
    return inspect_local_avatar(package.avatar_path)
