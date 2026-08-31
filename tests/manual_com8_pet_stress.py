"""Manual COM8 pet-bubble boundary stress test.

Run only with the LabCapsule device attached and Studio closed:
    python tests/manual_com8_pet_stress.py COM8 25
"""

from __future__ import annotations

from pathlib import Path
import sys
import threading
import time


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop"))

from labcapsule_desktop import SerialLink  # noqa: E402
from pet_device import render_pet_bubble  # noqa: E402


def main() -> int:
    port = sys.argv[1] if len(sys.argv) > 1 else "COM8"
    rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 25
    lines: list[str] = []
    lines_lock = threading.Lock()
    stop = threading.Event()

    def on_line(line: str) -> None:
        with lines_lock:
            lines.append(line)

    link = SerialLink(on_line, lambda _state, _port: None)
    link.connect(port)
    # Finish and invalidate a stale binary receive left by an earlier aborted
    # manual run. NUL is ignored by the text parser when no upload is active.
    with link.write_lock:
        assert link.port is not None
        SerialLink._write_all(link.port, bytes(2048))
        link.port.flush()
    time.sleep(0.3)
    deadline = time.monotonic() + 15
    handshake_ok = False
    while time.monotonic() < deadline:
        link.send("PING")
        link.send("STATUS")
        time.sleep(1.0)
        with lines_lock:
            if any(line.startswith("PONG,LABCAPSULE,") for line in lines):
                handshake_ok = True
                break
    with lines_lock:
        lines.clear()

    def heartbeat() -> None:
        tick = 0
        while not stop.wait(0.04):
            try:
                link.send(f"HOST,{tick % 29},37,65,-1")
                tick += 1
            except Exception:
                return

    worker = threading.Thread(target=heartbeat, daemon=True)
    worker.start()
    failure = ""
    try:
        for index in range(rounds):
            payload = render_pet_bubble(
                f"第 {index + 1}/{rounds} 轮：串口边界与中文气泡校验正常。")
            link.send("DISPLAY,PET")
            link.send("PET,STATE,HAPPY,TALK")
            link.upload("PETBUBBLE", payload, lambda _value: None)
            link.send("PET,STATUS")
        time.sleep(0.5)
    except Exception as error:
        failure = f"{type(error).__name__}: {error}"
    finally:
        stop.set()
        worker.join(timeout=1)
        link.close()

    with lines_lock:
        errors = [line for line in lines if line.startswith("ERR,")]
        uploads = [line for line in lines if line.startswith("OK,UPLOAD,PETBUBBLE")]
    print(f"HANDSHAKE={'OK' if handshake_ok else 'FAILED'} "
          f"UPLOAD_OK={len(uploads)}/{rounds} ERRORS={len(errors)}")
    if failure:
        print(f"FAILURE={failure}")
    for line in errors:
        print(line)
    if failure:
        print("LAST_LINES:")
        for line in lines[-30:]:
            print(line)
    return 0 if handshake_ok and len(uploads) == rounds and not errors and not failure else 1


if __name__ == "__main__":
    raise SystemExit(main())
