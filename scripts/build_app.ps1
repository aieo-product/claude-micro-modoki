# WARNING: Windows packaging is UNVERIFIED. Please report results to issue #21:
# https://github.com/aieo-product/claude-micro-modoki/issues/21

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Usage {
    Write-Output "Usage: $($MyInvocation.ScriptName)"
    Write-Output "  Build dist\ClaudeMicro\ClaudeMicro.exe with PyInstaller from .venv."
    Write-Output "  UNVERIFIED: Windows packaging has not been tested. Report results to issue #21."
    Write-Output "  https://github.com/aieo-product/claude-micro-modoki/issues/21"
}

if ($args.Count -gt 0) {
    if ($args[0] -eq "-h" -or $args[0] -eq "--help") {
        if ($args.Count -ne 1) {
            [Console]::Error.WriteLine("Error: too many arguments.")
            Write-Usage | ForEach-Object { [Console]::Error.WriteLine($_) }
            exit 2
        }
        Write-Usage
        exit 0
    }

    [Console]::Error.WriteLine("Error: unknown argument: $($args[0])")
    Write-Usage | ForEach-Object { [Console]::Error.WriteLine($_) }
    exit 2
}

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    [Console]::Error.WriteLine("Error: ClaudeMicro.exe must be built on Windows.")
    exit 1
}

[Console]::Error.WriteLine("UNVERIFIED: Windows packaging has not been tested.")
[Console]::Error.WriteLine("Reports and fixes: https://github.com/aieo-product/claude-micro-modoki/issues/21")

$RepoDir = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$PyInstaller = Join-Path $RepoDir ".venv\Scripts\pyinstaller.exe"
$SpecFile = Join-Path $RepoDir "pyinstaller\claudemicro.spec"
$DistDir = Join-Path $RepoDir "dist"
$WorkDir = Join-Path $RepoDir "build"
$ConfigDir = Join-Path $WorkDir ".pyinstaller-cache"
$Application = Join-Path $DistDir "ClaudeMicro\ClaudeMicro.exe"

if (-not (Test-Path -LiteralPath $PyInstaller -PathType Leaf)) {
    [Console]::Error.WriteLine("Error: PyInstaller was not found in .venv: $PyInstaller")
    [Console]::Error.WriteLine("Run .\.venv\Scripts\python.exe -m pip install -r requirements-app.txt first.")
    exit 1
}
if (-not (Test-Path -LiteralPath $SpecFile -PathType Leaf)) {
    [Console]::Error.WriteLine("Error: PyInstaller spec was not found: $SpecFile")
    exit 1
}

$HadConfigDir = Test-Path -LiteralPath "Env:PYINSTALLER_CONFIG_DIR"
$PreviousConfigDir = $null
if ($HadConfigDir) {
    $PreviousConfigDir = $env:PYINSTALLER_CONFIG_DIR
}
$HadNativeErrorPreference = Test-Path -LiteralPath "Variable:PSNativeCommandUseErrorActionPreference"
$PreviousNativeErrorPreference = $null
if ($HadNativeErrorPreference) {
    $PreviousNativeErrorPreference = $PSNativeCommandUseErrorActionPreference
}
$BuildExitCode = 1

Push-Location -LiteralPath $RepoDir
try {
    $env:PYINSTALLER_CONFIG_DIR = $ConfigDir
    # PowerShell 7.3+ can otherwise turn a native non-zero status into a
    # terminating error before the exact PyInstaller exit code is captured.
    if ($HadNativeErrorPreference) {
        $PSNativeCommandUseErrorActionPreference = $false
    }
    & $PyInstaller `
        --noconfirm `
        --clean `
        --distpath $DistDir `
        --workpath $WorkDir `
        $SpecFile
    $BuildExitCode = $LASTEXITCODE
}
finally {
    if ($HadNativeErrorPreference) {
        $PSNativeCommandUseErrorActionPreference = $PreviousNativeErrorPreference
    }
    if ($HadConfigDir) {
        $env:PYINSTALLER_CONFIG_DIR = $PreviousConfigDir
    }
    else {
        Remove-Item -LiteralPath "Env:PYINSTALLER_CONFIG_DIR" -ErrorAction SilentlyContinue
    }
    Pop-Location
}

if ($BuildExitCode -ne 0) {
    [Console]::Error.WriteLine("Error: PyInstaller failed with exit code $BuildExitCode.")
    exit $BuildExitCode
}
if (-not (Test-Path -LiteralPath $Application -PathType Leaf)) {
    [Console]::Error.WriteLine("Error: the build completed but $Application was not found.")
    exit 1
}

Write-Output "Build complete: $Application"
Write-Output "UNVERIFIED: This Windows build has not been tested. Report results to issue #21."
