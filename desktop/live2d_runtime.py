"""Consent persistence and child-process command construction for Live2D."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

from pet_packages import APP_DIR


CORE_URL = "https://cubism.live2d.com/sdk-web/core/05/live2dcubismcore.min.js"
CORE_LINE = "Cubism 5.2 hosted Core"
CONSENT_PATH = APP_DIR / "live2d_consent_v1.json"
CONTROL_PATH = APP_DIR / "live2d_control_v1.json"
LIVE2D_ACTIONS = {"IDLE", "BOUNCE", "TILT", "THINK", "TALK", "SCAN",
                  "CELEBRATE", "ALERT", "SLEEP"}


def has_live2d_consent(path_value: str | Path = CONSENT_PATH) -> bool:
    path = Path(path_value)
    if not path.is_file():
        return False
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    return bool(raw.get("accepted") is True and raw.get("coreUrl") == CORE_URL
                and raw.get("schemaVersion") == 1)


def save_live2d_consent(path_value: str | Path = CONSENT_PATH) -> None:
    path = Path(path_value)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({
        "schemaVersion": 1,
        "accepted": True,
        "coreUrl": CORE_URL,
        "coreLine": CORE_LINE,
        "acceptedAt": datetime.now(timezone.utc).isoformat(),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def write_live2d_action(emotion: str, action: str,
                        path_value: str | Path = CONTROL_PATH) -> int:
    path = Path(path_value)
    path.parent.mkdir(parents=True, exist_ok=True)
    safe_emotion = "".join(character for character in emotion.upper()
                           if character.isascii() and (character.isalnum() or character == "_"))[:16]
    safe_action = "".join(character for character in action.upper()
                          if character.isascii() and (character.isalnum() or character == "_"))[:16]
    if safe_action not in LIVE2D_ACTIONS:
        safe_action = "TALK"
    revision = time.time_ns()
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"schemaVersion": 1, "revision": revision,
                                     "emotion": safe_emotion or "SPEAKING",
                                     "action": safe_action}, separators=(",", ":")),
                         encoding="utf-8")
    temporary.replace(path)
    return revision


def player_command(model_path: str | Path, mode: str, desktop_root: str | Path,
                   executable: str | Path | None = None,
                   frozen: bool | None = None,
                   control_path: str | Path | None = None) -> list[str]:
    if mode not in {"stage", "overlay"}:
        raise ValueError("Live2D 播放模式无效")
    is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    program = str(executable or sys.executable)
    model = str(Path(model_path).expanduser().resolve())
    if is_frozen:
        command = [program, "--live2d-player", model, "--mode", mode]
    else:
        command = [program, str(Path(desktop_root).resolve() / "live2d_player.py"),
                   model, "--mode", mode]
    if control_path:
        command.extend(("--control", str(Path(control_path).expanduser().resolve())))
    return command
