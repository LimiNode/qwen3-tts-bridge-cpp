[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ProbePath,

    [Parameter(Mandatory = $true)]
    [string]$WorkerPath,

    [string]$Text = '',

    [string]$TextFile = '',

    [string[]]$WorkerArgument = @(),

    [string]$OutputRoot = 'tmp\speech-animation-qwen-e2e',

    [string]$Language = 'auto',
    [string]$Speaker = '',
    [string]$VoiceId = '',
    [string]$ReferenceAudio = '',
    [string]$ReferenceText = '',
    [switch]$XVectorOnly,
    [Nullable[UInt64]]$Seed,
    [ValidateRange(1, 4096)]
    [int]$QueueCapacity = 64,
    [ValidateRange(0, 1000)]
    [int]$ConsumerPollMs = 2,
    [ValidateRange(1000, 600000)]
    [int]$StartupTimeoutMs = 30000,
    [ValidateRange(1000, 3600000)]
    [int]$RequestTimeoutMs = 120000
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false

function Resolve-ExistingPath {
    param(
        [Parameter(Mandatory = $true)] [string]$Path,
        [Parameter(Mandatory = $true)] [string]$Description
    )
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Description was not found: $Path"
    }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Invoke-Probe {
    param(
        [Parameter(Mandatory = $true)] [ValidateSet('on', 'off')] [string]$Adapter,
        [Parameter(Mandatory = $true)] [string]$OutputPath
    )

    $arguments = @(
        '--adapter', $Adapter,
        '--worker', $WorkerPath,
        '--language', $Language,
        '--queue-capacity', $QueueCapacity,
        '--consumer-poll-ms', $ConsumerPollMs,
        '--startup-timeout-ms', $StartupTimeoutMs,
        '--request-timeout-ms', $RequestTimeoutMs,
        '--output-json', $OutputPath
    )
    if ($TextFile) { $arguments += @('--text-file', $TextFile) }
    else { $arguments += @('--text', $Text) }
    if ($Speaker) { $arguments += @('--speaker', $Speaker) }
    if ($VoiceId) { $arguments += @('--voice-id', $VoiceId) }
    if ($ReferenceAudio) { $arguments += @('--reference-audio', $ReferenceAudio) }
    if ($ReferenceText) { $arguments += @('--reference-text', $ReferenceText) }
    if ($XVectorOnly) { $arguments += '--x-vector-only' }
    if ($null -ne $Seed) { $arguments += @('--seed', [UInt64]$Seed) }
    foreach ($workerArgumentValue in $WorkerArgument) {
        $arguments += @('--worker-arg', $workerArgumentValue)
    }

    Write-Host "Running speech-animation probe ($Adapter)..."
    $probeOutput = & $ProbePath @arguments
    if ($LASTEXITCODE -ne 0) {
        if ($probeOutput) {
            $probeOutput | Select-Object -Last 20 | Write-Host
        }
        throw "speech-animation probe ($Adapter) failed with exit code $LASTEXITCODE."
    }
    $report = Get-Content -LiteralPath $OutputPath -Raw | ConvertFrom-Json
    if (-not $report.success) {
        throw "speech-animation probe ($Adapter) produced a non-accepted receipt: $OutputPath"
    }
    return $report
}

$ProbePath = Resolve-ExistingPath $ProbePath 'Speech-animation probe'
$WorkerPath = Resolve-ExistingPath $WorkerPath 'Qwen worker'
if (($Text -and $TextFile) -or (-not $Text -and -not $TextFile)) {
    throw 'Supply exactly one of -Text or -TextFile.'
}
if ($TextFile) {
    $TextFile = Resolve-ExistingPath $TextFile 'UTF-8 text file'
}
$root = if ([IO.Path]::IsPathRooted($OutputRoot)) {
    $OutputRoot
}
else {
    Join-Path (Get-Location) $OutputRoot
}
New-Item -ItemType Directory -Path $root -Force | Out-Null
$offPath = Join-Path $root 'adapter-off.json'
$onPath = Join-Path $root 'adapter-on.json'
$summaryPath = Join-Path $root 'ab-summary.json'
foreach ($path in @($offPath, $onPath, $summaryPath)) {
    if (Test-Path -LiteralPath $path) {
        throw "Refusing to overwrite existing output: $path"
    }
}

$off = Invoke-Probe -Adapter off -OutputPath $offPath
$on = Invoke-Probe -Adapter on -OutputPath $onPath

$firstPcmDelta = $null
$firstDownstreamDelta = $null
if ($null -ne $off.first_pcm_ms -and $null -ne $on.first_pcm_ms) {
    $firstPcmDelta = [double]$on.first_pcm_ms - [double]$off.first_pcm_ms
}
if ($null -ne $off.first_downstream_pcm_ms -and $null -ne $on.first_downstream_pcm_ms) {
    $firstDownstreamDelta = [double]$on.first_downstream_pcm_ms - [double]$off.first_downstream_pcm_ms
}

$summary = [ordered]@{
    schema_version = 1
    experiment = 'qwen_speech_animation_ab'
    text = $off.text
    text_source = $off.text_source
    text_file = $off.text_file
    adapter_off = [ordered]@{
        receipt_json = $offPath
        first_pcm_ms = $off.first_pcm_ms
        first_downstream_pcm_ms = $off.first_downstream_pcm_ms
        success = $off.success
    }
    adapter_on = [ordered]@{
        receipt_json = $onPath
        first_pcm_ms = $on.first_pcm_ms
        first_downstream_pcm_ms = $on.first_downstream_pcm_ms
        first_animation_span_ms = $on.first_animation_span_ms
        adapter_mean_ms = $on.adapter_mean_ms
        adapter_max_ms = $on.adapter_max_ms
        queue_high_water = $on.queue_high_water
        queue_full_count = $on.queue_full_count
        pcm_timeline_contiguous = $on.pcm_timeline_contiguous
        animation_timeline_contiguous = $on.animation_timeline_contiguous
        last_audio_span_matches_pcm_end = $on.last_audio_span_matches_pcm_end
        terminal_fade_anchored_at_pcm_end = $on.terminal_fade_anchored_at_pcm_end
        active_span_count = $on.active_span_count
        silence_span_count = $on.silence_span_count
        mouth_open_min = $on.mouth_open_min
        mouth_open_max = $on.mouth_open_max
        mouth_open_mean = $on.mouth_open_mean
        success = $on.success
    }
    deltas = [ordered]@{
        first_pcm_ms = $firstPcmDelta
        first_downstream_pcm_ms = $firstDownstreamDelta
    }
}
$summary | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $summaryPath -Encoding utf8
Write-Output "summary_json=$summaryPath"
