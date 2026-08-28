"""Validate LabCapsule V0.6 idle/experiment mode and hardware telemetry."""

from __future__ import annotations

import argparse
import asyncio
import json

from bleak import BleakClient

from ble_offline_smoke import COMMAND_UUID, STATUS_UUID, find_device


async def command(client: BleakClient, value: str) -> dict:
    await client.write_gatt_char(COMMAND_UUID, value.encode("ascii"), response=True)
    await asyncio.sleep(0.15)
    return json.loads((await client.read_gatt_char(STATUS_UUID)).decode("utf-8"))


async def run(args: argparse.Namespace) -> None:
    device = await find_device(args.scan_timeout)
    if device is None:
        raise RuntimeError("LabCapsule BLE device not found")
    async with BleakClient(device, timeout=20) as client:
        await command(client, "MODE:EXPERIMENT")
        await command(client, "NOTICE:PHONE LINK|READY FOR NOTICES")
        idle = await command(client, "MODE:IDLE")
        hardware = await command(client, "HARDWARE")

    mode = idle.get("device", {}).get("operationMode")
    if mode != "idle" or hardware.get("type") != "hardware":
        raise RuntimeError("mode or hardware response did not match V0.6 protocol")
    for key in ("internalTotal", "psramTotal", "storageCapacity"):
        if int(hardware.get(key, 0)) <= 0:
            raise RuntimeError(f"invalid hardware field: {key}")
    print(json.dumps({
        "device": device.name,
        "idleStatus": idle,
        "hardware": hardware,
    }, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scan-timeout", type=float, default=15.0)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
