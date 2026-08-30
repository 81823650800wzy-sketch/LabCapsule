# Pet Package Test Checklist

Run tests in increasing scope and stop at the layer the available environment permits.

## 1. Package validation

- Run `python scripts/create_pet_package.py validate <package-folder>`.
- Confirm ID, UTF-8 manifest, exactly one visual, contained paths, persona, and license metadata.
- For raster, confirm format, byte limit, dimensions, and frame count. For Live2D, confirm model version, moc, PNG textures, auxiliary JSON, expressions, motions, and dependency counts.
- Re-run after moving the entire folder to prove it has no external path dependency.

## 2. Application recognition

- Open `AI 桌宠 → 统一桌宠管理`.
- Select the package folder directly; then select its parent library and confirm the same package appears exactly once.
- Apply it and verify the displayed name, package ID, visual type, frame/motion count, persona, and greeting.
- Restart Studio and confirm the selected folder is restored. Move/delete it and confirm Studio falls back safely instead of crashing.

## 3. Unified visual behavior

- Compare the AI stage and desktop overlay: both must use the same canonical visual.
- For GIF, observe at least two loops and verify source timing is plausible; the desktop player clamps frames to 33–2000 ms.
- For Live2D, personally review and accept the applicable Cubism/model terms, verify WebGL load status, click/tap hit motions, trigger every listed motion group, and test stage plus transparent always-on-top overlay.
- For raster, send the pet to Screen Studio and verify the 240×320 preview derives from the same file. Live2D cannot run directly on ESP32; export an authorized GIF first. Do not upload until the user approves replacing device media.

## 4. AI identity

- Ask the pet for its name and role with no API key to exercise local fallback.
- With an explicitly configured test key or local compatible mock, verify the model receives the selected name/persona without exposing secrets.
- Connect/disconnect the device and verify event captions keep the selected visual and identity.

## 5. Regression and hardware

- Run the repository test suite and packaged-EXE smoke test.
- On COM8, use only `PING` and `STATUS` unless the user authorizes experiments or media upload.
- Record firmware identity, READY/error state, MPU status, mock state, and sample count.
- State explicitly whether media upload, firmware flash, Wi-Fi changes, and paid AI calls were skipped.
- Never commit or release third-party Live2D sample model files unless their redistribution license has been independently verified.
