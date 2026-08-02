[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$ReferenceAudioPath,
    [string]$ReferenceText = "",
    # Keep the built-in default ASCII so Windows PowerShell 5.1 can parse this
    # UTF-8-without-BOM script consistently. Pass Russian text with -Text.
    [string]$Text = "I am your robot. I am your worker. I execute the order now.",
    [switch]$XVectorOnly,
    [string]$Python = "",
    [string]$ModelPath = "",
    [string]$BuildDirectory = "build"
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$localConfigPath = Join-Path $repoRoot "config\playback-runtime.local.json"
$cliPath = Join-Path (Join-Path $repoRoot $BuildDirectory) "qwen_tts_play.exe"

function Resolve-ExistingPath([string]$PathValue, [string]$Name) {
    if ([string]::IsNullOrWhiteSpace($PathValue) -or -not (Test-Path -LiteralPath $PathValue)) {
        throw "$Name was not found: $PathValue"
    }
    return (Resolve-Path -LiteralPath $PathValue).Path
}

if (-not (Test-Path -LiteralPath $cliPath)) {
    throw "qwen_tts_play.exe was not found: $cliPath"
}
if (-not $XVectorOnly -and [string]::IsNullOrWhiteSpace($ReferenceText)) {
    throw "ReferenceText is required unless -XVectorOnly is used"
}

$referenceAudio = Resolve-ExistingPath $ReferenceAudioPath "Reference audio"
if ([string]::IsNullOrWhiteSpace($Python)) {
    if (-not (Test-Path -LiteralPath $localConfigPath)) {
        throw "Python was not provided and playback config was not found: $localConfigPath"
    }
    $Python = (Get-Content -Raw -LiteralPath $localConfigPath | ConvertFrom-Json).python
}
$pythonPath = Resolve-ExistingPath $Python "Python"

if ([string]::IsNullOrWhiteSpace($ModelPath)) {
    $cacheRoot = Join-Path $env:USERPROFILE ".cache\huggingface\hub\models--Qwen--Qwen3-TTS-12Hz-1.7B-Base\snapshots"
    $snapshot = Get-ChildItem -LiteralPath $cacheRoot -Directory -ErrorAction SilentlyContinue |
        Sort-Object Name -Descending |
        Select-Object -First 1
    if ($null -eq $snapshot) {
        throw "Base model was not configured and no cached 1.7B Base snapshot was found"
    }
    $ModelPath = $snapshot.FullName
}
$model = Resolve-ExistingPath $ModelPath "Base model"

$env:PYTHONPATH = "$repoRoot\worker\src"
$workerArguments = @(
    "-m", "qwen_tts_bridge_worker",
    "qwen",
    "--model-path", $model,
    "--runtime-backend", "upstream",
    "--device", "cuda",
    "--dtype", "bfloat16",
    "--attn-implementation", "sdpa",
    "--emit-every-frames", "8",
    "--decode-window-frames", "80",
    "--max-audio-seconds-per-utterance", "30"
)
$arguments = @("--worker", $pythonPath, "--cwd", $repoRoot)
foreach ($workerArgument in $workerArguments) {
    $arguments += @("--worker-arg", $workerArgument)
}
$arguments += @(
    "--text", $Text,
    "--language", "Russian",
    "--reference-audio", $referenceAudio
)
if ($ReferenceText) {
    $arguments += @("--reference-text", $ReferenceText)
}
if ($XVectorOnly) {
    $arguments += "--x-vector-only"
}

& $cliPath @arguments
exit $LASTEXITCODE
