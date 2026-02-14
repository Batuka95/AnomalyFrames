param(
    [string]$NdkPath,
    [ValidateSet('Debug', 'Release')]
    [string]$BuildType = 'Release',
    [string[]]$Abis = @('x86_64', 'arm64-v8a')
)

$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot  = (Resolve-Path (Join-Path $scriptDir '..')).Path

$sourceDir = Join-Path $repoRoot 'native/uinputd'
$buildRoot = Join-Path $repoRoot 'build/android'
$outRoot   = Join-Path $repoRoot 'bin/android'

# Resolve NDK path from args or env
if (-not $NdkPath) {
    if ($env:ANDROID_NDK_HOME) {
        $NdkPath = $env:ANDROID_NDK_HOME
    }
    elseif ($env:ANDROID_NDK_ROOT) {
        $NdkPath = $env:ANDROID_NDK_ROOT
    }
}

if (-not $NdkPath) {
    throw 'Android NDK path not set. Provide -NdkPath or set ANDROID_NDK_HOME/ANDROID_NDK_ROOT.'
}

$NdkPath = (Resolve-Path $NdkPath).Path
$toolchain = Join-Path $NdkPath 'build/cmake/android.toolchain.cmake'

if (-not (Test-Path $toolchain)) {
    throw "Android toolchain file not found: $toolchain"
}

# Ensure required host tools exist
if (-not (Get-Command cmake -ErrorAction SilentlyContinue)) {
    throw "cmake not found in PATH. Install CMake, then reopen PowerShell."
}
if (-not (Get-Command ninja -ErrorAction SilentlyContinue)) {
    throw "ninja not found in PATH. Install Ninja (winget install Ninja-build.Ninja), then reopen PowerShell."
}

# Build each ABI
foreach ($abi in $Abis) {
    $buildDir = Join-Path $buildRoot $abi
    $destDir  = Join-Path $outRoot  $abi

    # IMPORTANT: CMake caches the generator in the build folder. If we previously configured with VS/MSBuild,
    # reusing the folder will keep breaking. Clean per-ABI build dir for reliable reconfigure.
    if (Test-Path $buildDir) {
        Remove-Item -Recurse -Force $buildDir
    }
    New-Item -ItemType Directory -Force -Path $buildDir | Out-Null
    New-Item -ItemType Directory -Force -Path $destDir  | Out-Null

    $configureArgs = @(
        '-S', $sourceDir,
        '-B', $buildDir,
        '-G', 'Ninja',
        "-DCMAKE_TOOLCHAIN_FILE=$toolchain",
        "-DANDROID_ABI=$abi",
        '-DANDROID_PLATFORM=android-26',
        "-DCMAKE_BUILD_TYPE=$BuildType"
    )

    & cmake @configureArgs
    if ($LASTEXITCODE -ne 0) {
        throw "CMake configure failed for ABI '$abi'."
    }

    # Ninja is single-config; do not pass --config
    $buildArgs = @('--build', $buildDir)
    & cmake @buildArgs
    if ($LASTEXITCODE -ne 0) {
        throw "CMake build failed for ABI '$abi'."
    }

    # Locate artifact (CMake+Ninja normally emits $buildDir\uinputd)
    $candidates = @(
        (Join-Path $buildDir 'uinputd'),
        (Join-Path $buildDir 'uinputd.exe') # unlikely for Android but harmless to check
    )

    $artifact = $null
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            $artifact = $candidate
            break
        }
    }

    if (-not $artifact) {
        throw "Build succeeded but uinputd artifact not found for ABI '$abi'. Checked: $($candidates -join ', ')"
    }

    Copy-Item -Force $artifact (Join-Path $destDir 'uinputd')
    Write-Host "Built $abi -> bin/android/$abi/uinputd"
}
