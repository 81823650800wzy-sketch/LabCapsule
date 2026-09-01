---
name: labcapsule-context-access
description: Resolve LabCapsule device identity and retrieve only the relevant component, transport, sensor, experiment, or synchronized-memory context. Use when answering questions about a connected LabCapsule, adding sensors, diagnosing its hardware, or preparing AI context without loading the whole repository.
---

# LabCapsule Context Access

Use device evidence first, then retrieve the smallest relevant repository context.

1. Obtain the stable `deviceId` from `IDENTITY` (USB), `/api/status` (Wi‑Fi), or the BLE status characteristic. Never infer it from a COM number, IP address, or phone name.
2. Run `scripts/query_context.py --query "<question>" --catalog knowledge/catalog.json`. Add `--device-json` or `--experiment-json` only when those files are available. Do not load every reference.
3. Read only the detail files returned in `matches`. Treat live status and sensor scans as authoritative over static documentation.
4. For memory, use `memory/devices/<deviceId>/snapshot.json` in the user-configured private memory repository. Never commit API keys, GitHub tokens, Wi‑Fi passwords, raw audio, or unredacted secrets.
5. If the device is offline, label cached values with their timestamp. Never present mock sensor data as physical measurements.
6. Operations that start/abort experiments, change network credentials, flash firmware, clear storage, or overwrite media still require the normal user confirmation path.

See [context contract](references/context-contract.md) for runtime limits and merge rules.
