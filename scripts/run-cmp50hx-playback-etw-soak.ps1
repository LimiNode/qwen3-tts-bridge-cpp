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

    [string]$CudaVisibleDevices = 'GPU-40361931-6cb5-ac58-a059-5ba3e70986fb'
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false

$repo = Split-Path -Parent $PSScriptRoot

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

$player = Resolve-RepoPath $PlayerPath 'Playback client'
$python = Resolve-RepoPath $PythonPath 'Sealed Python runtime'
$model = Resolve-RepoPath $ModelPath 'Model path'
$shadow = Resolve-RepoPath $FasterShadowPath 'Faster shadow source'
$cache = Resolve-RepoPath $RuntimeCachePath 'Runtime cache'
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
        throw 'WPR GPU+Video capture requires an elevated PowerShell session; no ETW recording was started.'
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
    $etl = Join-Path $runDirectory "$Prefix-gpu-video.etl"
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
            Assert-ElevatedWprSession
            $status = @(& $wpr.Source -status 2>&1) -join [Environment]::NewLine
            if ($status -notmatch 'not (running|recording)') {
                throw 'WPR already has an active recording; refusing to stop or replace it.'
            }
            & $wpr.Source -start GPU -start Video -filemode
            if ($LASTEXITCODE -ne 0) {
                throw "WPR could not start GPU+Video recording (exit=$LASTEXITCODE)."
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
            & $wpr.Source -stop $etl
            if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $etl -PathType Leaf)) {
                throw "WPR could not stop GPU+Video recording into $etl."
            }
        }
    }

    if (-not (Test-Path -LiteralPath $metrics -PathType Leaf)) {
        throw "Playback run completed without metrics: $metrics"
    }
    $result = Get-Content -LiteralPath $metrics -Raw | ConvertFrom-Json
    $graphs = (Select-String -LiteralPath $stderr -Pattern 'CUDA graph captured!' -SimpleMatch |
        Measure-Object).Count
    return [ordered]@{
        prefix = $Prefix
        etw_captured = [bool]$CaptureEtw
        metrics_path = $metrics
        stdout_path = $stdout
        stderr_path = $stderr
        etl_path = if ($CaptureEtw) { $etl } else { $null }
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
        $result['outlier'] =
            $result.playback_completed -and
            $result.queue_empty_before_later_chunk_count -ge $QueueEmptyThreshold
        $attemptResults += $result
        if ($result.outlier) {
            $outlier = $result
            break
        }
    }

    $etwFollowup = $null
    if ($null -ne $outlier) {
        $etwFollowup = Invoke-PlaybackRun -Prefix 'outlier-followup-etw' -CaptureEtw
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
        etw_profiles = @('GPU', 'Video')
        queue_empty_threshold = $QueueEmptyThreshold
        normal_attempts = @($attemptResults)
        outlier_detected = ($null -ne $outlier)
        etw_followup = $etwFollowup
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
        Write-Output 'Playback outlier confirmed; WPR GPU+Video follow-up completed.'
    }
}
finally {
    foreach ($name in $environmentNames) {
        [Environment]::SetEnvironmentVariable($name, $previousEnvironment[$name], 'Process')
    }
}
