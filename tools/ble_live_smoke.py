"""Validate LabCapsule live experiment notifications over BLE."""

from __future__ import annotations

import argparse
import asyncio
import json
import struct

from bleak import BleakClient

from ble_offline_smoke import COMMAND_UUID, EXPERIMENT_DATA_UUID, STATUS_UUID, find_device


async def offline_summary(client: BleakClient) -> dict:
    await client.write_gatt_char(COMMAND_UUID, b"OFFLINE:INFO", response=True)
    await asyncio.sleep(0.15)
    return json.loads((await client.read_gatt_char(STATUS_UUID)).decode("utf-8"))


async def run(args: argparse.Namespace) -> None:
    device = await find_device(args.scan_timeout)
    if device is None:
        raise RuntimeError("LabCapsule BLE device not found")

    samples: list[tuple[int, tuple[int, ...]]] = []

    def notification(_sender, data: bytearray) -> None:
        packet = bytes(data)
        if len(packet) == 17 and packet[0] == 0x10:
            samples.append((struct.unpack_from("<I", packet, 1)[0],
                            struct.unpack_from("<6h", packet, 5)))

    async with BleakClient(device, timeout=20) as client:
        before = await offline_summary(client)
        await client.start_notify(EXPERIMENT_DATA_UUID, notification)
        await asyncio.sleep(0.15)
        command = f"START:{args.rate}:{args.duration}".encode("ascii")
        await client.write_gatt_char(COMMAND_UUID, command, response=True)
        await asyncio.sleep(args.duration + 1.5)
        await client.stop_notify(EXPERIMENT_DATA_UUID)
        after = await offline_summary(client)

    expected = args.rate * args.duration
    result = {
        "device": device.name,
        "rateHz": args.rate,
        "durationSeconds": args.duration,
        "expectedSamples": expected,
        "receivedNotifications": len(samples),
        "firstElapsedUs": samples[0][0] if samples else None,
        "lastElapsedUs": samples[-1][0] if samples else None,
        "offlineSessionsBefore": before.get("sessions"),
        "offlineSessionsAfter": after.get("sessions"),
        "offlineSamplesBefore": before.get("samples"),
        "offlineSamplesAfter": after.get("samples"),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if len(samples) < max(1, expected - 3):
        raise RuntimeError("too many live BLE notifications were lost")
    if before.get("sessions") != after.get("sessions"):
        raise RuntimeError("a fully streamed experiment unexpectedly created an offline session")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scan-timeout", type=float, default=15.0)
    parser.add_argument("--rate", type=int, default=100)
    parser.add_argument("--duration", type=int, default=2)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
