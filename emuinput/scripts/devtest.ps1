param(
  [string]$AdbExe         = "adb",
  [int]   $AdbServerPort  = 5037,
  [string]$Serial         = "127.0.0.1:5555",
  [int]   $HostPort       = 27183,
  [string]$PythonExe      = "python"
)

$ErrorActionPreference = "Stop"

# Project root = ...\emuinput
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

# Detect package layout
$pkgA = Join-Path $projectRoot "emuinput\__init__.py"            # expected: <root>\emuinput\__init__.py
$pkgB = Join-Path $projectRoot "emuinput\emuinput\__init__.py"   # alternate: <root>\emuinput\emuinput\__init__.py

if (Test-Path $pkgA) {
  $importRoot = $projectRoot
  $pkgPath    = Join-Path $projectRoot "emuinput"
}
elseif (Test-Path $pkgB) {
  $importRoot = Join-Path $projectRoot "emuinput"
  $pkgPath    = Join-Path $importRoot "emuinput"
}
else {
  Write-Host "Project root: $projectRoot"
  Write-Host "Could not find package at:"
  Write-Host "  $pkgA"
  Write-Host "  $pkgB"
  Write-Host ""
  Write-Host "Top-level listing:"
  Get-ChildItem -Force $projectRoot | Select-Object Name
  throw "Python package not found."
}

$binRoot = Join-Path $projectRoot "bin\android"

Write-Host "ADB_SERVER_PORT=$AdbServerPort"
Write-Host "Using serial: $Serial"
Write-Host "Using host port: $HostPort"
Write-Host "Project root: $projectRoot"
Write-Host "Import root:  $importRoot"
Write-Host "Package path: $pkgPath"
Write-Host "Bin dir:      $binRoot"

# Friendly binary check
if (-not (Test-Path (Join-Path $binRoot "x86_64\uinputd")) -and -not (Test-Path (Join-Path $binRoot "arm64-v8a\uinputd"))) {
  throw "No uinputd binaries found under $binRoot. Run .\scripts\build-android.ps1 first."
}

# Pin adb server port for this session
$env:ADB_SERVER_PORT = "$AdbServerPort"

# Connect (idempotent)
& $AdbExe connect $Serial | Out-Host

$state = (& $AdbExe -s $Serial get-state).Trim()
if ($state -ne "device") {
  throw "ADB connected but device not ready. get-state=$state serial=$Serial"
}

# Make import work without installing: PYTHONPATH must be the parent of the package folder
if ($env:PYTHONPATH) { $env:PYTHONPATH = "$importRoot;$env:PYTHONPATH" } else { $env:PYTHONPATH = $importRoot }

# Env for python test
$env:EMUINPUT_PROJECT_ROOT = $projectRoot
$env:EMUINPUT_ADB_EXE      = $AdbExe
$env:EMUINPUT_SERIAL       = $Serial
$env:EMUINPUT_HOST_PORT    = "$HostPort"
$env:EMUINPUT_BIN_DIR      = $binRoot

$tmpPy = Join-Path $env:TEMP ("emuinput_devtest_{0}.py" -f ([guid]::NewGuid().ToString("N")))

$py = @'
import os

project_root = os.environ["EMUINPUT_PROJECT_ROOT"]
adb_exe       = os.environ.get("EMUINPUT_ADB_EXE", "adb")
serial        = os.environ["EMUINPUT_SERIAL"]
host_port     = int(os.environ["EMUINPUT_HOST_PORT"])
bin_dir       = os.environ["EMUINPUT_BIN_DIR"]

from emuinput import Adb, EmuController

adb_port = int(os.environ.get("ADB_SERVER_PORT", "5037"))
adb = Adb(adb_exe=adb_exe, adb_server_port=adb_port)

c = EmuController(serial=serial, adb=adb, host_port=host_port, bin_dir=bin_dir)

try:
    hello = c.ensure_daemon()
    print("HELLO:", hello)

    # These coordinates match your HELLO range (0..540, 0..960) nicely
    c.tap(270, 480, down_ms=90)
    c.drag(270, 750, 270, 200, duration_ms=650, steps=40)
    c.type_text("J7M-3W")
    c.press_enter()
finally:
    c.close()

print("devtest complete")
'@

[System.IO.File]::WriteAllText($tmpPy, $py, (New-Object System.Text.UTF8Encoding($false)))

try {
  & $PythonExe $tmpPy
  if ($LASTEXITCODE -ne 0) { throw "Python devtest failed with exit code $LASTEXITCODE." }
}
finally {
  Remove-Item $tmpPy -ErrorAction SilentlyContinue
}
