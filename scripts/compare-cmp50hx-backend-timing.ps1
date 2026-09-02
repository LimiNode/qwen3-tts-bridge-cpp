param(
    [Parameter(Mandatory = $true)]
    [string]$GgmlSummaryPath,
    [Parameter(Mandatory = $true)]
    [string]$FasterSummaryPath,
    [string]$OutputPath = ''
)

$ErrorActionPreference = 'Stop'

function Read-ComparisonSummary {
    param([string]$Path, [string]$ExpectedBackend)

    $resolvedPath = (Resolve-Path -LiteralPath $Path).Path
    $summary = Get-Content -LiteralPath $resolvedPath -Raw | ConvertFrom-Json
    if ($ExpectedBackend -eq 'ggml' -and $summary.runtime_backend -ne 'ggml') {
        throw "Expected a native GGML summary: $resolvedPath"
    }
    if ($ExpectedBackend -eq 'faster' -and -not $summary.frozen_c_boundary) {
        throw "Expected a frozen Faster summary: $resolvedPath"
    }
    if (-not $summary.aggregate -or [int]$summary.aggregate.successful_attempts -lt 1) {
        throw "Summary has no successful timing attempts: $resolvedPath"
    }
    if (-not $summary.comparison_contract) {
        throw "Summary has no comparison_contract fingerprint: $resolvedPath"
    }
    [pscustomobject]@{ Path = $resolvedPath; Value = $summary }
}

function Assert-MatchingComparisonContracts {
    param([object]$GgmlContract, [object]$FasterContract)

    $fields = @(
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
    )
    foreach ($field in $fields) {
        if (
            $null -eq $GgmlContract.PSObject.Properties[$field] -or
            $null -eq $FasterContract.PSObject.Properties[$field] -or
            $null -eq $GgmlContract.$field -or
            $null -eq $FasterContract.$field
        ) {
            throw "A/B comparison contract is missing $field."
        }
        if ([string]$GgmlContract.$field -cne [string]$FasterContract.$field) {
            throw "A/B comparison contract mismatch: $field."
        }
    }
    if ([bool]$GgmlContract.etw_capture_enabled -or [bool]$GgmlContract.pcm_capture_enabled) {
        throw 'A/B timing comparison requires ETW and PCM capture to be disabled.'
    }
}

function Get-RelativeDeltaPercent {
    param([double]$Candidate, [double]$Baseline)

    if ($Baseline -le 0.0) { throw 'Timing baseline must be positive.' }
    (($Candidate / $Baseline) - 1.0) * 100.0
}

$ggml = Read-ComparisonSummary $GgmlSummaryPath 'ggml'
$faster = Read-ComparisonSummary $FasterSummaryPath 'faster'
$ggmlAggregate = $ggml.Value.aggregate
$fasterAggregate = $faster.Value.aggregate
Assert-MatchingComparisonContracts `
    -GgmlContract $ggml.Value.comparison_contract `
    -FasterContract $faster.Value.comparison_contract

$report = [ordered]@{
    schema_version = 1
    measurement = 'cross_backend_timing_comparison_not_quality_equivalence'
    ggml_summary = $ggml.Path
    faster_summary = $faster.Path
    comparison_contract = $ggml.Value.comparison_contract
    comparison_scope = [ordered]@{
        primary_metrics = @('real_time_factor', 'first_audio_ms', 'playback_completion', 'playback_proxy')
        diagnostic_only = @('synthesis_ms', 'audio_duration_ms')
        does_not_compare = @('PCM bytes', 'voice quality', 'speaker identity', 'hardware underruns')
    }
    ggml = $ggmlAggregate
    faster = $fasterAggregate
    primary_delta = [ordered]@{
        first_audio_ms_median = [double]$ggmlAggregate.first_audio_ms_median - [double]$fasterAggregate.first_audio_ms_median
        real_time_factor_median = [double]$ggmlAggregate.real_time_factor_median - [double]$fasterAggregate.real_time_factor_median
        real_time_factor_median_relative_percent = Get-RelativeDeltaPercent ([double]$ggmlAggregate.real_time_factor_median) ([double]$fasterAggregate.real_time_factor_median)
        first_audio_ms_median_relative_percent = Get-RelativeDeltaPercent ([double]$ggmlAggregate.first_audio_ms_median) ([double]$fasterAggregate.first_audio_ms_median)
        playback_completed_attempts = [int]$ggmlAggregate.playback_completed_attempts - [int]$fasterAggregate.playback_completed_attempts
        waveout_queue_starvation_proxy_observations_total = [int]$ggmlAggregate.waveout_queue_starvation_proxy_observations_total - [int]$fasterAggregate.waveout_queue_starvation_proxy_observations_total
    }
}

if (-not $OutputPath) {
    $OutputPath = Join-Path (Split-Path -Parent $ggml.Path) 'backend-timing-comparison.json'
}
$report | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $OutputPath -Encoding utf8
Write-Host "summary_json=$OutputPath"
Write-Host 'Cross-backend timing comparison completed; it does not establish quality equivalence.'
