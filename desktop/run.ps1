$ErrorActionPreference = "Stop"
$DesktopRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Get-Command python -ErrorAction Stop
& $Python.Source -m pip install -r (Join-Path $DesktopRoot "requirements.txt")
& $Python.Source (Join-Path $DesktopRoot "labcapsule_desktop.py")
