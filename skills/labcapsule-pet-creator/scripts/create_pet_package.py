#!/usr/bin/env python3
"""Create or validate a portable LabCapsule Pet Package V1."""

from __future__ import annotations

import argparse
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile

from PIL import Image, UnidentifiedImageError


MAX_BYTES = 12 * 1024 * 1024
MAX_DIMENSION = 2048
MAX_PIXELS = 4_194_304
MAX_FRAMES = 120
MAX_TOTAL_PIXELS = 180_000_000
MAX_TEXT_BYTES = 16 * 1024
MAX_MODEL_JSON_BYTES = 1024 * 1024
MAX_MOC_BYTES = 64 * 1024 * 1024
MAX_TEXTURE_BYTES = 32 * 1024 * 1024
MAX_AUX_JSON_BYTES = 8 * 1024 * 1024
MAX_TEXTURES = 16
MAX_MOTIONS = 256
MAX_TEXTURE_DIMENSION = 8192
FORMATS = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp", "GIF": ".gif"}
PACKAGE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
SCHEMA_URL = (
    "https://raw.githubusercontent.com/81823650800wzy-sketch/LabCapsule/"
    "main/docs/pet_package_v1.schema.json"
)


def validate_create_metadata(args: argparse.Namespace) -> None:
    if not PACKAGE_ID.fullmatch(args.id):
        raise ValueError("id 格式无效；请使用小写字母、数字、点、下划线或连字符")
    if not args.name.strip() or len(args.name.strip()) > 24:
        raise ValueError("name 必须为 1–24 个字符")
    if len(args.greeting) > 160:
        raise ValueError("greeting 超过 160 个字符")


def inspect_image(path: Path) -> dict:
    if not path.is_file():
        raise ValueError(f"形象文件不存在：{path}")
    size = path.stat().st_size
    if size < 1 or size > MAX_BYTES:
        raise ValueError("形象文件必须大于 0 且不超过 12 MiB")
    blob = path.read_bytes()
    try:
        with Image.open(BytesIO(blob)) as image:
            image_format = (image.format or "").upper()
            if image_format not in FORMATS:
                raise ValueError("形象只支持 PNG、JPG、WebP 或 GIF")
            width, height = image.size
            frames = int(getattr(image, "n_frames", 1))
            if (width < 1 or height < 1 or width > MAX_DIMENSION or height > MAX_DIMENSION
                    or width * height > MAX_PIXELS):
                raise ValueError("形象尺寸超过 2048×2048 / 4,194,304 像素限制")
            if frames < 1 or frames > MAX_FRAMES or width * height * frames > MAX_TOTAL_PIXELS:
                raise ValueError("动画帧数或总解码量超过限制")
            image.seek(0)
            image.load()
    except (UnidentifiedImageError, OSError) as error:
        raise ValueError(f"形象无法解码：{error}") from error
    return {
        "format": image_format, "width": width, "height": height, "frames": frames,
        "bytes": size, "sha256": hashlib.sha256(blob).hexdigest(),
    }


def contained_file(folder: Path, value: str, label: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} 不能为空")
    path = (folder / value).resolve()
    try:
        path.relative_to(folder.resolve())
    except ValueError as error:
        raise ValueError(f"{label} 不能位于角色包之外") from error
    if not path.is_file():
        raise ValueError(f"{label} 不存在：{value}")
    return path


def read_json(path: Path, label: str, max_bytes: int) -> dict:
    if not path.is_file() or path.stat().st_size < 1 or path.stat().st_size > max_bytes:
        raise ValueError(f"{label} 不存在、为空或过大")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} 不是有效 UTF-8 JSON：{error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} 根节点必须是对象")
    return value


def live2d_reference(folder: Path, value: object, label: str, max_bytes: int) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} 不能为空")
    path = contained_file(folder, value, label)
    size = path.stat().st_size
    if size < 1 or size > max_bytes:
        raise ValueError(f"{label} 为空或超过大小限制")
    return path


