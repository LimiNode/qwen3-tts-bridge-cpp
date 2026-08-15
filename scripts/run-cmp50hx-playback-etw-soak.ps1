param(
    [ValidateRange(1, 20)]
    [int]$Attempts = 3,

    [ValidateRange(1, 100)]
    [int]$QueueEmptyThreshold = 1,

    [string]$Text = 'This is a physical playback soak for the frozen Faster C configuration.',

    [string]$Speaker = 'ryan',

    [string]$PlayerPath = '',

    [string]$PythonPath = '',

    [string]$ModelPath = '',

    [string]$FasterShadowPath = '',

    [string]$RuntimeCachePath = '',

    [string]$OutputRoot = '',

    [string]$WprProfilePath = '',

    [string]$XperfPath = '',

    [string]$CudaVisibleDevices = 'GPU-40361931-6cb5-ac58-a059-5ba3e70986fb'
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false

$repo = Split-Path -Parent $PSScriptRoot
Import-Module (Join-Path $PSScriptRoot 'Cmp50hxEtwEvidence.psm1') -Force

function Resolve-RepoPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [string]$Description
    )

    $resolved = if ([IO.Path]::IsPathRooted($Path)) {
        $Path
    }
    else {
        Join-Path $repo $Path
    }
    if (-not (Test-Path -LiteralPath $resolved)) {
        throw "$Description was not found: $resolved"
    }
    return (Resolve-Path -LiteralPath $resolved).Path
}

if (-not $PlayerPath) {
    $PlayerPath = 'build\cmp50hx-diagnostic-mingw\qwen_tts_play.exe'
}
if (-not $PythonPath) {
    $PythonPath = 'tmp\QwenTTSBridge-technical-beta-r3\QwenTTSBridge-technical-beta-r3\worker\python\python.exe'
}
if (-not $ModelPath) {
    $ModelPath = 'tmp\cmp50hx-r3-external-models\Qwen3-TTS-12Hz-0.6B-CustomVoice'
}
if (-not $FasterShadowPath) {
    $FasterShadowPath = 'tmp\cmp50hx-faster-eager-shadow'
}
if (-not $RuntimeCachePath) {
    $RuntimeCachePath = 'tmp\cmp50hx-r3-runtime-cache'
}
if (-not $OutputRoot) {
    $OutputRoot = 'tmp\cmp50hx-playback-etw-soak'
}
if (-not $WprProfilePath) {
    $WprProfilePath = 'scripts\profiles\cmp50hx-dxgkrnl-scheduler.wprp'
}

$player = Resolve-RepoPath $PlayerPath 'Playback client'
$python = Resolve-RepoPath $PythonPath 'Sealed Python runtime'
$model = Resolve-RepoPath $ModelPath 'Model path'
$shadow = Resolve-RepoPath $FasterShadowPath 'Faster shadow source'
$cache = Resolve-RepoPath $RuntimeCachePath 'Runtime cache'
$wprProfile = Resolve-RepoPath $WprProfilePath 'WPR profile'
$outputDirectory = if ([IO.Path]::IsPathRooted($OutputRoot)) {
    $OutputRoot
}
else {
    Join-Path $repo $OutputRoot
}

$wpr = Get-Command wpr.exe -ErrorAction SilentlyContinue
if ($null -eq $wpr) {
    throw 'wpr.exe was not found. Install the Windows Performance Toolkit before requesting an ETW follow-up.'
}
if ($XperfPath) {
    $xperf = Resolve-RepoPath $XperfPath 'xperf.exe'
}
else {
    $xperfCommand = Get-Command xperf.exe -ErrorAction SilentlyContinue
    if ($null -eq $xperfCommand) {
        throw 'xperf.exe was not found. Install the Windows Performance Toolkit before requesting an ETW follow-up.'
    }
    $xperf = $xperfCommand.Source
}

