$ErrorActionPreference = "Stop"
$DesktopRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
python -m pip install -r (Join-Path $DesktopRoot "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed with exit code $LASTEXITCODE" }
python -m pip install "pyinstaller>=6,<7"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller installation failed with exit code $LASTEXITCODE" }
python -m PyInstaller --noconfirm --clean --windowed --onefile `
  --name "LabCapsule-Studio-0.8.0" `
  --collect-all imageio_ffmpeg `
  --exclude-module cv2 `
  --exclude-module lxml `
  --exclude-module scipy `
  --exclude-module matplotlib `
  (Join-Path $DesktopRoot "labcapsule_desktop.py")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed with exit code $LASTEXITCODE" }
Write-Host "EXE: $(Join-Path (Get-Location) 'dist\LabCapsule-Studio-0.8.0.exe')"
