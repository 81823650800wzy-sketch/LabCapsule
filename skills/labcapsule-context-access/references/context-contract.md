# Context contract

- Query result: at most 4 catalog matches and 4,000 UTF‑8 characters of static detail.
- Runtime context: device identity/capabilities, current connection health, sensor scan, active experiment, compact analysis summary, and at most 12 synchronized facts.
- Memory key: stable hardware `deviceId`, optionally shown with a local user alias.
- Merge: higher `revision` wins; equal revisions merge unique facts and sessions, then increment once. Keep at most 80 facts and 20 session summaries.
- Secrets: redact common key/token/password patterns before saving or upload. A public repository is rejected for writable memory sync.
- Character: one package ID controls persona, Live2D source, action map, poster and device proxy. Missing local model falls back visually but does not silently change persona or memory key.
