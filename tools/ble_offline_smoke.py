"""BLE smoke test for LabCapsule offline experiment storage.

This tool never connects the computer to the device Wi-Fi access point.  It scans
for the LabCapsule BLE service, reads the offline-store summary, exports all LCB1
sessions, and validates their headers and sample lengths.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import struct
from pathlib import Path

from bleak import BleakClient, BleakScanner


def uuid(characteristic: int) -> str:
    return f"6c4300{characteristic:02d}-4c61-6243-6170-73756c650001"


SERVICE_UUID = uuid(1)
COMMAND_UUID = uuid(2)
STATUS_UUID = uuid(3)
EXPERIMENT_DATA_UUID = uuid(8)
HEADER = struct.Struct("<IHHIIIIII")
SAMPLE_BYTES = 16
MAGIC_LCB1 = 0x3142434C


def validate_export(payload: bytes) -> list[dict[str, int]]:
    sessions: list[dict[str, int]] = []
    offset = 0
    while offset < len(payload):
        if len(payload) - offset < HEADER.size:
            raise ValueError(f"truncated header at byte {offset}")
        fields = HEADER.unpack_from(payload, offset)
        magic, version, header_size, session_id, rate, duration, count, dropped, flags = fields
        if magic != MAGIC_LCB1 or version != 1 or header_size < HEADER.size:
            raise ValueError(f"invalid LCB1 header at byte {offset}")
        session_size = header_size + count * SAMPLE_BYTES
        if offset + session_size > len(payload):
            raise ValueError(
                f"session {session_id} expects {session_size} bytes, "
                f"only {len(payload) - offset} remain"
            )
        sessions.append(
            {
                "sessionId": session_id,
                "sampleRateHz": rate,
                "durationSeconds": duration,
                "samples": count,
                "dropped": dropped,
                "flags": flags,
                "bytes": session_size,
            }
        )
        offset += session_size
    return sessions


async def find_device(timeout: float):
    return await BleakScanner.find_device_by_filter(
        lambda device, advertisement: (
            (device.name or "").startswith("LabCapsule")
            or SERVICE_UUID.lower() in [value.lower() for value in advertisement.service_uuids]
        ),
        timeout=timeout,
    )


async def run(args: argparse.Namespace) -> None:
    device = await find_device(args.scan_timeout)
    if device is None:
        raise RuntimeError("LabCapsule BLE device not found")

    async with BleakClient(device, timeout=20) as client:
        await client.write_gatt_char(COMMAND_UUID, b"OFFLINE:INFO", response=True)
        await asyncio.sleep(0.15)
        summary = json.loads((await client.read_gatt_char(STATUS_UUID)).decode("utf-8"))

        await client.write_gatt_char(COMMAND_UUID, b"OFFLINE:OPEN", response=True)
        exported = bytearray()
        chunks = 0
        while True:
            packet = bytes(await client.read_gatt_char(EXPERIMENT_DATA_UUID))
            if not packet:
                raise RuntimeError("empty BLE offline packet")
            if packet[0] == 0x21:
                break
            if packet[0] != 0x20:
                raise RuntimeError(f"unexpected BLE packet type 0x{packet[0]:02x}")
            exported.extend(packet[1:])
            chunks += 1
        await client.write_gatt_char(COMMAND_UUID, b"OFFLINE:CLOSE", response=True)

    sessions = validate_export(bytes(exported))
    if args.output:
        output = Path(args.output).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(exported)
    else:
        output = None

    print(json.dumps(
        {
            "device": device.name,
            "address": device.address,
            "summary": summary,
            "exportBytes": len(exported),
            "bleChunks": chunks,
            "sessions": sessions,
            "output": str(output) if output else None,
        },
        ensure_ascii=False,
        indent=2,
    ))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scan-timeout", type=float, default=15.0)
    parser.add_argument("--output", help="optional path for the exported .lcb data")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
