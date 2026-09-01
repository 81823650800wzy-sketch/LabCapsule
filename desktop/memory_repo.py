"""Private GitHub-repository memory sync keyed by a stable LabCapsule device ID."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import re
from typing import Callable
from urllib import error, parse, request


REPO_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
DEVICE_PATTERN = re.compile(r"^lc-[0-9a-f]{12}$")
BRANCH_PATTERN = re.compile(r"^[A-Za-z0-9._/-]{1,120}$")
SECRET_PATTERN = re.compile(
    r"(?i)(\b(?:api[_ -]?key|token|secret|password|密码|密钥)\b\s*[:=：]?\s*|"
    r"\bauthorization\b\s*[:=：]?\s*bearer\s+|\bbearer\s+)([^\s,;，；]{4,})"
)


def redact(value: str) -> str:
    return SECRET_PATTERN.sub(lambda match: f"{match.group(1)}[已隐藏]", value)


@dataclass(frozen=True)
class MemoryRemote:
    repository: str
    token: str
    branch: str = "main"

    def validate(self) -> None:
        if not REPO_PATTERN.fullmatch(self.repository.strip()):
            raise ValueError("记忆仓库必须是 owner/repository")
        if not BRANCH_PATTERN.fullmatch(self.branch.strip()) or ".." in self.branch:
            raise ValueError("记忆仓库分支名称无效")
        if not self.token.strip():
            raise ValueError("记忆仓库 Token 不能为空")


def empty_snapshot(device_id: str, character_id: str = "") -> dict:
    if not DEVICE_PATTERN.fullmatch(device_id):
        raise ValueError("设备 ID 无效")
    return {"schemaVersion": 1, "deviceId": device_id, "revision": 0,
            "updatedAt": datetime.now(timezone.utc).isoformat(),
            "characterId": character_id[:64], "facts": [], "recentSessions": []}


def sanitize_snapshot(value: dict, expected_device_id: str) -> dict:
    if not isinstance(value, dict) or value.get("schemaVersion") != 1:
        raise ValueError("记忆快照格式无效")
    if value.get("deviceId") != expected_device_id or not DEVICE_PATTERN.fullmatch(expected_device_id):
        raise ValueError("记忆快照设备 ID 不匹配")
    facts: list[str] = []
    for item in value.get("facts", []):
        clean = redact(str(item).strip())[:240]
        if clean and clean not in facts:
            facts.append(clean)
    sessions: list[dict] = []
    for item in value.get("recentSessions", []):
        if not isinstance(item, dict):
            continue
        session_id = re.sub(r"[^A-Za-z0-9._:-]", "", str(item.get("id", "")))[:64]
        if not session_id:
            continue
        sessions.append({"id": session_id,
                         "name": redact(str(item.get("name", "未命名实验")))[:120],
                         "startedAt": str(item.get("startedAt", ""))[:40],
                         "sampleCount": max(0, int(item.get("sampleCount", 0))),
                         "summary": redact(str(item.get("summary", "")))[:600]})
    return {"schemaVersion": 1, "deviceId": expected_device_id,
            "revision": max(0, int(value.get("revision", 0))),
            "updatedAt": str(value.get("updatedAt", ""))[:40],
            "characterId": str(value.get("characterId", ""))[:64],
            "facts": facts[-80:], "recentSessions": sessions[-20:]}


def merge_snapshots(local: dict, remote: dict) -> dict:
    device_id = str(local.get("deviceId", ""))
    left = sanitize_snapshot(local, device_id)
    right = sanitize_snapshot(remote, device_id)
    if right["revision"] > left["revision"]:
        primary, secondary = right, left
    else:
        primary, secondary = left, right
    facts = list(primary["facts"])
    for fact in secondary["facts"]:
        if fact not in facts:
            facts.append(fact)
    session_map = {item["id"]: item for item in secondary["recentSessions"]}
    session_map.update({item["id"]: item for item in primary["recentSessions"]})
    sessions = sorted(session_map.values(), key=lambda item: item.get("startedAt", ""))[-20:]
    return {"schemaVersion": 1, "deviceId": device_id,
            "revision": max(left["revision"], right["revision"]) + 1,
            "updatedAt": datetime.now(timezone.utc).isoformat(),
            "characterId": primary.get("characterId") or secondary.get("characterId", ""),
            "facts": facts[-80:], "recentSessions": sessions}


class GitHubMemoryClient:
    def __init__(self, remote: MemoryRemote, opener: Callable = request.urlopen):
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
                                        "User-Agent": "LabCapsule-Studio/1.0"})
        with self.opener(call, timeout=30) as response:
            payload = response.read()
        return json.loads(payload.decode("utf-8")) if payload else {}

    def require_private_repository(self) -> None:
        info = self._call("GET", "")
        if info.get("private") is not True:
            raise ValueError("为避免泄露，记忆同步只允许写入私有 GitHub 仓库")

    def pull(self, device_id: str) -> tuple[dict, str]:
        if not DEVICE_PATTERN.fullmatch(device_id):
            raise ValueError("设备 ID 无效")
        path = f"/contents/memory/devices/{device_id}/snapshot.json?ref=" + parse.quote(
            self.remote.branch, safe="")
        try:
            value = self._call("GET", path)
        except error.HTTPError as failure:
            if failure.code == 404:
                return empty_snapshot(device_id), ""
            raise
        raw = base64.b64decode(str(value.get("content", "")), validate=True)
        if len(raw) > 256 * 1024:
            raise ValueError("远程记忆快照超过 256 KiB")
        return sanitize_snapshot(json.loads(raw.decode("utf-8")), device_id), str(value.get("sha", ""))

    def push(self, snapshot: dict, sha: str = "") -> str:
        clean = sanitize_snapshot(snapshot, str(snapshot.get("deviceId", "")))
        clean["updatedAt"] = datetime.now(timezone.utc).isoformat()
        encoded = base64.b64encode(json.dumps(clean, ensure_ascii=False, indent=2).encode("utf-8"))
        path = f"/contents/memory/devices/{clean['deviceId']}/snapshot.json"
        body = {"message": f"memory: sync {clean['deviceId']} r{clean['revision']}",
                "content": encoded.decode("ascii"), "branch": self.remote.branch}
        if sha:
            body["sha"] = sha
        result = self._call("PUT", path, body)
        return str(result.get("content", {}).get("sha", ""))
