param(
    [string]$Python = "py",
    [string[]]$PythonArgs,
    [switch]$UseVenv,
    [string]$VenvPath = ".venv-packaging",
    [string]$WorkerCommand = "dist/QwenTTSBridge/worker-python/qwen_tts_worker.cmd",
    [Parameter(Mandatory = $true)]
    [string]$ModelPath,
    [Parameter(Mandatory = $true)]
    [string]$ModelManifest,
    [ValidateSet("upstream", "faster")]
    [string]$RuntimeBackend = "faster",
    [string]$Device = "cuda",
    [string]$Dtype = "bfloat16",
    [string]$AttnImplementation = "sdpa",
    [int]$TimeoutSeconds = 600,
    [string]$Text = "Portable worker real Qwen smoke test.",
    [string]$Language = "English",
    [string]$Speaker = "serena"
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

    return Join-Path (Resolve-RepoPath $Path) "Scripts/python.exe"
}

function Assert-PackagingPythonVersion {
    $VersionOutput = & $Python @PythonArgs -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to run portable worker test Python."
    }

    $Version = ($VersionOutput | Select-Object -First 1).Trim()
    if ($Version -ne $RequiredPythonVersion) {
        throw "Portable worker test Python must be $RequiredPythonVersion; selected Python is $Version."
    }
}

if ($UseVenv) {
    $VenvPython = Resolve-VenvPython $VenvPath
    if (-not (Test-Path -LiteralPath $VenvPython)) {
        throw "Python virtual environment was not found at $VenvPath. Run scripts/setup-python-packaging.ps1 -UseVenv first."
    }

    $Python = $VenvPython
    $PythonArgs = @()
}

Assert-PackagingPythonVersion

$ResolvedWorkerCommand = Resolve-RepoPath $WorkerCommand
$ResolvedModelPath = Resolve-RepoPath $ModelPath
$ResolvedModelManifest = Resolve-RepoPath $ModelManifest
if (-not (Test-Path -LiteralPath $ResolvedWorkerCommand)) {
    throw "Portable worker command was not found: $ResolvedWorkerCommand"
}
if (-not (Test-Path -LiteralPath $ResolvedModelPath)) {
    throw "Model path was not found: $ResolvedModelPath"
}
if (-not (Test-Path -LiteralPath $ResolvedModelManifest)) {
    throw "Model manifest was not found: $ResolvedModelManifest"
}

$PreviousPythonPath = $env:PYTHONPATH

try {
    $WorkerRoot = Split-Path -Parent $ResolvedWorkerCommand
    $DoctorCommand = Join-Path $WorkerRoot "qwen_tts_doctor.cmd"
    if (-not (Test-Path -LiteralPath $DoctorCommand)) {
        throw "Portable worker doctor was not found: $DoctorCommand"
    }

    & $DoctorCommand `
        --model-path $ResolvedModelPath `
        --model-manifest $ResolvedModelManifest `
        --require-cuda
    if ($LASTEXITCODE -ne 0) {
        throw "Portable worker doctor failed."
    }

    $WorkerSrc = Resolve-RepoPath "worker/src"
    if ([string]::IsNullOrWhiteSpace($env:PYTHONPATH)) {
        $env:PYTHONPATH = $WorkerSrc
    }
    else {
        $env:PYTHONPATH = "$WorkerSrc$([IO.Path]::PathSeparator)$env:PYTHONPATH"
    }

    & $Python @PythonArgs `
        "tests/python/verify_packaged_worker.py" `
        $ResolvedWorkerCommand `
        --engine qwen `
        --model-path $ResolvedModelPath `
        --runtime-backend $RuntimeBackend `
        --device $Device `
        --dtype $Dtype `
        --attn-implementation $AttnImplementation `
        --prefill-backend eager `
        --no-compile `
        --no-cuda-graphs `
        --require-natural-eos `
        --timeout-seconds "$TimeoutSeconds" `
        --text $Text `
        --language $Language `
        --speaker $Speaker
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}
finally {
    $env:PYTHONPATH = $PreviousPythonPath
}
