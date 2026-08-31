$ErrorActionPreference = "Stop"
$DesktopRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
python -m pip install -r (Join-Path $DesktopRoot "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed with exit code $LASTEXITCODE" }
python -m pip install "pyinstaller>=6,<7"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller installation failed with exit code $LASTEXITCODE" }
python -m PyInstaller --noconfirm --clean --windowed --onefile `
  --name "LabCapsule-Studio-0.11.0" `
  --collect-all imageio_ffmpeg `
  --add-data "$(Join-Path $DesktopRoot 'live2d_web\dist');live2d_web\dist" `
  --add-data "$(Join-Path $DesktopRoot 'live2d_web\THIRD_PARTY_NOTICES.md');live2d_web" `
  --exclude-module PyQt5 `
  --exclude-module PyQt6 `
  --exclude-module PySide2 `
  --exclude-module PySide6 `
  --exclude-module qtpy `
  --exclude-module cv2 `
  --exclude-module lxml `
  --exclude-module scipy `
  --exclude-module matplotlib `
  (Join-Path $DesktopRoot "labcapsule_desktop.py")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed with exit code $LASTEXITCODE" }
Write-Host "EXE: $(Join-Path (Get-Location) 'dist\LabCapsule-Studio-0.11.0.exe')"
