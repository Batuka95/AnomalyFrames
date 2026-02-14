param(
  [string]$AdbExe = "C:\Program Files\Netease\MuMuPlayer\nx_main\adb.exe",
  [int]$AdbServerPort = 5037,
  [string]$Serial = "127.0.0.1:5555",
  [int]$HostPort = 27183,
  [string]$BinDir = "",
  [switch]$AttemptFix,
  [switch]$PythonCheck,
  [string]$PythonExe = "python"
)

$ErrorActionPreference = "Stop"

function Write-Section([string]$Title) {
  Write-Host ""
  Write-Host "=== $Title ===" -ForegroundColor Cyan
}

function Write-Pass([string]$Msg) {
  Write-Host "[PASS] $Msg" -ForegroundColor Green
}

function Write-Warn([string]$Msg) {
  Write-Host "[WARN] $Msg" -ForegroundColor Yellow
}

function Write-Fail([string]$Msg) {
  Write-Host "[FAIL] $Msg" -ForegroundColor Red
}

function Invoke-External {
  param(
    [Parameter(Mandatory = $true)][string]$FilePath,
    [Parameter(Mandatory = $true)][string[]]$Arguments,
    [int]$TimeoutSec = 20
  )
  $psi = New-Object System.Diagnostics.ProcessStartInfo
  $psi.FileName = $FilePath
  $escapedArgs = @()
  foreach ($arg in $Arguments) {
    if ($null -eq $arg) { continue }
    $s = [string]$arg
    if ($s -match '[\s"]') {
      $escaped = $s.Replace('"', '\"')
      $escapedArgs += '"' + $escaped + '"'
    } else {
      $escapedArgs += $s
    }
  }
  $psi.Arguments = ($escapedArgs -join ' ')
  $psi.RedirectStandardOutput = $true
  $psi.RedirectStandardError = $true
  $psi.UseShellExecute = $false
  $psi.CreateNoWindow = $true

  $proc = New-Object System.Diagnostics.Process
  $proc.StartInfo = $psi
  [void]$proc.Start()

  if (-not $proc.WaitForExit($TimeoutSec * 1000)) {
    try { $proc.Kill($true) } catch {}
    return [pscustomobject]@{
      ExitCode = 124
      StdOut = ""
      StdErr = "Timed out after $TimeoutSec sec"
      TimedOut = $true
    }
  }

  return [pscustomobject]@{
    ExitCode = $proc.ExitCode
    StdOut = $proc.StandardOutput.ReadToEnd()
    StdErr = $proc.StandardError.ReadToEnd()
    TimedOut = $false
  }
}

function Invoke-Adb {
  param(
    [string[]]$CommandArgs,
    [int]$TimeoutSec = 20
  )
  Invoke-External -FilePath $script:ResolvedAdbExe -Arguments $CommandArgs -TimeoutSec $TimeoutSec
}

function Show-Run {
  param(
    [string]$Label,
    [string[]]$CommandArgs,
    [int]$TimeoutSec = 20
  )
  Write-Host "`n$Label"
  Write-Host "  > $script:ResolvedAdbExe $($CommandArgs -join ' ')" -ForegroundColor DarkGray
  $r = Invoke-Adb -CommandArgs $CommandArgs -TimeoutSec $TimeoutSec
  if ($r.StdOut.Trim()) { Write-Host $r.StdOut.Trim() }
  if ($r.StdErr.Trim()) { Write-Host $r.StdErr.Trim() -ForegroundColor DarkYellow }
  if ($r.TimedOut) {
    Write-Fail "$Label timed out."
  } elseif ($r.ExitCode -ne 0) {
    Write-Fail "$Label failed with exit $($r.ExitCode)."
  } else {
    Write-Pass "$Label succeeded."
  }
  return $r
}

function Read-LineWithTimeout {
  param(
    [Parameter(Mandatory = $true)][System.IO.StreamReader]$Reader,
    [int]$TimeoutMs = 2000
  )
  $task = $Reader.ReadLineAsync()
  if ($task.Wait($TimeoutMs)) {
    return $task.Result
  }
  return $null
}

function Probe-UinputHello {
  param(
    [int]$Port
  )
  $client = $null
  $stream = $null
  $writer = $null
  $reader = $null
  try {
    $client = New-Object System.Net.Sockets.TcpClient
    $iar = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
    if (-not $iar.AsyncWaitHandle.WaitOne(3000)) {
      throw "TCP connect timeout to 127.0.0.1:$Port"
    }
    $client.EndConnect($iar)
    $stream = $client.GetStream()
    $stream.ReadTimeout = 3000
    $stream.WriteTimeout = 3000
    $writer = New-Object System.IO.StreamWriter($stream)
    $writer.NewLine = "`n"
    $writer.AutoFlush = $true
    $reader = New-Object System.IO.StreamReader($stream)

    $writer.WriteLine("HELLO")
    $line = Read-LineWithTimeout -Reader $reader -TimeoutMs 3000
    if (-not $line) {
      throw "No HELLO response from uinputd"
    }
    return [pscustomobject]@{
      Ok = $line.StartsWith("OK ")
      Line = $line
      Error = ""
    }
  } catch {
    return [pscustomobject]@{
      Ok = $false
      Line = ""
      Error = "$_"
    }
  } finally {
    try { if ($writer) { $writer.Dispose() } } catch {}
    try { if ($reader) { $reader.Dispose() } } catch {}
    try { if ($stream) { $stream.Dispose() } } catch {}
    try { if ($client) { $client.Dispose() } } catch {}
  }
}

