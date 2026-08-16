param(
    [Parameter(Mandatory = $true)]
    [string]$SummaryPath,

    [string]$OutputPath = '',

    [string]$XperfPath = '',

    [ValidateRange(0, 60000000)]
    [int64]$WindowBeforeUs = 1000000,

    [ValidateRange(0, 60000000)]
    [int64]$WindowAfterUs = 100000
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false

function Resolve-ExistingPath {
    param([string]$Path, [string]$Description)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Description was not found: $Path"
    }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Write-JsonAtomically {
    param([string]$Path, [object]$Value)
    if (Test-Path -LiteralPath $Path) {
        throw "Refusing to overwrite existing marker analysis report: $Path"
    }
    $temporary = "$Path.tmp.$PID"
    try {
        [IO.File]::WriteAllText(
            $temporary,
            (($Value | ConvertTo-Json -Depth 10) + [Environment]::NewLine),
            [Text.UTF8Encoding]::new($false))
        Move-Item -LiteralPath $temporary -Destination $Path -ErrorAction Stop
    }
    finally {
        if (Test-Path -LiteralPath $temporary) {
            Remove-Item -LiteralPath $temporary -Force
        }
    }
}

function Get-XperfDumperLines {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Xperf,

        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,

        [Parameter(Mandatory = $true)]
        [string]$LinePattern,

        [Parameter(Mandatory = $true)]
        [string]$Description
    )

    $temporaryOutput = Join-Path ([IO.Path]::GetTempPath()) "cmp50hx-xperf-$PID-$([guid]::NewGuid().ToString('N')).out"
    $temporaryError = Join-Path ([IO.Path]::GetTempPath()) "cmp50hx-xperf-$PID-$([guid]::NewGuid().ToString('N')).err"
    try {
        # xperf emits hundreds of thousands of irrelevant records even for a
        # bounded provider dump. Redirecting first keeps the PowerShell pipeline
        # out of its hot path; only matching records are materialized below.
        & $Xperf @Arguments 1> $temporaryOutput 2> $temporaryError
        if ($LASTEXITCODE -ne 0) {
            $errorText = if (Test-Path -LiteralPath $temporaryError) {
                (Get-Content -LiteralPath $temporaryError -Raw).Trim()
            }
            else { '' }
            throw "xperf $Description dump failed (exit=$LASTEXITCODE). $errorText"
        }

        $lines = New-Object 'System.Collections.Generic.List[string]'
        foreach ($line in [IO.File]::ReadLines($temporaryOutput)) {
            if ($line -match $LinePattern) {
                $lines.Add($line)
            }
        }
        return $lines.ToArray()
    }
    finally {
        Remove-Item -LiteralPath $temporaryOutput, $temporaryError -Force -ErrorAction SilentlyContinue
    }
}

Import-Module (Join-Path $PSScriptRoot 'Cmp50hxEtwTraceAnalysis.psm1') -Force
Import-Module (Join-Path $PSScriptRoot 'Cmp50hxEtwMarkerAnalysis.psm1') -Force

$summaryFile = Resolve-ExistingPath $SummaryPath 'ETW soak summary'
$summary = Get-Content -LiteralPath $summaryFile -Raw | ConvertFrom-Json
if (-not $summary.valid_outlier_etw_evidence) {
    throw 'The summary does not certify valid outlier ETW evidence; refusing marker analysis.'
}
if (-not $summary.etw_followup.etl_usable_for_analysis -or
    -not $summary.etw_followup.playback_markers_present -or
    $summary.etw_followup.event_loss_status -ne 'verified_zero') {
    throw 'The ETW follow-up does not satisfy the zero-loss, semantic, marker-aware evidence gate.'
}

$etlFile = Resolve-ExistingPath $summary.etw_followup.etl_path 'ETL'
$metricsFile = Resolve-ExistingPath $summary.etw_followup.metrics_path 'ETW playback metrics'
$metrics = Get-Content -LiteralPath $metricsFile -Raw | ConvertFrom-Json
if ($metrics.chunks.Count -eq 0) {
    throw 'ETW playback metrics contain no audio chunks; refusing marker analysis.'
}
$expectedMarkerCount = [int]$summary.etw_followup.expected_playback_marker_count
$expectedFromMetrics = 1 + [int]$summary.etw_followup.queue_empty_before_later_chunk_count
if ($expectedMarkerCount -ne $expectedFromMetrics) {
    throw "Summary marker count $expectedMarkerCount does not match request-start plus queue-empty count $expectedFromMetrics."
}
if (-not $OutputPath) {
    $OutputPath = Join-Path (Split-Path -Parent $summaryFile) 'etw-marker-analysis-summary.json'
}

if ($XperfPath) {
    $xperf = Resolve-ExistingPath $XperfPath 'xperf.exe'
}
else {
    $xperfCommand = Get-Command xperf.exe -ErrorAction SilentlyContinue
    if ($null -eq $xperfCommand) {
        throw 'xperf.exe was not found. Install the Windows Performance Toolkit.'
    }
    $xperf = $xperfCommand.Source
}

