param(
    [Parameter(Mandatory = $true)]
    [string]$ModelPath,
    [string]$Python = "py",
    [string[]]$PythonArgs,
    [switch]$UseVenv,
    [string]$VenvPath = ".venv-packaging",
    [string]$WorkerExe = "dist/QwenTTSBridge/worker-python/qwen_tts_worker.cmd",
    [int]$TimeoutSeconds = 1200,
    [int]$Requests = 2,
    [string]$Device = "cuda",
    [string]$Dtype = "auto",
    [string]$AttnImplementation = "",
    [int]$EmitEveryFrames = 8,
    [int]$DecodeWindowFrames = 80,
    [int]$OverlapSamples = 0,
    [switch]$EnableStreamingOptimizations,
    [switch]$NoCompile,
    [switch]$NoCudaGraphs,
    [string]$CompileMode = "reduce-overhead",
    [switch]$NoCompileCodebookPredictor,
    [switch]$NoCompileTalker,
    [switch]$WarmupSynthesis,
    [string]$WarmupText = "Warmup.",
    [string]$WarmupLanguage = "auto",
    [string]$WarmupSpeaker = "",
    [string]$WarmupInstruction = "",
    [string]$Text = "Packaged Qwen worker benchmark request.",
    [string]$Language = "auto",
    [string]$Speaker = "",
    [string]$Instruction = ""
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

function Assert-PackagingPythonVersion {
    $VersionOutput = & $Python @PythonArgs -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to run benchmark Python. Install Python $RequiredPythonVersion or pass -Python/-PythonArgs explicitly."
    }

    $Version = ($VersionOutput | Select-Object -First 1).Trim()
    if ($Version -ne $RequiredPythonVersion) {
        throw "Benchmark Python must be $RequiredPythonVersion; selected Python is $Version."
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

$WorkerSrc = Resolve-RepoPath "worker/src"
if ([string]::IsNullOrWhiteSpace($env:PYTHONPATH)) {
    $env:PYTHONPATH = $WorkerSrc
}
else {
    $env:PYTHONPATH = "$WorkerSrc$([IO.Path]::PathSeparator)$env:PYTHONPATH"
}

$Arguments = @(
    "tests/python/benchmark_packaged_worker.py",
    (Resolve-RepoPath $WorkerExe),
    "--engine",
    "qwen",
    "--model-path",
    (Resolve-RepoPath $ModelPath),
    "--device",
    $Device,
    "--dtype",
    $Dtype,
    "--timeout-seconds",
    "$TimeoutSeconds",
    "--requests",
    "$Requests",
    "--text",
    $Text,
    "--language",
    $Language,
    "--emit-every-frames",
    "$EmitEveryFrames",
    "--decode-window-frames",
    "$DecodeWindowFrames",
    "--overlap-samples",
    "$OverlapSamples"
)

if (-not [string]::IsNullOrWhiteSpace($AttnImplementation)) {
    $Arguments += @("--attn-implementation", $AttnImplementation)
}
if ($EnableStreamingOptimizations) {
    $Arguments += @("--enable-streaming-optimizations")
}
if ($NoCompile) {
    $Arguments += @("--no-compile")
}
if ($NoCudaGraphs) {
    $Arguments += @("--no-cuda-graphs")
}
if (-not [string]::IsNullOrWhiteSpace($CompileMode)) {
    $Arguments += @("--compile-mode", $CompileMode)
}
if ($NoCompileCodebookPredictor) {
    $Arguments += @("--no-compile-codebook-predictor")
}
if ($NoCompileTalker) {
    $Arguments += @("--no-compile-talker")
}
if ($WarmupSynthesis) {
    $Arguments += @("--warmup-synthesis")
}
if (-not [string]::IsNullOrWhiteSpace($WarmupText)) {
    $Arguments += @("--warmup-text", $WarmupText)
}
if (-not [string]::IsNullOrWhiteSpace($WarmupLanguage)) {
    $Arguments += @("--warmup-language", $WarmupLanguage)
}
if (-not [string]::IsNullOrWhiteSpace($WarmupSpeaker)) {
    $Arguments += @("--warmup-speaker", $WarmupSpeaker)
}
if (-not [string]::IsNullOrWhiteSpace($WarmupInstruction)) {
    $Arguments += @("--warmup-instruction", $WarmupInstruction)
}
if (-not [string]::IsNullOrWhiteSpace($Speaker)) {
    $Arguments += @("--speaker", $Speaker)
}
if (-not [string]::IsNullOrWhiteSpace($Instruction)) {
    $Arguments += @("--instruction", $Instruction)
}

& $Python @PythonArgs @Arguments
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