Write-Section "Resolve ADB"
$script:ResolvedAdbExe = $null
$adbCandidates = @()
if ($AdbExe) { $adbCandidates += $AdbExe }
$adbCandidates += "adb"
$adbCandidates = $adbCandidates | Where-Object { $_ -and $_.Trim() } | Select-Object -Unique

foreach ($c in $adbCandidates) {
  if ([System.IO.Path]::IsPathRooted($c)) {
    if (Test-Path $c) {
      $script:ResolvedAdbExe = $c
      break
    }
  } else {
    $hit = Get-Command $c -ErrorAction SilentlyContinue
    if ($hit) {
      $script:ResolvedAdbExe = $hit.Source
      break
    }
  }
}

if (-not $script:ResolvedAdbExe) {
  Write-Fail "No adb executable found. Checked: $($adbCandidates -join ', ')"
  exit 2
}
Write-Pass "Using adb: $script:ResolvedAdbExe"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $BinDir) {
  $BinDir = Join-Path $projectRoot "bin\android"
}
Write-Host "ProjectRoot: $projectRoot"
Write-Host "BinDir:      $BinDir"
Write-Host "Serial:      $Serial"
Write-Host "HostPort:    $HostPort"
Write-Host "ADB port:    $AdbServerPort"

$oldAdbPort = $env:ADB_SERVER_PORT
$env:ADB_SERVER_PORT = "$AdbServerPort"