$runId = '{0}-{1}' -f [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ'), $PID
$runDirectory = Join-Path $outputDirectory $runId
New-Item -ItemType Directory -Path $runDirectory -ErrorAction Stop | Out-Null

$environmentNames = @(
    'CUDA_VISIBLE_DEVICES', 'PYTHONHOME', 'PYTHONPATH', 'PYTHONNOUSERSITE',
    'PYTHONDONTWRITEBYTECODE', 'HF_HOME', 'HF_HUB_CACHE', 'TRANSFORMERS_CACHE',
    'TORCH_HOME', 'XDG_CACHE_HOME', 'HF_HUB_OFFLINE', 'TRANSFORMERS_OFFLINE',
    'QTB_FASTER_EAGER_DIAGNOSTIC', 'QTB_FASTER_MLP_FP32_ISLAND',
    'QTB_FASTER_RESIDUAL_CARRIER_FP32', 'QTB_FASTER_GRAPH_RESIDUAL_CARRIER_FP32',
    'QTB_FASTER_MLP_NARROW_GATE_UP_FP16', 'QTB_FASTER_GRAPH_CARRIER_PROOF_PATH',
    'QTB_FASTER_GRAPH_FINITE_CHECKER', 'QTB_FASTER_GRAPH_FINITE_PROOF_PATH',
    'QTB_FASTER_STALL_TELEMETRY', 'QTB_FASTER_DIAGNOSTIC_TRACE_PATH',
    'QTB_FASTER_DIAGNOSTIC_START_REQUEST', 'QTB_NSYS_CUDA_PROFILER_PAIR'
)
$previousEnvironment = @{}
foreach ($name in $environmentNames) {
    $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}

function Set-FrozenCEnvironment {
    $env:CUDA_VISIBLE_DEVICES = $CudaVisibleDevices
    $env:PYTHONHOME = Split-Path -Parent $python
    $env:PYTHONPATH = "$shadow;$repo\worker\src"
    $env:PYTHONNOUSERSITE = '1'
    $env:PYTHONDONTWRITEBYTECODE = '1'
    $env:HF_HOME = Join-Path $cache 'huggingface'
    $env:HF_HUB_CACHE = Join-Path $cache 'huggingface\hub'
    $env:TRANSFORMERS_CACHE = Join-Path $cache 'transformers'
    $env:TORCH_HOME = Join-Path $cache 'torch'
    $env:XDG_CACHE_HOME = $cache
    $env:HF_HUB_OFFLINE = '1'
    $env:TRANSFORMERS_OFFLINE = '1'
    $env:QTB_FASTER_EAGER_DIAGNOSTIC = '0'
    $env:QTB_FASTER_MLP_FP32_ISLAND = '1'
    $env:QTB_FASTER_RESIDUAL_CARRIER_FP32 = '0'
    $env:QTB_FASTER_GRAPH_RESIDUAL_CARRIER_FP32 = '1'
    $env:QTB_FASTER_MLP_NARROW_GATE_UP_FP16 = '1'
    $env:QTB_FASTER_GRAPH_CARRIER_PROOF_PATH = ''
    $env:QTB_FASTER_GRAPH_FINITE_CHECKER = '0'
    $env:QTB_FASTER_GRAPH_FINITE_PROOF_PATH = ''
    $env:QTB_FASTER_STALL_TELEMETRY = '0'
    $env:QTB_FASTER_DIAGNOSTIC_TRACE_PATH = ''
    $env:QTB_FASTER_DIAGNOSTIC_START_REQUEST = ''
    $env:QTB_NSYS_CUDA_PROFILER_PAIR = '0'
}

function Assert-ElevatedWprSession {
    $principal = [Security.Principal.WindowsPrincipal]::new(
        [Security.Principal.WindowsIdentity]::GetCurrent())
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'WPR DxgKrnl capture requires an elevated PowerShell session; no ETW recording was started.'
    }
}

