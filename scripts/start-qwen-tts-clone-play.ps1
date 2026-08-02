[CmdletBinding()]
param(
    [string]$ReferenceAudioPath = "",
    [string]$ReferenceText = "",
    # Keep the built-in default ASCII so Windows PowerShell 5.1 can parse this
    # UTF-8-without-BOM script consistently. Pass Russian text with -Text.
    [string]$Text = "I am your robot. I am your worker. I execute the order now.",
    [switch]$Interactive,
    [switch]$XVectorOnly,
    [string]$VoiceRegistryPath = "",
    [string]$VoiceId = "",
    [ValidateSet("faster", "upstream")]
    [string]$RuntimeBackend = "faster",
    [ValidateRange(0.05, 2.0)]
    [double]$Temperature = 0.45,
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
if (-not [string]::IsNullOrWhiteSpace($VoiceId)) {
    if (-not [string]::IsNullOrWhiteSpace($ReferenceAudioPath) -or
        -not [string]::IsNullOrWhiteSpace($ReferenceText) -or $XVectorOnly) {
        throw "VoiceId cannot be combined with direct reference-audio parameters"
    }
    if ([string]::IsNullOrWhiteSpace($VoiceRegistryPath)) {
        throw "VoiceRegistryPath is required with VoiceId"
    }
}
elseif ([string]::IsNullOrWhiteSpace($ReferenceAudioPath)) {
    throw "ReferenceAudioPath is required unless VoiceId selects a registered profile"
}
elseif (-not $XVectorOnly -and [string]::IsNullOrWhiteSpace($ReferenceText)) {
    throw "ReferenceText is required unless -XVectorOnly is used"
}

$referenceAudio = ""
if (-not [string]::IsNullOrWhiteSpace($ReferenceAudioPath)) {
    $referenceAudio = Resolve-ExistingPath $ReferenceAudioPath "Reference audio"
}
$voiceRegistry = ""
if (-not [string]::IsNullOrWhiteSpace($VoiceRegistryPath)) {
    $voiceRegistry = Resolve-ExistingPath $VoiceRegistryPath "Voice registry"
}
if (Test-Path -LiteralPath $localConfigPath) {
    $runtimeConfig = Get-Content -Raw -LiteralPath $localConfigPath | ConvertFrom-Json
}
else {
    $runtimeConfig = $null
}
if ([string]::IsNullOrWhiteSpace($Python)) {
    if ($null -eq $runtimeConfig) {
        throw "Python was not provided and playback config was not found: $localConfigPath"
    }
    $Python = $runtimeConfig.python
}
$pythonPath = Resolve-ExistingPath $Python "Python"

if ([string]::IsNullOrWhiteSpace($ModelPath)) {
    $cacheRoot = Join-Path $env:USERPROFILE ".cache\huggingface\hub\models--Qwen--Qwen3-TTS-12Hz-1.7B-Base"
    $mainRef = Join-Path $cacheRoot "refs\main"
    $snapshot = $null
    if (Test-Path -LiteralPath $mainRef) {
        $revision = (Get-Content -Raw -LiteralPath $mainRef).Trim()
        if ($revision) {
            $candidate = Join-Path $cacheRoot "snapshots\$revision"
            if (Test-Path -LiteralPath $candidate) {
                $snapshot = Get-Item -LiteralPath $candidate
            }
        }
    }
    if ($null -eq $snapshot) {
        $snapshots = @(Get-ChildItem -LiteralPath (Join-Path $cacheRoot "snapshots") -Directory -ErrorAction SilentlyContinue)
        if ($snapshots.Count -eq 1) {
            $snapshot = $snapshots[0]
        }
    }
    if ($null -eq $snapshot) {
        throw "Base model was not configured and no cached 1.7B Base snapshot was found"
    }
    $ModelPath = $snapshot.FullName
}
$model = Resolve-ExistingPath $ModelPath "Base model"

if ($RuntimeBackend -eq "faster") {
    if ($null -eq $runtimeConfig -or [string]::IsNullOrWhiteSpace($runtimeConfig.faster_qwen_source_path)) {
        throw "faster_qwen_source_path must be set in $localConfigPath for RuntimeBackend=faster"
    }
    $runtimeSource = Resolve-ExistingPath $runtimeConfig.faster_qwen_source_path "FasterQwen source"
}
else {
    $runtimeSource = Join-Path $repoRoot "external\python\Qwen3-TTS-streaming"
    if (-not (Test-Path -LiteralPath $runtimeSource)) {
        throw "Vendored Qwen3-TTS streaming source was not found: $runtimeSource"
    }
}
$env:PYTHONPATH = "$runtimeSource;$repoRoot\worker\src"
$workerArguments = @(
    "-m", "qwen_tts_bridge_worker",
    "qwen",
    "--model-path", $model,
    "--runtime-backend", $RuntimeBackend,
    "--device", "cuda",
    "--dtype", "bfloat16",
    "--attn-implementation", "sdpa",
    "--emit-every-frames", "8",
    "--decode-window-frames", "80",
    "--max-audio-seconds-per-utterance", "30",
    "--temperature", $Temperature
)
if ($voiceRegistry) {
    $workerArguments += @("--voice-registry-path", $voiceRegistry)
}
if ($VoiceId -and $RuntimeBackend -eq "faster") {
    $workerArguments += @(
        "--preload-voice-profiles",
        "--warmup-synthesis",
        "--warmup-voice-id", $VoiceId,
        "--warmup-text", "Voice profile warmup.",
        "--warmup-max-output-chunks", "2"
    )
}
$arguments = @(
    "--worker", $pythonPath,
    "--cwd", $repoRoot,
    "--startup-timeout-ms", "60000"
)
foreach ($workerArgument in $workerArguments) {
    $arguments += @("--worker-arg", $workerArgument)
}
if (-not $Interactive) {
    $arguments += @("--text", $Text)
}
$arguments += @("--language", "Russian")
if ($VoiceId) {
    $arguments += @("--voice-id", $VoiceId)
}
else {
    $arguments += @("--reference-audio", $referenceAudio)
}
if ($ReferenceText -and -not $VoiceId) {
    $arguments += @("--reference-text", $ReferenceText)
}
if ($XVectorOnly) {
    $arguments += "--x-vector-only"
}

& $cliPath @arguments
exit $LASTEXITCODE
