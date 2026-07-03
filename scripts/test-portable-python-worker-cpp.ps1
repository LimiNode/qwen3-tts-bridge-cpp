param(
    [string]$Python = "py",
    [string[]]$PythonArgs,
    [switch]$UseVenv,
    [string]$VenvPath = ".venv-packaging",
    [string]$ExampleExe = "build/default/Release/qwen_tts_save_wav.exe",
    [string]$WorkerRoot = "dist/QwenTTSBridge/worker-python",
    [string]$OutputPath = "tmp/portable-python-worker-cpp.wav",
    [int]$TimeoutSeconds = 30,
    [int]$MockChunks = 1,
    [int]$MockChunkMs = 100
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot
$RequiredPythonVersion = "3.11"

if (-not $PSBoundParameters.ContainsKey("PythonArgs")) {
    if ($Python -eq "py") {
        $PythonArgs = @("-3.11")
    }
    else {
        $PythonArgs = @()
    }
}

function Resolve-RepoPath {
    param(
        [string]$Path
    )

    if ([IO.Path]::IsPathRooted($Path)) {
        return [IO.Path]::GetFullPath($Path)
    }

    return [IO.Path]::GetFullPath((Join-Path $RepoRoot $Path))
}

function Resolve-VenvPython {
    param(
        [string]$Path
    )

    $ResolvedVenvPath = Resolve-RepoPath $Path
    return Join-Path $ResolvedVenvPath "Scripts/python.exe"
}

function Invoke-ProjectPython {
    param(
        [string[]]$Arguments
    )

    & $Python @PythonArgs @Arguments
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

function Assert-PackagingPythonVersion {
    $VersionOutput = & $Python @PythonArgs -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to run portable worker C++ smoke Python. Install Python $RequiredPythonVersion or pass -Python/-PythonArgs explicitly."
    }

    $Version = ($VersionOutput | Select-Object -First 1).Trim()
    if ($Version -ne $RequiredPythonVersion) {
        throw "Portable worker C++ smoke Python must be $RequiredPythonVersion; selected Python is $Version. Recreate $VenvPath with Python $RequiredPythonVersion or pass -Python/-PythonArgs explicitly."
    }
}

if ($UseVenv) {
    $VenvPython = Resolve-VenvPython $VenvPath
    if (-not (Test-Path -LiteralPath $VenvPython)) {
        $Message = "Python virtual environment was not found at $VenvPath. " +
            "Run scripts/setup-python-packaging.ps1 -UseVenv first."
        throw $Message
    }

    $Python = $VenvPython
    $PythonArgs = @()
}

Assert-PackagingPythonVersion

$ResolvedExampleExe = Resolve-RepoPath $ExampleExe
$ResolvedWorkerRoot = Resolve-RepoPath $WorkerRoot
$ResolvedOutputPath = Resolve-RepoPath $OutputPath
$WorkerPython = Join-Path $ResolvedWorkerRoot "python/python.exe"
$WorkerSitePackages = Join-Path $ResolvedWorkerRoot "python/Lib/site-packages"

if (-not (Test-Path -LiteralPath $ResolvedExampleExe)) {
    throw "qwen_tts_save_wav executable was not found: $ResolvedExampleExe"
}
if (-not (Test-Path -LiteralPath $WorkerPython)) {
    throw "Portable worker python.exe was not found: $WorkerPython"
}
if (-not (Test-Path -LiteralPath $WorkerSitePackages)) {
    throw "Portable worker site-packages was not found: $WorkerSitePackages"
}

$OutputParent = Split-Path -Parent $ResolvedOutputPath
if (-not [string]::IsNullOrWhiteSpace($OutputParent)) {
    New-Item -ItemType Directory -Force -Path $OutputParent | Out-Null
}
if (Test-Path -LiteralPath $ResolvedOutputPath) {
    Remove-Item -LiteralPath $ResolvedOutputPath -Force
}

$PreviousPythonHome = $env:PYTHONHOME
$PreviousPythonPath = $env:PYTHONPATH
$PreviousPythonNoUserSite = $env:PYTHONNOUSERSITE
$PreviousPythonDontWriteBytecode = $env:PYTHONDONTWRITEBYTECODE

try {
    $env:PYTHONHOME = Join-Path $ResolvedWorkerRoot "python"
    $env:PYTHONPATH = $WorkerSitePackages
    $env:PYTHONNOUSERSITE = "1"
    $env:PYTHONDONTWRITEBYTECODE = "1"

    $ExampleArgs = @(
        "--worker",
        $WorkerPython,
        "--worker-arg",
        "-B",
        "--worker-arg",
        "-P",
        "--worker-arg",
        "-s",
        "--worker-arg",
        "-m",
        "--worker-arg",
        "qwen_tts_bridge_worker",
        "--worker-arg",
        "mock",
        "--worker-arg",
        "--chunks",
        "--worker-arg",
        "$MockChunks",
        "--worker-arg",
        "--chunk-ms",
        "--worker-arg",
        "$MockChunkMs",
        "--output",
        $ResolvedOutputPath,
        "--text",
        "Portable Python worker C++ smoke test.",
        "--request-timeout-ms",
        "$($TimeoutSeconds * 1000)"
    )

    & $ResolvedExampleExe @ExampleArgs
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}
finally {
    $env:PYTHONHOME = $PreviousPythonHome
    $env:PYTHONPATH = $PreviousPythonPath
    $env:PYTHONNOUSERSITE = $PreviousPythonNoUserSite
    $env:PYTHONDONTWRITEBYTECODE = $PreviousPythonDontWriteBytecode
}

Invoke-ProjectPython @(
    "tests/python/verify_wav.py",
    $ResolvedOutputPath,
    "--sample-rate",
    "24000",
    "--channels",
    "1",
    "--bits-per-sample",
    "16",
    "--min-data-bytes",
    "1"
)

Write-Host "portable Python worker C++ smoke test passed: $ResolvedOutputPath"