$processReport = @(& $xperf -i $etlFile -a process 2>&1)
if ($LASTEXITCODE -ne 0) {
    throw "xperf process report failed (exit=$LASTEXITCODE)."
}
$worker = Get-Cmp50hxWorkerProcess -ProcessReport ($processReport -join [Environment]::NewLine)
if ($worker.worker_process_status -ne 'resolved') {
    throw "Could not resolve one worker Python process from the ETL. Players=$($worker.player_pids -join ',') workers=$($worker.worker_pids -join ',')"
}
$workerPid = [int]$worker.worker_pids[0]

$cswitchReport = @(& $xperf -i $etlFile -a cswitch -process 2>&1)
if ($LASTEXITCODE -ne 0) {
    throw "xperf CSwitch report failed (exit=$LASTEXITCODE)."
}
$workerCswitchPresent = ($cswitchReport -join [Environment]::NewLine) -match "python\.exe\s+\(\s*$workerPid\)"

$markLines = @(Get-XperfDumperLines `
        -Xperf $xperf `
        -Arguments @('-i', $etlFile, '-a', 'dumper', '-provider', '{ce1dbfb4-137e-4da6-87b0-3f59aa102cbc}') `
        -LinePattern '^\s*Mark,\s*\d+,\s*qwen_tts_bridge\.playback\.' `
        -Description 'PerfInfo marker')
$markers = @(Get-Cmp50hxPlaybackMarkers -DumperLines $markLines)
$markerValidation = Assert-Cmp50hxPlaybackMarkerSequence `
    -Markers $markers `
    -ExpectedMarkerCount $expectedMarkerCount
$windows = @(New-Cmp50hxPlaybackMarkerWindows `
        -Markers $markers `
        -WindowBeforeUs $WindowBeforeUs `
        -WindowAfterUs $WindowAfterUs)
$combinedStart = [int64](($windows | Measure-Object -Property start_timestamp_us -Minimum).Minimum)
$combinedEnd = [int64](($windows | Measure-Object -Property end_timestamp_us -Maximum).Maximum)

$dxgOutput = Join-Path ([IO.Path]::GetTempPath()) "cmp50hx-xperf-$PID-$([guid]::NewGuid().ToString('N')).out"
$dxgError = Join-Path ([IO.Path]::GetTempPath()) "cmp50hx-xperf-$PID-$([guid]::NewGuid().ToString('N')).err"
try {
    & $xperf -i $etlFile -a dumper -range $combinedStart $combinedEnd `
        -provider '{802ec45a-1e99-4b83-9920-87c98277ba9d}' 1> $dxgOutput 2> $dxgError
    if ($LASTEXITCODE -ne 0) {
        $errorText = (Get-Content -LiteralPath $dxgError -Raw -ErrorAction SilentlyContinue).Trim()
        throw "xperf bounded DxgKrnl dump failed (exit=$LASTEXITCODE). $errorText"
    }
    # Do not materialize the complete xperf output: this bounded interval can
    # still contain hundreds of thousands of unrelated GPU records.
    $windowSummaries = @(Get-Cmp50hxMarkerWindowDxgKrnlSummary `
            -DumperLines ([IO.File]::ReadLines($dxgOutput)) `
            -Windows $windows `
            -WorkerPid $workerPid)
}
finally {
    Remove-Item -LiteralPath $dxgOutput, $dxgError -Force -ErrorAction SilentlyContinue
}
$workerDxgKrnlEventCount = [int](($windowSummaries | Measure-Object -Property worker_dxgkrnl_event_count -Sum).Sum)
$attribution = Get-Cmp50hxWorkerAttributionStatus `
    -WorkerCswitchPresent $workerCswitchPresent `
    -WorkerDxgKrnlEventCount $workerDxgKrnlEventCount
if (-not $attribution.worker_attribution_valid) {
    throw "Worker attribution is incomplete in marker windows: $($attribution.invalid_reasons -join ',')"
}

$etl = Get-Item -LiteralPath $etlFile
$report = [ordered]@{
    schema_version = 1
    analysis = 'cmp50hx_etw_marker_window_attribution'
    analysis_scope = 'marker_aligned_bounded_etl'
    source_summary_path = $summaryFile
    etl_path = $etlFile
    etl_size_bytes = $etl.Length
    valid_outlier_etw_evidence = [bool]$summary.valid_outlier_etw_evidence
    playback = [ordered]@{
        measurement = 'WaveOut queue starvation proxy; not a hardware underrun counter'
        queue_empty_before_later_chunk_count = [int]$summary.etw_followup.queue_empty_before_later_chunk_count
        total_audio_duration_ms = [double]$summary.etw_followup.total_audio_duration_ms
    }
    marker_validation = $markerValidation
    bounded_dump = [ordered]@{
        start_timestamp_us = $combinedStart
        end_timestamp_us = $combinedEnd
        window_before_us = $WindowBeforeUs
        window_after_us = $WindowAfterUs
    }
    worker = $worker
    cswitch = [ordered]@{
        analysis_scope = 'full_bounded_etl'
        worker_process_present = [bool]$workerCswitchPresent
    }
    marker_windows = $windowSummaries
    attribution = $attribution
    conclusion = 'The report establishes marker-aligned DxgKrnl event presence and worker attribution only. It does not determine a GPU stall, preemption, scheduling gap, or root cause.'
}
Write-JsonAtomically -Path $OutputPath -Value $report
Write-Output "analysis_json=$OutputPath"