def inspect_live2d(path_value: str | Path) -> dict:
    model_path = Path(path_value).expanduser().resolve()
    if not model_path.is_file() or not model_path.name.lower().endswith(".model3.json"):
        raise ValueError("Live2D 主文件必须是存在的 .model3.json")
    model = read_json(model_path, "model3.json", MAX_MODEL_JSON_BYTES)
    if model.get("Version") != 3:
        raise ValueError("当前只支持 Version=3 的 Cubism model3.json")
    references = model.get("FileReferences")
    if not isinstance(references, dict):
        raise ValueError("model3.json 缺少 FileReferences")
    folder = model_path.parent
    files: list[Path] = [model_path]
    moc = live2d_reference(folder, references.get("Moc"), "Moc", MAX_MOC_BYTES)
    files.append(moc)
    textures = references.get("Textures")
    if not isinstance(textures, list) or not 1 <= len(textures) <= MAX_TEXTURES:
        raise ValueError(f"Textures 必须包含 1–{MAX_TEXTURES} 个纹理")
    for index, value in enumerate(textures):
        texture = live2d_reference(folder, value, f"Textures[{index}]", MAX_TEXTURE_BYTES)
        try:
            with Image.open(texture) as image:
                if image.format != "PNG":
                    raise ValueError(f"Textures[{index}] 必须是 PNG")
                width, height = image.size
                if (width < 1 or height < 1 or width > MAX_TEXTURE_DIMENSION
                        or height > MAX_TEXTURE_DIMENSION):
                    raise ValueError(f"Textures[{index}] 尺寸超过 {MAX_TEXTURE_DIMENSION}×"
                                     f"{MAX_TEXTURE_DIMENSION}")
                image.verify()
        except (UnidentifiedImageError, OSError) as error:
            raise ValueError(f"Textures[{index}] 无法解码：{error}") from error
        files.append(texture)
    for key in ("Physics", "Pose", "DisplayInfo", "UserData"):
        if references.get(key):
            target = live2d_reference(folder, references[key], key, MAX_AUX_JSON_BYTES)
            read_json(target, key, MAX_AUX_JSON_BYTES)
            files.append(target)
    expressions = references.get("Expressions", [])
    if not isinstance(expressions, list):
        raise ValueError("Expressions 必须是数组")
    for index, entry in enumerate(expressions):
        if not isinstance(entry, dict):
            raise ValueError(f"Expressions[{index}] 必须是对象")
        target = live2d_reference(folder, entry.get("File"),
                                  f"Expressions[{index}]", MAX_AUX_JSON_BYTES)
        read_json(target, f"Expressions[{index}]", MAX_AUX_JSON_BYTES)
        files.append(target)
    motions = references.get("Motions", {})
    if not isinstance(motions, dict):
        raise ValueError("Motions 必须是对象")
    motion_count = 0
    motion_groups: list[str] = []
    for group, entries in motions.items():
        if not isinstance(group, str) or not isinstance(entries, list):
            raise ValueError("每个动作组必须是数组")
        if entries:
            motion_groups.append(group)
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError(f"动作组 {group} 含无效条目")
            motion = live2d_reference(folder, entry.get("File"),
                                      f"Motions.{group}", MAX_AUX_JSON_BYTES)
            read_json(motion, f"Motions.{group}", MAX_AUX_JSON_BYTES)
            files.append(motion)
            if entry.get("Sound"):
                files.append(live2d_reference(folder, entry["Sound"],
                                              f"Motions.{group}.Sound", MAX_TEXTURE_BYTES))
            motion_count += 1
            if motion_count > MAX_MOTIONS:
                raise ValueError(f"动作数量超过 {MAX_MOTIONS}")
    unique_files = tuple(dict.fromkeys(path.resolve() for path in files))
    return {
        "model_path": str(model_path), "model_name": model_path.name,
        "motion_count": motion_count, "motion_groups": motion_groups,
        "files": unique_files, "root": folder,
    }


def validate(folder_value: str | Path) -> dict:
    folder = Path(folder_value).expanduser().resolve()
    manifest_path = folder / "pet.json"
    if not manifest_path.is_file() or manifest_path.stat().st_size > 64 * 1024:
        raise ValueError("缺少 pet.json，或清单超过 64 KiB")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"pet.json 不是有效 UTF-8 JSON：{error}") from error
    if not isinstance(manifest, dict) or manifest.get("schemaVersion") != 1:
        raise ValueError("pet.json 根节点必须是对象，schemaVersion 必须为 1")
    package_id = str(manifest.get("id", ""))
    if not PACKAGE_ID.fullmatch(package_id):
        raise ValueError("id 格式无效")
    name = str(manifest.get("name", "")).strip()
    if not name or len(name) > 24:
        raise ValueError("name 必须为 1–24 个字符")
    avatar_value = manifest.get("avatar")
    live2d_value = manifest.get("live2dModel")
    if bool(avatar_value) == bool(live2d_value):
        raise ValueError("pet.json 必须且只能指定 avatar 或 live2dModel")
    image: dict = {}
    visual: dict
    if avatar_value:
        avatar = contained_file(folder, avatar_value, "avatar")
        image = inspect_image(avatar)
        visual = {"visualKind": "raster", "avatar": str(avatar.relative_to(folder))}
    else:
        model = contained_file(folder, live2d_value, "live2dModel")
        live2d = inspect_live2d(model)
        visual = {
            "visualKind": "live2d",
            "live2dModel": str(model.relative_to(folder)),
            "motionCount": live2d["motion_count"],
            "motionGroups": live2d["motion_groups"],
        }
    persona_file = manifest.get("personaFile")
    if persona_file:
        persona = contained_file(folder, persona_file, "personaFile")
        if persona.stat().st_size > MAX_TEXT_BYTES:
            raise ValueError("personaFile 超过 16 KiB")
        persona.read_text(encoding="utf-8")
    if len(str(manifest.get("greeting", ""))) > 160:
        raise ValueError("greeting 超过 160 个字符")
    return {"valid": True, "folder": str(folder), "id": package_id, "name": name,
            **visual, **image}


