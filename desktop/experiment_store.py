"""Durable desktop experiment sessions grouped by stable device identity."""

from __future__ import annotations

import csv
from datetime import datetime
import json
from pathlib import Path
import re
import secrets


DEVICE_PATTERN = re.compile(r"^lc-[0-9a-f]{12}$")
CSV_HEADER = ("timestamp_us", "ax_g", "ay_g", "az_g",
              "gx_dps", "gy_dps", "gz_dps")


class ExperimentStore:
    def __init__(self, app_dir: Path):
        self.root = app_dir / "experiments"

    def _device_dir(self, device_id: str) -> Path:
        if not DEVICE_PATTERN.fullmatch(device_id):
            raise ValueError("稳定设备 ID 无效，不能保存实验")
        return self.root / device_id

    def save(self, device_id: str, samples: list[list[str]], rate_hz: int,
             duration_seconds: int, started_at: str, aborted: bool,
             summary: str) -> dict:
        if not samples:
            raise ValueError("没有可保存的实验样本")
        folder = self._device_dir(device_id)
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().astimezone()
        session_id = stamp.strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(3)
        csv_path = folder / f"{session_id}.csv"
        meta_path = folder / f"{session_id}.json"
        csv_tmp = csv_path.with_suffix(".csv.tmp")
        with csv_tmp.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle)
            writer.writerow(CSV_HEADER)
            writer.writerows(samples)
        csv_tmp.replace(csv_path)
        value = {"schemaVersion": 1, "id": session_id, "deviceId": device_id,
                 "name": "运动实验（中止）" if aborted else "运动实验",
                 "startedAt": started_at or stamp.isoformat(timespec="seconds"),
                 "completedAt": stamp.isoformat(timespec="seconds"),
                 "aborted": aborted, "sampleRateHz": max(0, int(rate_hz)),
                 "durationSeconds": max(0, int(duration_seconds)),
                 "sampleCount": len(samples), "summary": str(summary)[:600],
                 "csv": csv_path.name}
        meta_tmp = meta_path.with_suffix(".json.tmp")
        meta_tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        meta_tmp.replace(meta_path)
        return value

    def recent(self, device_id: str, limit: int = 20) -> list[dict]:
        folder = self._device_dir(device_id)
        if not folder.is_dir():
            return []
        output: list[dict] = []
        for path in sorted(folder.glob("*.json"), reverse=True)[:max(1, min(100, limit))]:
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                if value.get("deviceId") != device_id:
                    continue
                output.append({"id": str(value.get("id", ""))[:64],
                               "name": str(value.get("name", "运动实验"))[:120],
                               "startedAt": str(value.get("startedAt", ""))[:40],
                               "sampleCount": max(0, int(value.get("sampleCount", 0))),
                               "summary": str(value.get("summary", ""))[:600]})
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                continue
        return output