function Get-EtlValidation {
    param(
        [Parameter(Mandatory = $true)]
        [string]$EtlPath,

        [Parameter(Mandatory = $true)]
        [string]$TraceStatsPath,

        [Parameter(Mandatory = $true)]
        [string]$TraceStatsDetailPath
    )

    if (-not (Test-Path -LiteralPath $EtlPath -PathType Leaf)) {
        return [ordered]@{
            etl_transport_valid = $false
            etl_size_bytes = $null
            tracestats_path = $null
            tracestats_detail_path = $null
            event_loss_status = 'unparseable'
            lost_buffer_count = $null
            lost_event_count = $null
            dxgkrnl_present = $false
            dxgkrnl_event_count = $null
            cswitch_present = $false
            scheduler_event_presence_verified = $false
            scheduler_event_types = @()
            scheduler_event_count = $null
            semantic_trace_valid = $false
        }
    }

    $etl = Get-Item -LiteralPath $EtlPath
    if ($etl.Length -le 0) {
        return [ordered]@{
            etl_transport_valid = $false
            etl_size_bytes = $etl.Length
            tracestats_path = $null
            tracestats_detail_path = $null
            event_loss_status = 'unparseable'
            lost_buffer_count = $null
            lost_event_count = $null
            dxgkrnl_present = $false
            dxgkrnl_event_count = $null
            cswitch_present = $false
            scheduler_event_presence_verified = $false
            scheduler_event_types = @()
            scheduler_event_count = $null
            semantic_trace_valid = $false
        }
    }

    $traceStats = @(& $xperf -i $EtlPath -a tracestats 2>&1)
    $traceStatsExitCode = $LASTEXITCODE
    [IO.File]::WriteAllText(
        $TraceStatsPath,
        (($traceStats -join [Environment]::NewLine) + [Environment]::NewLine),
        [Text.UTF8Encoding]::new($false))

    $traceStatsDetail = @(& $xperf -i $EtlPath -a tracestats -detail 2>&1)
    $traceStatsDetailExitCode = $LASTEXITCODE
    [IO.File]::WriteAllText(
        $TraceStatsDetailPath,
        (($traceStatsDetail -join [Environment]::NewLine) + [Environment]::NewLine),
        [Text.UTF8Encoding]::new($false))
    if ($traceStatsExitCode -ne 0 -or $traceStatsDetailExitCode -ne 0) {
        return [ordered]@{
            etl_transport_valid = $false
            etl_size_bytes = $etl.Length
            tracestats_path = $TraceStatsPath
            tracestats_detail_path = $TraceStatsDetailPath
            event_loss_status = 'unparseable'
            lost_buffer_count = $null
            lost_event_count = $null
            dxgkrnl_present = $false
            dxgkrnl_event_count = $null
            cswitch_present = $false
            scheduler_event_presence_verified = $false
            scheduler_event_types = @()
            scheduler_event_count = $null
            semantic_trace_valid = $false
        }
    }

    $eventLoss = Get-Cmp50hxEventLossStatus -TraceStatsText ($traceStats -join [Environment]::NewLine)
    $semantic = Get-Cmp50hxTraceSemanticStatus -TraceStatsText ($traceStatsDetail -join [Environment]::NewLine)
    return [ordered]@{
        etl_transport_valid = $true
        etl_size_bytes = $etl.Length
        tracestats_path = $TraceStatsPath
        tracestats_detail_path = $TraceStatsDetailPath
        event_loss_status = $eventLoss.event_loss_status
        lost_buffer_count = $eventLoss.lost_buffer_count
        lost_event_count = $eventLoss.lost_event_count
        dxgkrnl_present = $semantic.dxgkrnl_present
        dxgkrnl_event_count = $semantic.dxgkrnl_event_count
        cswitch_present = $semantic.cswitch_present
        scheduler_event_presence_verified = $semantic.scheduler_event_presence_verified
        scheduler_event_types = $semantic.scheduler_event_types
        scheduler_event_count = $semantic.scheduler_event_count
        semantic_trace_valid = $semantic.semantic_trace_valid
    }
}

