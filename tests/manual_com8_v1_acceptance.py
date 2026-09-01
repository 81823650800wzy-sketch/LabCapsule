"""Read-only COM8 acceptance check for LabCapsule V1.

This script never changes Wi-Fi, starts an experiment, erases media, or writes a file.
It is intentionally kept in the repository so release verification is reproducible.
"""

from __future__ import annotations

import argparse
import time

import serial


COMMANDS = (
    ("PING", "PONG,LABCAPSULE,"),
    ("IDENTITY", "IDENTITY,"),
    ("STATUS", "STATUS,"),
    ("NETWORK", "NETWORK,"),
    ("SENSORS", "SENSORS,"),
    ("PET,STATUS", "PET,"),
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", default="COM8")
    parser.add_argument("--baud", default=460800, type=int)
    args = parser.parse_args()

    responses: list[str] = []
    with serial.Serial(args.port, args.baud, timeout=0.2, write_timeout=2) as device:
        # A full flash may reopen COM8 before NVS, display and sensors finish
        # initialization.  Do not mistake boot logs for command responses.
        time.sleep(3.0)
        device.reset_input_buffer()
        for command, expected_prefix in COMMANDS:
            device.write((command + "\n").encode("ascii"))
            device.flush()
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                line = device.readline().decode("utf-8", "replace").strip()
                if not line or not line.startswith(expected_prefix):
                    continue
                responses.append(line)
                break

    print("\n".join(responses))
    required = ("PONG,LABCAPSULE,", "IDENTITY,", "STATUS,", "NETWORK,", "SENSORS,", "PET,")
    missing = [prefix for prefix in required if not any(line.startswith(prefix) for line in responses)]
    if missing:
        print("MISSING=" + ",".join(missing))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
