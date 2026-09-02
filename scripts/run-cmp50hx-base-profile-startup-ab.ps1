[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$PlayerPath,

    [Parameter(Mandatory = $true)]
    [string]$PythonPath,

    [Parameter(Mandatory = $true)]
    [string]$BaseModelPath,

    [Parameter(Mandatory = $true)]
    [string]$VoiceRegistryPath,

    [Parameter(Mandatory = $true)]
    [string]$VoiceId,

    [Parameter(Mandatory = $true)]
    [string]$RuntimeCachePath,

    [string]$FasterSourcePath = 'external\python\faster-qwen3-tts',

    [string]$Text = 'CMP 50HX registered voice profile startup latency check.',

    [string]$Language = 'Russian',

    [ValidateRange(1, 10)]
    [int]$Attempts = 3,

    [string]$OutputRoot = 'tmp\cmp50hx-base-profile-startup-ab',

    [string]$CudaVisibleDevices = 'GPU-40361931-6cb5-ac58-a059-5ba3e70986fb'
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$runner = Join-Path $PSScriptRoot 'run-cmp50hx-playback-etw-soak.ps1'

function Resolve-ExistingPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [string]$Description
    )

    $candidate = if ([IO.Path]::IsPathRooted($Path)) {
        $Path
    }
    else {
        Join-Path $repoRoot $Path
    }
    if (-not (Test-Path -LiteralPath $candidate)) {
        throw "$Description was not found: $candidate"
    }
    return (Resolve-Path -LiteralPath $candidate).Path
}

function Get-Median {
    param([double[]]$Values)

    if ($Values.Count -eq 0) {
        return $null
    }
    $ordered = @($Values | Sort-Object)
    $middle = [int][Math]::Floor($ordered.Count / 2)
    if (($ordered.Count % 2) -eq 1) {
        return $ordered[$middle]
    }
    return ($ordered[$middle - 1] + $ordered[$middle]) / 2.0
}

function Read-CaseResult {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Label,

        [Parameter(Mandatory = $true)]
        [string]$CaseRoot,

        [Parameter(Mandatory = $true)]
        [int]$ExpectedAttempts
    )

    $summaryPath = Get-ChildItem -LiteralPath $CaseRoot -Recurse -Filter summary.json |
        Select-Object -ExpandProperty FullName -First 1
    if (-not $summaryPath) {
        throw "$Label did not produce summary.json."
    }
    $summary = Get-Content -LiteralPath $summaryPath -Raw | ConvertFrom-Json
    $attempts = @($summary.normal_attempts)
    if ($attempts.Count -ne $ExpectedAttempts) {
        throw "$Label reported $($attempts.Count) normal attempts; expected $ExpectedAttempts."
    }

    $firstArrivals = [System.Collections.Generic.List[double]]::new()
    $playbackStarts = [System.Collections.Generic.List[double]]::new()
    foreach ($attempt in $attempts) {
        if ($attempt.exit_code -ne 0 -or -not $attempt.playback_completed) {
            throw "$Label contains a failed or incomplete playback attempt."
        }
        if ($attempt.queue_empty_before_later_chunk_count -ne 0) {
            throw "$Label recorded a later-chunk queue-starvation proxy observation."
        }
        $metrics = Get-Content -LiteralPath $attempt.metrics_path -Raw | ConvertFrom-Json
        if ($metrics.audio_chunk_count -lt 2) {
            throw "$Label produced fewer than two PCM chunks; prebuffer timing is unavailable."
        }
        $firstArrivals.Add([double]$metrics.chunks[0].arrival_ms)
        $playbackStarts.Add([double]$metrics.playback_started_ms)
    }

    return [ordered]@{
        label = $Label
        summary_json = $summaryPath
        attempts = $ExpectedAttempts
        first_pcm_arrival_ms = [ordered]@{
            samples = @($firstArrivals)
            median = Get-Median @($firstArrivals)
        }
        waveout_start_ms = [ordered]@{
            samples = @($playbackStarts)
            median = Get-Median @($playbackStarts)
        }
        later_chunk_queue_starvation_proxy_count = 0
    }
}

