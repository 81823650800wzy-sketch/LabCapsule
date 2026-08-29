$ErrorActionPreference = "Stop"
$DesktopRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
python -m pip install -r (Join-Path $DesktopRoot "requirements.txt")
python -m pip install "pyinstaller>=6,<7"
python -m PyInstaller --noconfirm --clean --windowed --onefile `
  --name "LabCapsule-Studio-0.7.0" `
  --collect-all imageio_ffmpeg `
  --exclude-module cv2 `
  --exclude-module lxml `
  --exclude-module scipy `
  --exclude-module matplotlib `
  (Join-Path $DesktopRoot "labcapsule_desktop.py")
Write-Host "EXE: $(Join-Path (Get-Location) 'dist\LabCapsule-Studio-0.7.0.exe')"
