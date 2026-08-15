param(
    [Parameter(Mandatory = $true)]
    [string]$SummaryPath,

    [string]$OutputPath = '',

    [string]$XperfPath = ''
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false

function Resolve-ExistingPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [string]$Description
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Description was not found: $Path"
    }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Write-JsonAtomically {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [object]$Value
    )

    if (Test-Path -LiteralPath $Path) {
        throw "Refusing to overwrite existing analysis report: $Path"
    }
    $temporary = "$Path.tmp.$PID"
    try {
        [IO.File]::WriteAllText(
            $temporary,
            (($Value | ConvertTo-Json -Depth 8) + [Environment]::NewLine),
            [Text.UTF8Encoding]::new($false))
        Move-Item -LiteralPath $temporary -Destination $Path -ErrorAction Stop
    }
    finally {
        if (Test-Path -LiteralPath $temporary) {
            Remove-Item -LiteralPath $temporary -Force
        }
    }
}

$modulePath = Join-Path $PSScriptRoot 'Cmp50hxEtwTraceAnalysis.psm1'
Import-Module $modulePath -Force

$summaryFile = Resolve-ExistingPath $SummaryPath 'ETW soak summary'
$summary = Get-Content -LiteralPath $summaryFile -Raw | ConvertFrom-Json
if (-not $summary.valid_outlier_etw_evidence) {
    throw 'The summary does not certify valid outlier ETW evidence; refusing attribution analysis.'
}
$etlFile = Resolve-ExistingPath $summary.etw_followup.etl_path 'ETL'
$metricsFile = Resolve-ExistingPath $summary.etw_followup.metrics_path 'ETW playback metrics'
$metrics = Get-Content -LiteralPath $metricsFile -Raw | ConvertFrom-Json
if ($metrics.chunks.Count -eq 0) {
    throw 'ETW playback metrics contain no audio chunks; refusing attribution analysis.'
}
if (-not $OutputPath) {
    $OutputPath = Join-Path (Split-Path -Parent $summaryFile) 'etw-attribution-summary.json'
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

$dxgLines = New-Object 'System.Collections.Generic.List[string]'
& $xperf -i $etlFile -a dumper -provider '{802EC45A-1E99-4B83-9920-87C98277BA9D}' 2>&1 |
    ForEach-Object {
        if ($_ -match "^Microsoft-Windows-DxgKrnl/[^/]+/.*python\.exe\s+\(\s*$workerPid\)") {
            $dxgLines.Add($_)
        }
    }
if ($LASTEXITCODE -ne 0) {
    throw "xperf DxgKrnl dump failed (exit=$LASTEXITCODE)."
}
$dxgKrnl = Get-Cmp50hxDxgKrnlEventSummary -DumperLines $dxgLines.ToArray() -WorkerPid $workerPid
$attribution = Get-Cmp50hxWorkerAttributionStatus `
    -WorkerCswitchPresent $workerCswitchPresent `
    -WorkerDxgKrnlEventCount $dxgKrnl.worker_dxgkrnl_event_count
if (-not $attribution.worker_attribution_valid) {
    throw "Worker attribution is incomplete: $($attribution.invalid_reasons -join ',')"
}

$etl = Get-Item -LiteralPath $etlFile
$report = [ordered]@{
    schema_version = 1
    analysis = 'cmp50hx_etw_worker_attribution'
    analysis_scope = 'full_bounded_etl'
    source_summary_path = $summaryFile
    etl_path = $etlFile
    etl_size_bytes = $etl.Length
    valid_outlier_etw_evidence = [bool]$summary.valid_outlier_etw_evidence
    playback = [ordered]@{
        queue_empty_before_later_chunk_count = [int]$summary.etw_followup.queue_empty_before_later_chunk_count
        total_audio_duration_ms = [double]$summary.etw_followup.total_audio_duration_ms
    }
    worker = $worker
    cswitch = [ordered]@{
        worker_process_present = [bool]$workerCswitchPresent
    }
    dxgkrnl = $dxgKrnl
    attribution = $attribution
    conclusion = 'The report establishes ETW data presence and worker attribution only; it does not determine the stall root cause.'
}
Write-JsonAtomically -Path $OutputPath -Value $report
Write-Output "analysis_json=$OutputPath"
