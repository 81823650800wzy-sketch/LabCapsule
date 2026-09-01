"""Private GitHub role-card bundles shared by Studio and Android."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import http.client
import json
from pathlib import Path
import re
import shutil
import ssl
import tempfile
from typing import Callable
from urllib import error, parse, request
import zipfile

from PIL import Image

from memory_repo import BRANCH_PATTERN, REPO_PATTERN
from pet_packages import PetPackage


ROLE_TAG = "labcapsule-rolecards-v1"
MAX_BUNDLE = 256 * 1024 * 1024
MAX_UNPACKED = 220 * 1024 * 1024
MAX_ENTRIES = 1200
ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,80}$")


@dataclass(frozen=True)
class RoleCardRemote:
    repository: str
    token: str
    branch: str = "main"

    def validate(self):
        if not REPO_PATTERN.fullmatch(self.repository.strip()):
            raise ValueError("角色卡仓库必须是 owner/repository")
        if not BRANCH_PATTERN.fullmatch(self.branch.strip()) or ".." in self.branch:
            raise ValueError("角色卡仓库分支无效")
        if not self.token.strip():
            raise ValueError("角色卡仓库 Token 不能为空")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _preview(path: Path) -> bytes:
    if not path.is_file() or path.stat().st_size > 32 * 1024 * 1024:
        raise ValueError("静态预览不存在或超过 32 MiB")
    with Image.open(path) as source:
        image = source.convert("RGB")
        image.thumbnail((180, 240), Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (180, 240), "#0c0c0c")
        canvas.paste(image, ((180 - image.width) // 2, (240 - image.height) // 2))
        with tempfile.SpooledTemporaryFile(max_size=512 * 1024) as output:
            canvas.save(output, format="JPEG", quality=84, optimize=True)
            output.seek(0)
            value = output.read()
    if len(value) > 512 * 1024:
        raise ValueError("静态预览压缩后超过 512 KiB")
    return value


def build_role_card(package: PetPackage, persona: str, preview_path: str | Path,
                    voice_path: str | Path | None, output_path: str | Path) -> dict:
    if package.visual_kind != "live2d":
        raise ValueError("V1.2 双端角色卡当前要求 Live2D 形象")
    role_id = package.package_id
    if not ID_PATTERN.fullmatch(role_id):
        raise ValueError("角色卡 id 无效")
    root = Path(package.folder).resolve()
    model = Path(package.live2d_model_path).resolve()
    try:
        model_relative = model.relative_to(root).as_posix()
    except ValueError as failure:
        raise ValueError("Live2D 模型必须位于角色包目录") from failure
    preview = _preview(Path(preview_path).expanduser().resolve())
    voice = Path(voice_path).expanduser().resolve() if voice_path else None
    if voice and (not voice.is_file() or voice.stat().st_size > 128 * 1024 * 1024):
        raise ValueError("语音包不存在或超过 128 MiB")
    output = Path(output_path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".tmp")
    manifest = {
        "schemaVersion": 1, "id": role_id, "name": package.name[:80],
        "characterId": role_id, "persona": persona.strip()[:4000],
        "live2dModel": "live2d/" + model_relative, "previewFile": "preview.jpg",
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    if not manifest["persona"]:
        raise ValueError("角色卡人设不能为空")
    if voice:
        manifest["voiceFile"] = "voice/" + re.sub(r"[^A-Za-z0-9._-]", "_", voice.name)[:100]
    entries = 0
    unpacked = len(preview)
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            archive.writestr("rolecard.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            archive.writestr("preview.jpg", preview)
            for path in sorted(root.rglob("*")):
                if not path.is_file():
                    continue
                if path.is_symlink():
                    raise ValueError("角色包不能包含符号链接")
                entries += 1
                unpacked += path.stat().st_size
                if entries > MAX_ENTRIES or unpacked > MAX_UNPACKED:
                    raise ValueError("角色卡文件数量或解压大小超过限制")
                archive.write(path, "live2d/" + path.relative_to(root).as_posix())
            if voice:
                unpacked += voice.stat().st_size
                if unpacked > MAX_UNPACKED:
                    raise ValueError("角色卡解压大小超过限制")
                archive.write(voice, manifest["voiceFile"])
        if temporary.stat().st_size > MAX_BUNDLE:
            raise ValueError("角色卡压缩包超过 256 MiB")
        temporary.replace(output)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    digest = _sha256(output)
    return {"id": role_id, "name": package.name[:80], "characterId": role_id,
            "sha256": digest, "size": output.stat().st_size,
            "updatedAt": datetime.now(timezone.utc).isoformat(),
            "hasVoice": bool(voice),
            "previewBase64": base64.b64encode(preview).decode("ascii")}


def read_role_manifest(bundle_path: str | Path) -> dict:
    path = Path(bundle_path)
    if not path.is_file() or path.stat().st_size > MAX_BUNDLE:
        raise ValueError("角色卡文件不存在或过大")
    with zipfile.ZipFile(path) as archive:
        try:
            info = archive.getinfo("rolecard.json")
        except KeyError as failure:
            raise ValueError("角色卡缺少 rolecard.json") from failure
        if info.file_size > 64 * 1024:
            raise ValueError("角色卡清单过大")
        manifest = json.loads(archive.read(info).decode("utf-8"))
    if (not isinstance(manifest, dict) or manifest.get("schemaVersion") != 1 or
            not ID_PATTERN.fullmatch(str(manifest.get("id", "")))):
        raise ValueError("角色卡清单无效")
    return manifest


def apply_role_card(bundle_path: str | Path, destination: str | Path,
                    replace_visual: bool = True, replace_persona: bool = True,
                    replace_voice: bool = True) -> dict:
    if not any((replace_visual, replace_persona, replace_voice)):
        raise ValueError("至少选择一个替换项")
    bundle = Path(bundle_path).resolve()
    manifest = read_role_manifest(bundle)
    root = Path(destination).expanduser().resolve()
    temporary = root.with_name(root.name + ".tmp")
    backup = root.with_name(root.name + ".backup")
    shutil.rmtree(temporary, ignore_errors=True)
    temporary.mkdir(parents=True)
    total = 0
    try:
        with zipfile.ZipFile(bundle) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_ENTRIES + 10:
                raise ValueError("角色卡文件数量过多")
            prefixes = []
            if replace_visual:
                prefixes.append("live2d/")
            if replace_voice:
                prefixes.append("voice/")
            for info in infos:
                if not any(info.filename.startswith(prefix) for prefix in prefixes):
                    continue
                relative = info.filename.split("/", 1)[1] if "/" in info.filename else ""
                if not relative:
                    continue
                target_base = temporary / ("voice" if info.filename.startswith("voice/") else "")
                target = (target_base / relative).resolve()
                try:
                    target.relative_to(temporary)
                except ValueError as failure:
                    raise ValueError("角色卡包含越界路径") from failure
                total += info.file_size
                if total > MAX_UNPACKED:
                    raise ValueError("角色卡解压后过大")
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(info) as source, target.open("wb") as sink:
                        shutil.copyfileobj(source, sink, 64 * 1024)
            if replace_persona:
                (temporary / "persona.txt").write_text(str(manifest.get("persona", ""))[:4000],
                                                        encoding="utf-8")
            preview = archive.read("preview.jpg")
            (temporary / "preview.jpg").write_bytes(preview)
        model_entry = str(manifest.get("live2dModel", ""))
        if replace_visual:
            if not model_entry.startswith("live2d/") or not model_entry.endswith(".model3.json"):
                raise ValueError("角色卡 Live2D 入口无效")
            model_relative = model_entry[len("live2d/"):]
            if not (temporary / model_relative).is_file():
                raise ValueError("角色卡缺少 model3.json")
            pet = {"schemaVersion": 1, "id": str(manifest["id"]).lower()[:64],
                   "name": str(manifest.get("name", "角色"))[:24],
                   "live2dModel": model_relative, "personaFile": "persona.txt",
                   "greeting": "链路就绪。今天想观察什么现象？"}
            (temporary / "pet.json").write_text(json.dumps(pet, ensure_ascii=False, indent=2),
                                                 encoding="utf-8")
        shutil.rmtree(backup, ignore_errors=True)
        if root.exists():
            root.replace(backup)
        temporary.replace(root)
        shutil.rmtree(backup, ignore_errors=True)
        return manifest
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        if not root.exists() and backup.exists():
            backup.replace(root)
        raise


class GitHubRoleCardClient:
    def __init__(self, remote: RoleCardRemote, opener: Callable = request.urlopen):
        remote.validate()
        self.remote = remote
        self.opener = opener
        self.api = "https://api.github.com/repos/" + remote.repository

    def _call(self, method: str, path: str, body: dict | None = None) -> dict:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        call = request.Request(self.api + path, data=data, method=method,
                               headers={"Accept": "application/vnd.github+json",
                                        "Authorization": "Bearer " + self.remote.token,
                                        "X-GitHub-Api-Version": "2022-11-28",
                                        "User-Agent": "LabCapsule-Studio/1.2"})
        with self.opener(call, timeout=60) as response:
            payload = response.read(2 * 1024 * 1024)
        return json.loads(payload.decode("utf-8")) if payload else {}

    def require_private_repository(self):
        if self._call("GET", "").get("private") is not True:
            raise ValueError("角色卡同步只允许使用私有 GitHub 仓库")

    def pull_catalog(self) -> tuple[dict, str]:
        path = "/contents/rolecards/index.json?ref=" + parse.quote(self.remote.branch, safe="")
        try:
            wrapper = self._call("GET", path)
        except error.HTTPError as failure:
            if failure.code == 404:
                return {"schemaVersion": 1, "cards": []}, ""
            raise
        raw = base64.b64decode(str(wrapper.get("content", "")), validate=True)
        if len(raw) > 1024 * 1024:
            raise ValueError("角色卡索引超过 1 MiB")
        catalog = json.loads(raw.decode("utf-8"))
        if catalog.get("schemaVersion") != 1 or not isinstance(catalog.get("cards"), list):
            raise ValueError("角色卡索引格式无效")
        return catalog, str(wrapper.get("sha", ""))

    def push_catalog(self, catalog: dict, sha: str = ""):
        content = base64.b64encode(json.dumps(catalog, ensure_ascii=False, indent=2)
                                   .encode("utf-8")).decode("ascii")
        body = {"message": "rolecards: update catalog", "content": content,
                "branch": self.remote.branch}
        if sha:
            body["sha"] = sha
        self._call("PUT", "/contents/rolecards/index.json", body)

    def ensure_release(self) -> dict:
        try:
            return self._call("GET", "/releases/tags/" + ROLE_TAG)
        except error.HTTPError as failure:
            if failure.code != 404:
                raise
        return self._call("POST", "/releases", {
            "tag_name": ROLE_TAG, "target_commitish": self.remote.branch,
            "name": "LabCapsule 私有角色卡",
            "body": "由 LabCapsule 双端管理的私有角色卡资产，请勿公开。",
            "draft": False, "prerelease": True})

    def upload_asset(self, release: dict, asset_name: str, bundle: Path,
                     progress: Callable[[int], None] | None = None) -> int:
        for old in release.get("assets", []):
            if old.get("name") == asset_name:
                self._call("DELETE", f"/releases/assets/{int(old['id'])}")
        path = f"/repos/{self.remote.repository}/releases/{int(release['id'])}/assets?name=" + \
               parse.quote(asset_name, safe="")
        connection = http.client.HTTPSConnection("uploads.github.com", timeout=120,
                                                 context=ssl.create_default_context())
        headers = {"Authorization": "Bearer " + self.remote.token,
                   "Accept": "application/vnd.github+json", "Content-Type": "application/zip",
                   "Content-Length": str(bundle.stat().st_size),
                   "User-Agent": "LabCapsule-Studio/1.2"}
        connection.putrequest("POST", path)
        for key, value in headers.items():
            connection.putheader(key, value)
        connection.endheaders()
        sent, size = 0, bundle.stat().st_size
        with bundle.open("rb") as source:
            for chunk in iter(lambda: source.read(64 * 1024), b""):
                connection.send(chunk)
                sent += len(chunk)
                if progress:
                    progress(min(100, sent * 100 // max(1, size)))
        response = connection.getresponse()
        payload = response.read(2 * 1024 * 1024)
        connection.close()
        if not 200 <= response.status < 300:
            raise RuntimeError(f"角色卡资产上传 HTTP {response.status}")
        return int(json.loads(payload.decode("utf-8"))["id"])

    def publish(self, bundle: Path, item: dict,
                progress: Callable[[int], None] | None = None) -> dict:
        self.require_private_repository()
        catalog, catalog_sha = self.pull_catalog()
        release = self.ensure_release()
        asset_name = f"{item['id']}-{item['sha256'][:12]}.zip"
        item = dict(item)
        item.update(assetId=self.upload_asset(release, asset_name, bundle, progress),
                    assetName=asset_name)
        cards = [item] + [value for value in catalog["cards"]
                          if value.get("id") != item["id"]][:29]
        catalog = {"schemaVersion": 1, "updatedAt": datetime.now(timezone.utc).isoformat(),
                   "cards": cards}
        self.push_catalog(catalog, catalog_sha)
        return catalog

    def download(self, item: dict, target: Path,
                 progress: Callable[[int], None] | None = None) -> Path:
        size, asset_id = int(item.get("size", 0)), int(item.get("assetId", 0))
        digest = str(item.get("sha256", ""))
        if not 0 < size <= MAX_BUNDLE or not asset_id or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("角色卡索引项无效")
        call = request.Request(f"{self.api}/releases/assets/{asset_id}",
                               headers={"Accept": "application/octet-stream",
                                        "Authorization": "Bearer " + self.remote.token,
                                        "User-Agent": "LabCapsule-Studio/1.2"})
        temporary = target.with_suffix(".tmp")
        received = 0
        try:
            with self.opener(call, timeout=120) as response, temporary.open("wb") as output:
                while True:
                    chunk = response.read(64 * 1024)
                    if not chunk:
                        break
                    received += len(chunk)
                    if received > MAX_BUNDLE:
                        raise ValueError("角色卡下载超过 256 MiB")
                    output.write(chunk)
                    if progress:
                        progress(min(100, received * 100 // max(1, size)))
            if _sha256(temporary) != digest:
                raise ValueError("角色卡 SHA-256 校验失败")
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary.replace(target)
            return target
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