$player = Resolve-ExistingPath $PlayerPath 'Playback client'
$python = Resolve-ExistingPath $PythonPath 'Python runtime'
$baseModel = Resolve-ExistingPath $BaseModelPath 'Base model'
$voiceRegistry = Resolve-ExistingPath $VoiceRegistryPath 'Voice registry'
$runtimeCache = Resolve-ExistingPath $RuntimeCachePath 'Runtime cache'
$fasterSource = Resolve-ExistingPath $FasterSourcePath 'Faster source'

$outputDirectory = if ([IO.Path]::IsPathRooted($OutputRoot)) {
    $OutputRoot
}
else {
    Join-Path $repoRoot $OutputRoot
}
$runDirectory = Join-Path $outputDirectory ([DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ'))
New-Item -ItemType Directory -Path $runDirectory -Force | Out-Null

$common = @{
    Attempts = $Attempts
    PlayerPath = $player
    PythonPath = $python
    ModelPath = $baseModel
    VoiceRegistryPath = $voiceRegistry
    VoiceId = $VoiceId
    RuntimeCachePath = $runtimeCache
    FasterSourcePath = $fasterSource
    Text = $Text
    Language = $Language
    PlaybackPrebufferChunks = 2
    WorkerSynthesisWarmup = $true
    WorkerWarmupPasses = 1
    WorkerWarmupUnboundedPasses = 1
    WorkerWarmupMaxOutputChunks = 2
    EmitEveryFrames = 16
    CodecRightPaddedDecode = $true
    CodecRightPaddedCudaGraph = $true
    CodecRightPaddedWindowFrames = 48
    SkipEtwFollowup = $true
    CudaVisibleDevices = $CudaVisibleDevices
}

$baselineRoot = Join-Path $runDirectory 'fixed-16'
& $runner @common -OutputRoot $baselineRoot
if ($LASTEXITCODE -ne 0) {
    throw "Fixed-16 Base-profile playback exited with $LASTEXITCODE."
}
$baseline = Read-CaseResult -Label 'fixed_16' -CaseRoot $baselineRoot -ExpectedAttempts $Attempts

$candidateRoot = Join-Path $runDirectory 'startup-schedule-8-23'
& $runner @common -OutputRoot $candidateRoot -EmitChunkSchedule 8,23
if ($LASTEXITCODE -ne 0) {
    throw "Base startup schedule 8,23 playback exited with $LASTEXITCODE."
}
$candidate = Read-CaseResult -Label 'startup_schedule_8_23' -CaseRoot $candidateRoot -ExpectedAttempts $Attempts

$firstPcmDelta = $candidate.first_pcm_arrival_ms.median - $baseline.first_pcm_arrival_ms.median
$playbackStartDelta = $candidate.waveout_start_ms.median - $baseline.waveout_start_ms.median
$report = [ordered]@{
    schema_version = 1
    scope = 'cmp50hx_base_profile_startup_ab'
    generated_at_utc = [DateTime]::UtcNow.ToString('o')
    voice_id = $VoiceId
    text = $Text
    language = $Language
    fixed_runtime = [ordered]@{
        emit_every_frames = 16
        right_padded_decode_window_frames = 48
        manual_codec_cuda_graph = $true
        playback_prebuffer_chunks = 2
    }
    baseline = $baseline
    startup_schedule_8_23 = $candidate
    median_delta_ms = [ordered]@{
        first_pcm_arrival = [Math]::Round($firstPcmDelta, 3)
        waveout_start = [Math]::Round($playbackStartDelta, 3)
    }
    interpretation = 'The only runtime difference is Base emission cadence: fixed 16 frames versus 8 then 23 frames. Negative deltas improve request-to-first-PCM or WaveOut-start latency. Both arms require zero later-chunk queue-starvation-proxy observations; this proxy is not a hardware-underrun counter.'
}
$reportPath = Join-Path $runDirectory 'report.json'
$report | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $reportPath -Encoding utf8
Write-Output "report_json=$reportPath"
Write-Output 'Base-profile startup A/B completed.'
