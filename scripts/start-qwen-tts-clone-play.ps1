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
    [ValidateSet("default", "cmp50hx-ultra-low-latency", "cmp50hx-low-latency", "cmp50hx-safe")]
    [string]$RuntimeProfile = "default",
    [ValidateRange(0.05, 2.0)]
    [double]$Temperature = 0.45,
    [switch]$StyleExperiment,
    [string]$Python = "",
    [string]$ModelPath = "",
    [string]$FasterSourcePath = "",
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
    if ([string]::IsNullOrWhiteSpace($FasterSourcePath)) {
        if ($null -eq $runtimeConfig -or [string]::IsNullOrWhiteSpace($runtimeConfig.faster_qwen_source_path)) {
            throw "FasterSourcePath was not provided and faster_qwen_source_path is not set in $localConfigPath"
        }
        $FasterSourcePath = $runtimeConfig.faster_qwen_source_path
    }
    $runtimeSource = Resolve-ExistingPath $FasterSourcePath "FasterQwen source"
}
else {
    $runtimeSource = Join-Path $repoRoot "external\python\Qwen3-TTS-streaming"
    if (-not (Test-Path -LiteralPath $runtimeSource)) {
        throw "Vendored Qwen3-TTS streaming source was not found: $runtimeSource"
    }
}
$env:PYTHONPATH = "$runtimeSource;$repoRoot\worker\src"
$emitEveryFrames = 8
$emitChunkSchedule = @()
$decodeWindowFrames = 80
$maxSeqLen = 2048
$dtype = "bfloat16"
switch ($RuntimeProfile) {
    "cmp50hx-ultra-low-latency" {
        # Fastest accepted CMP 50HX profile: first E3 chunk, then steady E4.
        $emitEveryFrames = 4
        $emitChunkSchedule = @(3, 4)
        $decodeWindowFrames = 29
        $maxSeqLen = 448
        $dtype = "float16"
    }
    "cmp50hx-low-latency" {
        # Bounded CMP 50HX profile: E4 + W33 + one-chunk playback prebuffer.
        $emitEveryFrames = 4
        $decodeWindowFrames = 33
        $maxSeqLen = 768
        $dtype = "float16"
    }
    "cmp50hx-safe" {
        # Sustained-rate CMP 50HX fallback: E8 + W33 + one-chunk prebuffer.
        $emitEveryFrames = 8
        $decodeWindowFrames = 33
        $maxSeqLen = 2048
        $dtype = "float16"
    }
}
$maxDecodeInputFrames = 25 + $emitEveryFrames
if ($RuntimeProfile -ne "default") {
    $env:QTB_FASTER_MLP_FP32_ISLAND = "1"
    $env:QTB_FASTER_GRAPH_RESIDUAL_CARRIER_FP32 = "1"
    $env:QTB_FASTER_MLP_NARROW_GATE_UP_FP16 = "1"
    $env:QTB_FASTER_CODEC_RIGHT_PADDED_DECODE = "1"
    $env:QTB_FASTER_CODEC_RIGHT_PADDED_DECODE_WINDOW_FRAMES = "$decodeWindowFrames"
    $env:QTB_FASTER_CODEC_RIGHT_PADDED_MAX_DECODE_INPUT_FRAMES = "$maxDecodeInputFrames"
    $env:QTB_FASTER_CODEC_RIGHT_PADDED_CUDA_GRAPH = "1"
    $env:QTB_FASTER_BASE_REFERENCE_CONTEXT_BOOTSTRAP = "1"
}
$workerArguments = @(
    "-m", "qwen_tts_bridge_worker",
    "qwen",
    "--model-path", $model,
    "--runtime-backend", $RuntimeBackend,
    "--device", "cuda",
    "--dtype", $dtype,
    "--attn-implementation", "sdpa",
    "--max-seq-len", $maxSeqLen,
    "--emit-every-frames", $emitEveryFrames,
    "--decode-window-frames", $decodeWindowFrames,
    "--max-audio-seconds-per-utterance", "30",
    "--temperature", $Temperature
)
if ($RuntimeProfile -ne "default") {
    $workerArguments += @("--runtime-profile", $RuntimeProfile)
}
if ($emitChunkSchedule.Count -gt 0) {
    $workerArguments += @("--emit-chunk-schedule", ($emitChunkSchedule -join ','))
}
if ($voiceRegistry) {
    $workerArguments += @("--voice-registry-path", $voiceRegistry)
}
if ($StyleExperiment) {
    $workerArguments += "--allow-request-sampling-overrides"
}
if ($VoiceId -and $RuntimeBackend -eq "faster") {
    # The warmup request prepares only the selected profile. Preloading the
    # entire local registry is unnecessary and can exceed its bounded LRU cache.
    $workerArguments += @(
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

# Keep startup latency policy explicit and reproducible for the acceptance
# profiles. The player still owns physical playback and may be replaced by a
# different sink in applications.
$arguments += @("--playback-prebuffer-chunks", "1")

& $cliPath @arguments
exit $LASTEXITCODE
