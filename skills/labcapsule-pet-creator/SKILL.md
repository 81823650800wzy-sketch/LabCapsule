---
name: labcapsule-pet-creator
description: Create, validate, repair, and test unified LabCapsule pet-package folders from PNG, JPG, WebP, GIF, or Live2D Cubism model3 runtime assets. Use when a user wants to add an animated desktop pet, package a character for LabCapsule Studio, or diagnose why a pet folder is not recognized; do not use for unrelated image editing.
---

# LabCapsule Pet Creator

Create one portable folder whose single canonical visual drives the AI identity and desktop stages. Raster visuals can also be handed to the 240×320 Screen Studio; Live2D must first be exported or recorded to a raster animation for the ESP32 display.

## Workflow

1. Inspect the supplied source and determine whether it is a raster asset (PNG, JPG, WebP, GIF) or a Cubism runtime `.model3.json`. Confirm the user may use it. Do not infer copyright or character-IP permission from availability on the internet.
2. Read [references/package-format.md](references/package-format.md) before creating or repairing a package.
3. Use `scripts/create_pet_package.py create` for a raster package, or `create-live2d` for a Cubism package. Both refuse a non-empty output directory, write UTF-8 metadata, and validate the completed folder. The Live2D command copies only the runtime dependency graph referenced by `model3.json`; it does not copy editor-only `.cmo3` or `.can3` files.
4. Keep exactly one canonical `avatar` or `live2dModel` in `pet.json`, never both. Do not create separate identities for the main window, overlay, and device.
5. Run `scripts/create_pet_package.py validate <folder>` after any manual edit. Treat a validation failure as unfinished work.
6. When the user asks for testing, release readiness, or app integration, read and follow [references/test-checklist.md](references/test-checklist.md). Report which layers were actually exercised; do not claim a hardware or online test from static validation.

For Live2D, read the official [file-type guide](https://docs.live2d.com/en/cubism-editor-manual/file-type-and-extension/) and preserve `model3.json`, `moc3`, textures, physics/pose/display-info files, expressions, and `motion3.json` files exactly as referenced. LabCapsule does not bundle Cubism Core. The user must personally accept the applicable Live2D/Cubism terms before playback. Treat redistributing a sample model and publishing an expandable model-loading application as separate licensing questions.

If the user provides only a folder with exactly one supported image or one discoverable `model3.json`, LabCapsule Studio can infer a zero-configuration pet. Create `pet.json` for any distributable package so identity, persona, author, and license remain stable.

Do not publish, push, or upload a package unless the user authorizes that external action.
