# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_all


root = Path(SPEC).resolve().parent
datas = [
    (str(root / "desktop" / "live2d_web" / "dist"), "live2d_web/dist"),
    (str(root / "desktop" / "live2d_web" / "THIRD_PARTY_NOTICES.md"), "live2d_web"),
    (str(root / "knowledge"), "knowledge"),
    (str(root / "shared"), "shared"),
]
binaries = []
hiddenimports = ["bleak.backends.winrt", "sounddevice", "webview.platforms.edgechromium"]
package_data, package_binaries, package_hidden = collect_all("imageio_ffmpeg")
datas += package_data
binaries += package_binaries
hiddenimports += package_hidden


a = Analysis(
    [str(root / "desktop" / "labcapsule_desktop.py")],
    pathex=[str(root / "desktop")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PyQt5", "PyQt6", "PySide2", "PySide6", "qtpy", "cv2", "lxml",
              "scipy", "matplotlib"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="LabCapsule-Studio-1.3.0",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