def write_package_metadata(output: Path, args: argparse.Namespace,
                           visual_key: str, visual_value: str) -> None:
    persona_text = ""
    if args.persona_file:
        persona_source = Path(args.persona_file).expanduser().resolve()
        if not persona_source.is_file() or persona_source.stat().st_size > MAX_TEXT_BYTES:
            raise ValueError("persona 文件不存在或超过 16 KiB")
        persona_text = persona_source.read_text(encoding="utf-8").strip()
    elif args.persona:
        persona_text = args.persona.strip()
    if not persona_text:
        persona_text = (
            f"你是名为“{args.name}”的 LabCapsule 数字实验伙伴。保持友善、严谨，"
            "不编造传感器数据，也不未经确认操作实验或设备。"
        )
    (output / "persona.txt").write_text(persona_text[:2400] + "\n", encoding="utf-8")
    manifest = {
        "$schema": SCHEMA_URL, "schemaVersion": 1, "id": args.id,
        "name": args.name.strip(), visual_key: visual_value,
        "personaFile": "persona.txt", "greeting": args.greeting,
        "author": args.author, "license": args.license, "homepage": args.homepage,
    }
    (output / "pet.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def create(args: argparse.Namespace) -> dict:
    validate_create_metadata(args)
    source = Path(args.source).expanduser().resolve()
    image = inspect_image(source)
    output = Path(args.output).expanduser().resolve()
    if output.exists():
        if not output.is_dir():
            raise ValueError("输出路径已存在且不是文件夹")
        if any(output.iterdir()):
            raise ValueError("输出目录已存在且非空；为避免覆盖，请选择新的目录")
    output.mkdir(parents=True, exist_ok=True)
    suffix = FORMATS[image["format"]]
    avatar_name = "avatar" + suffix
    target = output / avatar_name
    if source != target:
        shutil.copy2(source, target)
    write_package_metadata(output, args, "avatar", avatar_name)
    return validate(output)


def create_live2d(args: argparse.Namespace) -> dict:
    validate_create_metadata(args)
    source_model = Path(args.model).expanduser().resolve()
    asset = inspect_live2d(source_model)
    output = Path(args.output).expanduser().resolve()
    if output.exists():
        if not output.is_dir():
            raise ValueError("输出路径已存在且不是文件夹")
        if any(output.iterdir()):
            raise ValueError("输出目录已存在且非空；为避免覆盖，请选择新的目录")
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=output.parent))
    try:
        runtime = stage / "live2d"
        source_root: Path = asset["root"]
        for source in asset["files"]:
            relative = source.relative_to(source_root)
            target = runtime / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        model_relative = Path("live2d") / source_model.relative_to(source_root)
        write_package_metadata(stage, args, "live2dModel", model_relative.as_posix())
        result = validate(stage)
        if output.exists():
            output.rmdir()
        stage.replace(output)
        result["folder"] = str(output)
        return result
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Create or validate LabCapsule Pet Package V1")
    commands = root.add_subparsers(dest="command", required=True)
    def add_metadata(command):
        command.add_argument("--output", required=True)
        command.add_argument("--id", required=True)
        command.add_argument("--name", required=True)
        command.add_argument("--persona")
        command.add_argument("--persona-file")
        command.add_argument("--greeting", default="链路就绪。今天想观察什么现象？")
        command.add_argument("--author", default="")
        command.add_argument("--license", default="")
        command.add_argument("--homepage", default="")

    make = commands.add_parser("create", help="create a package from one image or GIF")
    make.add_argument("--source", required=True)
    add_metadata(make)
    live2d = commands.add_parser(
        "create-live2d", help="copy one model3 runtime dependency graph into a package")
    live2d.add_argument("--model", required=True)
    add_metadata(live2d)
    check = commands.add_parser("validate", help="validate an existing package")
    check.add_argument("folder")
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "create":
            result = create(args)
        elif args.command == "create-live2d":
            result = create_live2d(args)
        else:
            result = validate(args.folder)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