try {
  Write-Section "Process/Port Snapshot"
  $adbProcs = Get-Process adb -ErrorAction SilentlyContinue | Select-Object Id, ProcessName, Path
  if ($adbProcs) {
    $adbProcs | Format-Table -AutoSize | Out-Host
  } else {
    Write-Warn "No adb processes currently running."
  }
  (netstat -ano | Select-String ":5037") | ForEach-Object { $_.ToString() } | Out-Host
  (netstat -ano | Select-String ":5555") | ForEach-Object { $_.ToString() } | Out-Host

  Write-Section "ADB Baseline"
  [void](Show-Run -Label "adb version" -CommandArgs @("version") -TimeoutSec 10)
  [void](Show-Run -Label "adb start-server" -CommandArgs @("start-server") -TimeoutSec 10)
  [void](Show-Run -Label "adb connect" -CommandArgs @("connect", $Serial) -TimeoutSec 15)
  $devices = Show-Run -Label "adb devices -l" -CommandArgs @("devices", "-l") -TimeoutSec 15

  $stateResult = Show-Run -Label "adb get-state" -CommandArgs @("-s", $Serial, "get-state") -TimeoutSec 15
  $state = $stateResult.StdOut.Trim()
  if ($state -ne "device") {
    Write-Warn "Serial '$Serial' state is '$state' (expected 'device')."
  } else {
    Write-Pass "Serial '$Serial' is online."
  }

  $echoResult = Show-Run -Label "adb shell echo" -CommandArgs @("-s", $Serial, "shell", "echo ok") -TimeoutSec 12
  $abiResult = Show-Run -Label "adb shell getprop abi" -CommandArgs @("-s", $Serial, "shell", "getprop ro.product.cpu.abi") -TimeoutSec 12
  $abi = $abiResult.StdOut.Trim()
  if (-not $abi) {
    Write-Warn "ABI probe returned empty."
  } else {
    Write-Pass "ABI: $abi"
  }

  Write-Section "Remote uinputd State"
  [void](Show-Run -Label "remote binary" -CommandArgs @("-s", $Serial, "shell", "toybox ls -l /data/local/tmp/uinputd 2>/dev/null || echo NO_REMOTE_BIN") -TimeoutSec 10)
  [void](Show-Run -Label "remote pid" -CommandArgs @("-s", $Serial, "shell", "toybox pidof uinputd || echo NO_PID") -TimeoutSec 10)
  [void](Show-Run -Label "remote input device scan" -CommandArgs @("-s", $Serial, "shell", "toybox grep -ni -A12 -B2 uinputd-virtual-touchscreen /proc/bus/input/devices || echo NO_VIRTUAL_DEVICE") -TimeoutSec 10)
  [void](Show-Run -Label "remote uinputd log head" -CommandArgs @("-s", $Serial, "shell", "toybox head -n 80 /data/local/tmp/uinputd.log 2>/dev/null || echo NO_DAEMON_LOG") -TimeoutSec 10)

  if ($AttemptFix) {
    Write-Section "Attempt Fix (safe restart)"
    [void](Show-Run -Label "kill remote uinputd" -CommandArgs @("-s", $Serial, "shell", "toybox pkill -x uinputd >/dev/null 2>&1 || true") -TimeoutSec 10)

    $localBinary = $null
    if ($abi -match "arm64") {
      $candidate = Join-Path $BinDir "arm64-v8a\uinputd"
      if (Test-Path $candidate) { $localBinary = $candidate }
    }
    if (-not $localBinary -and $abi -match "x86_64") {
      $candidate = Join-Path $BinDir "x86_64\uinputd"
      if (Test-Path $candidate) { $localBinary = $candidate }
    }
    if (-not $localBinary) {
      $fallbackX64 = Join-Path $BinDir "x86_64\uinputd"
      $fallbackArm = Join-Path $BinDir "arm64-v8a\uinputd"
      if (Test-Path $fallbackX64) { $localBinary = $fallbackX64 }
      elseif (Test-Path $fallbackArm) { $localBinary = $fallbackArm }
    }

    if ($localBinary) {
      [void](Show-Run -Label "push uinputd binary" -CommandArgs @("-s", $Serial, "push", $localBinary, "/data/local/tmp/uinputd") -TimeoutSec 20)
      [void](Show-Run -Label "chmod uinputd binary" -CommandArgs @("-s", $Serial, "shell", "chmod 755 /data/local/tmp/uinputd") -TimeoutSec 10)
    } else {
      Write-Warn "No local uinputd binary found under $BinDir"
    }

    [void](Show-Run -Label "start remote uinputd" -CommandArgs @("-s", $Serial, "shell", "toybox nohup /data/local/tmp/uinputd --daemon > /data/local/tmp/uinputd.log 2>&1 &") -TimeoutSec 10)
    [void](Show-Run -Label "verify remote uinputd pid" -CommandArgs @("-s", $Serial, "shell", "sleep 0.3; toybox pidof uinputd || echo NO_PID") -TimeoutSec 10)
  }

  Write-Section "Forward + HELLO"
  $rmFwd = Show-Run -Label "remove forward" -CommandArgs @("-s", $Serial, "forward", "--remove", "tcp:$HostPort") -TimeoutSec 10
  if ($rmFwd.ExitCode -ne 0 -and $rmFwd.StdErr -match "listener 'tcp:$HostPort' not found") {
    Write-Warn "forward remove reported not found; continuing."
  }
  [void](Show-Run -Label "add forward" -CommandArgs @("-s", $Serial, "forward", "tcp:$HostPort", "localabstract:uinputd") -TimeoutSec 10)
  [void](Show-Run -Label "forward list" -CommandArgs @("forward", "--list") -TimeoutSec 10)

  $hello = Probe-UinputHello -Port $HostPort
  if ($hello.Ok) {
    Write-Pass "uinputd HELLO response: $($hello.Line)"
  } else {
    Write-Fail "uinputd HELLO failed: $($hello.Error)"
  }

  if ($PythonCheck) {
    Write-Section "Optional Python Package Check"
    $oldPyPath = $env:PYTHONPATH
    if ($oldPyPath) {
      $env:PYTHONPATH = "$projectRoot;$oldPyPath"
    } else {
      $env:PYTHONPATH = "$projectRoot"
    }
    $tmpPy = Join-Path $env:TEMP ("uinput_diag_{0}.py" -f ([guid]::NewGuid().ToString("N")))
    $py = @'
import sys
try:
    from emuinput import Adb, EmuController
    print("IMPORT_OK", Adb.__name__, EmuController.__name__)
except Exception as e:
    print("IMPORT_FAIL", repr(e))
    sys.exit(1)
'@
    [System.IO.File]::WriteAllText($tmpPy, $py, (New-Object System.Text.UTF8Encoding($false)))
    try {
      $r = Invoke-External -FilePath $PythonExe -Arguments @($tmpPy) -TimeoutSec 20
      if ($r.StdOut.Trim()) { Write-Host $r.StdOut.Trim() }
      if ($r.StdErr.Trim()) { Write-Host $r.StdErr.Trim() -ForegroundColor DarkYellow }
      if ($r.ExitCode -eq 0) {
        Write-Pass "Python import check passed."
      } else {
        Write-Warn "Python import check failed (often means PYTHONPATH/venv context only)."
      }
    } finally {
      Remove-Item $tmpPy -ErrorAction SilentlyContinue
      if ($null -eq $oldPyPath) {
        Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
      } else {
        $env:PYTHONPATH = $oldPyPath
      }
    }
  }
}
finally {
  if ($null -eq $oldAdbPort) {
    Remove-Item Env:ADB_SERVER_PORT -ErrorAction SilentlyContinue
  } else {
    $env:ADB_SERVER_PORT = $oldAdbPort
  }
}

Write-Host ""
Write-Host "Diagnostics complete." -ForegroundColor Cyan
