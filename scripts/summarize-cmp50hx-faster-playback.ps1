param(
    [Parameter(Mandatory = $true)]
    [string]$SummaryPath,
    [string]$OutputPath = ''
)

$ErrorActionPreference = 'Stop'

function Get-JsonMetricEvents {
    param([string]$LogPath)

    if (-not (Test-Path -LiteralPath $LogPath -PathType Leaf)) {
        throw "Worker stderr log was not found: $LogPath"
    }
    $rawLog = Get-Content -LiteralPath $LogPath -Raw
    $matches = [regex]::Matches($rawLog, '(?s)qtb_metric\s+(\{.*?\})(?:\r?\n){2}')
    $events = @()
    foreach ($match in $matches) {
        # Native stderr is formatted at the host's console width when redirected.
        # Compact telemetry JSON has no semantic newlines, so join wrapped lines.
        $events += (($match.Groups[1].Value -replace '\r?\n', '') | ConvertFrom-Json)
    }
    $events
}

function Get-Median {
    param([double[]]$Values)

    if ($Values.Count -eq 0) { return $null }
    $sorted = @($Values | Sort-Object)
    $middle = [int]($sorted.Count / 2)
    if ($sorted.Count % 2 -eq 1) { return $sorted[$middle] }
    ($sorted[$middle - 1] + $sorted[$middle]) / 2.0
}

function Get-Percentile {
    param([double[]]$Values, [ValidateRange(0.0, 1.0)][double]$Quantile)

    if ($Values.Count -eq 0) { return $null }
    $sorted = @($Values | Sort-Object)
    $index = [int][Math]::Ceiling($Quantile * $sorted.Count) - 1
    $sorted[[Math]::Max(0, [Math]::Min($index, $sorted.Count - 1))]
}

$resolvedSummary = (Resolve-Path -LiteralPath $SummaryPath).Path
$source = Get-Content -LiteralPath $resolvedSummary -Raw | ConvertFrom-Json
if (-not $source.frozen_c_boundary) {
    throw 'The supplied summary does not contain a frozen-C playback boundary.'
}
$normalAttempts = @($source.normal_attempts)
if ($normalAttempts.Count -eq 0) {
    throw 'The supplied summary contains no normal playback attempts.'
}
$contract = $source.comparison_contract
if (-not $contract) {
    throw 'The supplied summary has no comparison_contract fingerprint.'
}
foreach ($field in @(
        'schema_version',
        'text_sha256',
        'language',
        'speaker',
        'seed',
        'seed_mode',
        'attempts_requested',
        'attempts_completed',
        'playback_prebuffer_chunks',
        'workload_label',
        'etw_capture_enabled',
        'pcm_capture_enabled'
    )) {
    if ($null -eq $contract.PSObject.Properties[$field] -or $null -eq $contract.$field) {
        throw "The supplied summary comparison_contract is missing $field."
    }
}
if ([int]$contract.attempts_completed -ne $normalAttempts.Count) {
    throw 'The supplied summary comparison_contract does not match normal attempts.'
}

$attemptRecords = @()
foreach ($attempt in $normalAttempts) {
    if ([int]$attempt.exit_code -ne 0) {
        throw "Faster playback attempt $($attempt.prefix) failed with exit code $($attempt.exit_code)."
    }
    $finished = @(
        Get-JsonMetricEvents ([string]$attempt.stderr_path) |
            Where-Object { $_.event -eq 'request_finished' } |
            Select-Object -Last 1
    )
    if ($finished.Count -ne 1) {
        throw "Faster playback attempt $($attempt.prefix) has no request_finished metric."
    }
    $attemptRecords += [ordered]@{
        prefix = [string]$attempt.prefix
        synthesis_ms = [double]$finished[0].synthesis_ms
        first_audio_ms = [double]$finished[0].first_audio_ms
        real_time_factor = [double]$finished[0].real_time_factor
        audio_duration_ms = [double]$finished[0].audio_duration_ms
        audio_chunk_count = [int]$finished[0].audio_chunks
        playback_completed = [bool]$attempt.playback_completed
        waveout_queue_starvation_proxy_observations = [int]$attempt.queue_empty_before_later_chunk_count
    }
}

$synthesis = [double[]]@($attemptRecords | ForEach-Object { $_.synthesis_ms })
$firstAudio = [double[]]@($attemptRecords | ForEach-Object { $_.first_audio_ms })
$rtf = [double[]]@($attemptRecords | ForEach-Object { $_.real_time_factor })
$starvation = [int[]]@($attemptRecords | ForEach-Object { $_.waveout_queue_starvation_proxy_observations })
$report = [ordered]@{
    schema_version = 1
    measurement = 'repeated_frozen_faster_playback_not_native_ggml_quality_equivalence'
    source_summary = $resolvedSummary
    comparison_contract = $contract
    frozen_c_boundary = $source.frozen_c_boundary
    aggregate = [ordered]@{
        successful_attempts = $attemptRecords.Count
        synthesis_ms_median = Get-Median $synthesis
        synthesis_ms_p95 = Get-Percentile $synthesis 0.95
        first_audio_ms_median = Get-Median $firstAudio
        first_audio_ms_p95 = Get-Percentile $firstAudio 0.95
        real_time_factor_median = Get-Median $rtf
        real_time_factor_p95 = Get-Percentile $rtf 0.95
        waveout_queue_starvation_proxy_observations_total = [int](($starvation | Measure-Object -Sum).Sum)
        playback_completed_attempts = @($attemptRecords | Where-Object { $_.playback_completed }).Count
    }
    attempts = $attemptRecords
}

if (-not $OutputPath) {
    $OutputPath = Join-Path (Split-Path -Parent $resolvedSummary) 'faster-timing-summary.json'
}
$report | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $OutputPath -Encoding utf8
Write-Host "summary_json=$OutputPath"
Write-Host 'Frozen Faster timing summary completed; quality equivalence with native GGML is not asserted.'