function Invoke-PlaybackRun {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Prefix,

        [switch]$CaptureEtw
    )

    $metrics = Join-Path $runDirectory "$Prefix-playback-metrics.json"
    $stdout = Join-Path $runDirectory "$Prefix.stdout.log"
    $stderr = Join-Path $runDirectory "$Prefix.stderr.log"
    $etl = Join-Path $runDirectory "$Prefix-gpu.etl"
    $wprStopReport = Join-Path $runDirectory "$Prefix-wpr-stop.txt"
    $traceStats = Join-Path $runDirectory "$Prefix-xperf-tracestats.txt"
    $traceStatsDetail = Join-Path $runDirectory "$Prefix-xperf-tracestats-detail.txt"
    $arguments = @(
        '--worker', $python, '--cwd', $repo,
        '--worker-arg', '-B', '--worker-arg', '-P', '--worker-arg', '-s',
        '--worker-arg', '-m', '--worker-arg', 'qwen_tts_bridge_worker',
        '--worker-arg', 'qwen', '--worker-arg', '--model-path', '--worker-arg', $model,
        '--worker-arg', '--runtime-backend', '--worker-arg', 'faster',
        '--worker-arg', '--device', '--worker-arg', 'cuda:0',
        '--worker-arg', '--dtype', '--worker-arg', 'float16',
        '--worker-arg', '--attn-implementation', '--worker-arg', 'sdpa',
        '--worker-arg', '--prefill-backend', '--worker-arg', 'eager',
        '--worker-arg', '--emit-every-frames', '--worker-arg', '8',
        '--worker-arg', '--decode-window-frames', '--worker-arg', '80',
        '--worker-arg', '--no-compile', '--worker-arg', '--no-cuda-graphs',
        '--worker-arg', '--seed', '--worker-arg', '20260806',
        '--worker-arg', '--seed-mode', '--worker-arg', 'fixed',
        '--text', $Text, '--speaker', $Speaker,
        '--startup-timeout-ms', '240000',
        '--playback-metrics-file', $metrics
    )

    $wprStarted = $false
    try {
        if ($CaptureEtw) {
            $arguments += '--etw-playback-markers'
            Assert-ElevatedWprSession
            $status = @(& $wpr.Source -status 2>&1) -join [Environment]::NewLine
            if ($status -notmatch 'not (running|recording)') {
                throw 'WPR already has an active recording; refusing to stop or replace it.'
            }
            & $wpr.Source -start "$wprProfile!CMP50HX-DxgKrnl-Scheduler" -filemode
            if ($LASTEXITCODE -ne 0) {
                throw "WPR could not start minimal DxgKrnl recording (exit=$LASTEXITCODE)."
            }
            $wprStarted = $true
        }

        $previousErrorActionPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = 'Continue'
            & $player @arguments 1> $stdout 2> $stderr
            $exitCode = $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $previousErrorActionPreference
        }
        if ($exitCode -ne 0) {
            throw "Frozen-C physical playback run failed with exit code $exitCode."
        }
    }
    finally {
        if ($wprStarted) {
            $stopOutput = @(& $wpr.Source -stop $etl 2>&1)
            [IO.File]::WriteAllText(
                $wprStopReport,
                (($stopOutput -join [Environment]::NewLine) + [Environment]::NewLine),
                [Text.UTF8Encoding]::new($false))
            if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $etl -PathType Leaf)) {
                throw "WPR could not stop minimal DxgKrnl recording into $etl. $($stopOutput -join ' ')"
            }
        }
    }

    if (-not (Test-Path -LiteralPath $metrics -PathType Leaf)) {
        throw "Playback run completed without metrics: $metrics"
    }
    $result = Get-Content -LiteralPath $metrics -Raw | ConvertFrom-Json
    if ($CaptureEtw -and -not $result.etw_playback_markers_enabled) {
        throw 'ETW follow-up completed without requested playback marker instrumentation.'
    }
    $graphs = (Select-String -LiteralPath $stderr -Pattern 'CUDA graph captured!' -SimpleMatch |
        Measure-Object).Count
    $etlValidation = if ($CaptureEtw) {
        Get-EtlValidation -EtlPath $etl -TraceStatsPath $traceStats `
            -TraceStatsDetailPath $traceStatsDetail
    }
    else { $null }
    return [ordered]@{
        prefix = $Prefix
        etw_captured = [bool]$CaptureEtw
        metrics_path = $metrics
        stdout_path = $stdout
        stderr_path = $stderr
        etl_path = if ($CaptureEtw) { $etl } else { $null }
        wpr_stop_report_path = if ($CaptureEtw) { $wprStopReport } else { $null }
        etl_size_bytes = if ($CaptureEtw) { $etlValidation.etl_size_bytes } else { $null }
        tracestats_path = if ($CaptureEtw) { $etlValidation.tracestats_path } else { $null }
        tracestats_detail_path = if ($CaptureEtw) { $etlValidation.tracestats_detail_path } else { $null }
        etl_transport_valid = if ($CaptureEtw) { $etlValidation.etl_transport_valid } else { $null }
        event_loss_status = if ($CaptureEtw) { $etlValidation.event_loss_status } else { $null }
        lost_buffer_count = if ($CaptureEtw) { $etlValidation.lost_buffer_count } else { $null }
        lost_event_count = if ($CaptureEtw) { $etlValidation.lost_event_count } else { $null }
        dxgkrnl_present = if ($CaptureEtw) { $etlValidation.dxgkrnl_present } else { $null }
        dxgkrnl_event_count = if ($CaptureEtw) { $etlValidation.dxgkrnl_event_count } else { $null }
        cswitch_present = if ($CaptureEtw) { $etlValidation.cswitch_present } else { $null }
        scheduler_event_presence_verified = if ($CaptureEtw) {
            $etlValidation.scheduler_event_presence_verified
        }
        else { $null }
        scheduler_event_types = if ($CaptureEtw) { $etlValidation.scheduler_event_types } else { $null }
        scheduler_event_count = if ($CaptureEtw) { $etlValidation.scheduler_event_count } else { $null }
        semantic_trace_valid = if ($CaptureEtw) { $etlValidation.semantic_trace_valid } else { $null }
        event_loss_verified_zero = if ($CaptureEtw) {
            $etlValidation.event_loss_status -eq 'verified_zero'
        }
        else { $null }
        etl_usable_for_analysis = if ($CaptureEtw) {
            $etlValidation.etl_transport_valid -and
            $etlValidation.event_loss_status -eq 'verified_zero' -and
            $etlValidation.semantic_trace_valid
        }
        else { $null }
        exit_code = $exitCode
        playback_completed = [bool]$result.playback_completed
        audio_chunk_count = [int]$result.audio_chunk_count
        total_audio_duration_ms = [double]$result.total_audio_duration_ms
        queue_empty_before_later_chunk_count = [int]$result.queue_empty_before_later_chunk_count
        faster_graph_capture_count = $graphs
    }
}

try {
    Set-FrozenCEnvironment
    $attemptResults = @()
    $outlier = $null
    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        $result = Invoke-PlaybackRun -Prefix ("normal-{0:D2}" -f $attempt)
        $result['outlier'] = Test-Cmp50hxPlaybackOutlier `
            -PlaybackCompleted $result.playback_completed `
            -QueueEmptyBeforeLaterChunkCount $result.queue_empty_before_later_chunk_count `
            -QueueEmptyThreshold $QueueEmptyThreshold
        $attemptResults += $result
        if ($result.outlier) {
            $outlier = $result
            break
        }
    }

    $etwFollowup = $null
    if ($null -ne $outlier) {
        $etwFollowup = Invoke-PlaybackRun -Prefix 'outlier-followup-etw' -CaptureEtw
        $etwFollowup['outlier'] = Test-Cmp50hxPlaybackOutlier `
            -PlaybackCompleted $etwFollowup.playback_completed `
            -QueueEmptyBeforeLaterChunkCount $etwFollowup.queue_empty_before_later_chunk_count `
            -QueueEmptyThreshold $QueueEmptyThreshold
    }

    $summary = [ordered]@{
        schema_version = 1
        run_id = $runId
        frozen_c_boundary = [ordered]@{
            layer2_gate_up_dtype = 'float16'
            layer2_product_down_dtype = 'float32'
            residual_and_rmsnorm_dtype = 'float32'
            normalized_branch_dtype = 'float16'
            faster_internal_graphs = 'normal runtime path'
            eager_numerical_trace = $false
            graph_finite_checker = $false
            stall_telemetry = $false
            etw_on_normal_runs = $false
        }
        playback_measurement = 'WaveOut queue starvation proxy; not a hardware underrun counter'
        etw_profile = 'CMP50HX-DxgKrnl-Scheduler'
        etw_profile_path = $wprProfile
        queue_empty_threshold = $QueueEmptyThreshold
        normal_attempts = @($attemptResults)
        outlier_detected = ($null -ne $outlier)
        etw_followup = $etwFollowup
        valid_outlier_etw_evidence = ($null -ne $etwFollowup) -and
            $etwFollowup.etl_transport_valid -and
            $etwFollowup.event_loss_verified_zero -and
            $etwFollowup.semantic_trace_valid -and
            $etwFollowup.outlier
    }
    $summaryPath = Join-Path $runDirectory 'summary.json'
    [IO.File]::WriteAllText(
        $summaryPath,
        (($summary | ConvertTo-Json -Depth 8) + [Environment]::NewLine),
        [Text.UTF8Encoding]::new($false))
    Write-Output "summary_json=$summaryPath"
    if ($null -eq $outlier) {
        Write-Output "No playback outlier in $Attempts bounded frozen-C attempts; WPR was not launched."
    }
    else {
        if (-not $etwFollowup.etl_usable_for_analysis) {
            Write-Error "ETL validation failed (transport_valid=$($etwFollowup.etl_transport_valid), event_loss_status=$($etwFollowup.event_loss_status), semantic_trace_valid=$($etwFollowup.semantic_trace_valid)); ETL is not valid evidence."
            exit 5
        }
        if (-not $etwFollowup.outlier) {
            Write-Output 'Playback outlier confirmed in a normal run; WPR follow-up is a usable normal/reference ETL, not captured outlier evidence.'
        }
        else {
            Write-Output 'Playback outlier reproduced under WPR; minimal DxgKrnl ETW evidence is valid.'
        }
    }
}
finally {
    foreach ($name in $environmentNames) {
        [Environment]::SetEnvironmentVariable($name, $previousEnvironment[$name], 'Process')
    }
}
