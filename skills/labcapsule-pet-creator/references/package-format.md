# LabCapsule Pet Package V1

## Raster layout

```text
my-pet/
├─ pet.json
├─ avatar.png | avatar.jpg | avatar.webp | avatar.gif
└─ persona.txt
```

`avatar` is the only canonical visual. LabCapsule Studio uses it for the AI stage and overlay, and sends the same file into Screen Studio when requested.

## Live2D layout

```text
my-live2d-pet/
├─ pet.json
├─ persona.txt
└─ live2d/
   ├─ my-pet.model3.json
   ├─ my-pet.moc3
   ├─ textures/*.png
   └─ motions/*.motion3.json
```

Use `"live2dModel": "live2d/my-pet.model3.json"` instead of `avatar`. The model JSON remains the canonical visual and references its moc, textures, physics/pose/display-info, expressions, and motions by contained relative paths. `.cmo3` and `.can3` are editor files and are not required at runtime. See the official [Live2D file-type guide](https://docs.live2d.com/en/cubism-editor-manual/file-type-and-extension/).

## pet.json

```json
{
  "$schema": "https://raw.githubusercontent.com/81823650800wzy-sketch/LabCapsule/main/docs/pet_package_v1.schema.json",
  "schemaVersion": 1,
  "id": "my-pet",
  "name": "我的桌宠",
  "avatar": "avatar.gif",
  "personaFile": "persona.txt",
  "greeting": "链路就绪。今天想观察什么现象？",
  "author": "作者名称",
  "license": "CC0-1.0",
  "homepage": "https://example.com/my-pet"
}
```

Rules:

- `schemaVersion` is the integer `1`.
- `id` matches `^[a-z0-9][a-z0-9._-]{0,63}$` and is unique inside a library.
- `name` is non-empty and at most 24 characters in the current UI.
- Exactly one of `avatar` or `live2dModel` is required.
- `avatar`, `live2dModel`, and `personaFile` are relative paths contained inside the package folder. Absolute paths and `..` escapes are invalid.
- The canonical avatar is PNG, JPG, WebP, or GIF; at most 12 MiB, 2048×2048, 4,194,304 pixels per frame, 120 frames, and 180,000,000 total source pixels.
- `persona.txt` is UTF-8, at most 16 KiB; the app uses at most 2,400 characters.
- `greeting` is at most 160 characters. `author`, `license`, and `homepage` should describe the actual source and permission; they do not grant rights by themselves.
- Live2D currently accepts Cubism `Version: 3`, 1–16 PNG textures, up to 256 motions, and validates every referenced runtime file before launch. The app serves model files only on `127.0.0.1` and loads official Cubism Core only after explicit user consent.
- Do not assume a downloaded sample may be redistributed. Before publishing a general model loader, review the official [SDK license](https://www.live2d.com/en/sdk/license/) and [Expandable Application guidance](https://www.live2d.com/en/sdk/license/expandable/).

## Zero-configuration folders

A folder without `pet.json` is recognized when it contains exactly one supported top-level image, or exactly one `model3.json` within the bounded folder scan. Optional `persona.txt` and `greeting.txt` are read. Multiple visuals are intentionally rejected as ambiguous. Use this mode for local trials, not distribution.
