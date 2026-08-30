[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$PlayerPath,

    [Parameter(Mandatory = $true)]
    [string]$PythonPath,

    [Parameter(Mandatory = $true)]
    [string]$CustomVoiceModelPath,

    [Parameter(Mandatory = $true)]
    [string]$RuntimeCachePath,

    [string]$FasterSourcePath = 'external\python\faster-qwen3-tts',

    [string]$BaseModelPath = '',

    [string]$VoiceRegistryPath = '',

    [string]$VoiceId = '',

    [string]$OutputRoot = 'tmp\real-model-release-acceptance',

    [ValidateRange(2, 8)]
    [int]$PersistentRequests = 4,

    [string]$CudaVisibleDevices = 'GPU-40361931-6cb5-ac58-a059-5ba3e70986fb',

    [switch]$SkipPhysicalPlayback
)

$ErrorActionPreference = 'Stop'
# The real worker uses stderr for diagnostics. Capture it with the native exit
# code instead of letting PowerShell turn an ordinary worker diagnostic into a
# premature script exception.
$PSNativeCommandUseErrorActionPreference = $false
$repoRoot = Split-Path -Parent $PSScriptRoot

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

function Write-Json {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [object]$Value
    )

    $Value | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $Path -Encoding utf8
}

function Invoke-WorkerBenchmark {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Model,

        [Parameter(Mandatory = $true)]
        [string]$RequestShapesPath,

        [string]$Registry = '',

        [string]$WarmupVoiceId = '',

        [string]$Label
    )

    $arguments = @(
        'tests/python/benchmark_packaged_worker.py', $python,
        '--worker-prefix-arg=-B', '--worker-prefix-arg=-P', '--worker-prefix-arg=-s',
        '--worker-prefix-arg=-m', '--worker-prefix-arg=qwen_tts_bridge_worker',
        '--engine', 'qwen', '--model-path', $Model,
        '--runtime-backend', 'faster', '--device', 'cuda:0', '--dtype', 'float16',
        '--attn-implementation', 'sdpa', '--emit-every-frames', '16',
        '--decode-window-frames', '80', '--no-compile', '--no-cuda-graphs',
        '--seed', '20260806', '--seed-mode', 'fixed',
        '--warmup-synthesis', '--warmup-synthesis-passes', '1',
        '--warmup-unbounded-passes', '1', '--warmup-max-output-chunks', '2',
        '--warmup-text', 'Warmup.', '--warmup-language', 'auto',
        '--warmup-speaker', 'ryan',
        '--timeout-seconds', '900', '--requests', "$PersistentRequests",
        '--request-shapes-jsonl', $RequestShapesPath
    )
    if ($Registry) {
        $arguments += @('--voice-registry-path', $Registry)
    }
    if ($WarmupVoiceId) {
        $arguments += @('--warmup-voice-id', $WarmupVoiceId)
    }

    $previousErrorActionPreference = $ErrorActionPreference
    try {
        # Windows PowerShell 5.1 still promotes redirected native stderr to a
        # non-terminating error record. Keep it available for the report.
        $ErrorActionPreference = 'Continue'
        $raw = @(& $python @arguments 2>&1)
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    $text = $raw -join [Environment]::NewLine
    if ($exitCode -ne 0) {
        throw "$Label worker benchmark failed with exit code $exitCode.`n$text"
    }
    try {
        return $text | ConvertFrom-Json
    }
    catch {
        throw "$Label worker benchmark did not produce one JSON report.`n$text"
    }
}

function Assert-CompletedAudioRequests {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Report,

        [Parameter(Mandatory = $true)]
        [string]$Label
    )

    $requests = @($Report.requests)
    if ($requests.Count -ne $PersistentRequests) {
        throw "$Label reported $($requests.Count) requests; expected $PersistentRequests."
    }
    foreach ($request in $requests) {
        if ([int64]$request.audio_bytes -le 0 -or [int]$request.audio_chunks -le 0) {
            throw "$Label request $($request.request_id) completed without PCM audio."
        }
        if ($null -eq $request.first_audio_ms -or $null -eq $request.completed_ms) {
            throw "$Label request $($request.request_id) has incomplete timing evidence."
        }
    }
}

$player = Resolve-ExistingPath $PlayerPath 'Playback client'
$python = Resolve-ExistingPath $PythonPath 'Python runtime'
$customVoiceModel = Resolve-ExistingPath $CustomVoiceModelPath 'CustomVoice model'
$runtimeCache = Resolve-ExistingPath $RuntimeCachePath 'Runtime cache'
$fasterSource = Resolve-ExistingPath $FasterSourcePath 'Faster source'

$baseProfileRequested = $BaseModelPath -or $VoiceRegistryPath -or $VoiceId
if ($baseProfileRequested -and (-not $BaseModelPath -or -not $VoiceRegistryPath -or -not $VoiceId)) {
    throw '-BaseModelPath, -VoiceRegistryPath, and -VoiceId must be supplied together.'
}
$baseModel = if ($BaseModelPath) { Resolve-ExistingPath $BaseModelPath 'Base model' } else { '' }
$voiceRegistry = if ($VoiceRegistryPath) { Resolve-ExistingPath $VoiceRegistryPath 'Voice registry' } else { '' }

$outputDirectory = if ([IO.Path]::IsPathRooted($OutputRoot)) {
    $OutputRoot
}
else {
    Join-Path $repoRoot $OutputRoot
}
$runDirectory = Join-Path $outputDirectory ([DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ'))
New-Item -ItemType Directory -Path $runDirectory -Force | Out-Null

$environmentNames = @(
    'CUDA_VISIBLE_DEVICES', 'PYTHONHOME', 'PYTHONPATH', 'PYTHONNOUSERSITE',
    'PYTHONDONTWRITEBYTECODE', 'HF_HOME', 'HF_HUB_CACHE', 'TRANSFORMERS_CACHE',
    'TORCH_HOME', 'XDG_CACHE_HOME', 'HF_HUB_OFFLINE', 'TRANSFORMERS_OFFLINE',
    'QTB_FASTER_EAGER_DIAGNOSTIC', 'QTB_FASTER_MLP_FP32_ISLAND',
    'QTB_FASTER_RESIDUAL_CARRIER_FP32', 'QTB_FASTER_GRAPH_RESIDUAL_CARRIER_FP32',
    'QTB_FASTER_MLP_NARROW_GATE_UP_FP16', 'QTB_FASTER_STALL_TELEMETRY',
    'QTB_FASTER_CODEC_RIGHT_PADDED_DECODE',
    'QTB_FASTER_CODEC_RIGHT_PADDED_DECODE_WINDOW_FRAMES',
    'QTB_FASTER_CODEC_RIGHT_PADDED_MAX_DECODE_INPUT_FRAMES',
    'QTB_FASTER_CODEC_RIGHT_PADDED_CUDA_GRAPH',
    'QTB_FASTER_CODEC_RIGHT_PADDED_COMPILE',
    'QTB_FASTER_CODEC_RIGHT_PADDED_COMPILE_MODE'
)
$previousEnvironment = @{}
foreach ($name in $environmentNames) {
    $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}

try {
    $env:CUDA_VISIBLE_DEVICES = $CudaVisibleDevices
    $env:PYTHONHOME = Split-Path -Parent $python
    $env:PYTHONPATH = "$fasterSource;$repoRoot\worker\src"
    $env:PYTHONNOUSERSITE = '1'
    $env:PYTHONDONTWRITEBYTECODE = '1'
    $env:HF_HOME = Join-Path $runtimeCache 'huggingface'
    $env:HF_HUB_CACHE = Join-Path $runtimeCache 'huggingface\hub'
    $env:TRANSFORMERS_CACHE = Join-Path $runtimeCache 'transformers'
    $env:TORCH_HOME = Join-Path $runtimeCache 'torch'
    $env:XDG_CACHE_HOME = $runtimeCache
    $env:HF_HUB_OFFLINE = '1'
    $env:TRANSFORMERS_OFFLINE = '1'
    $env:QTB_FASTER_EAGER_DIAGNOSTIC = '0'
    $env:QTB_FASTER_MLP_FP32_ISLAND = '1'
    $env:QTB_FASTER_RESIDUAL_CARRIER_FP32 = '0'
    $env:QTB_FASTER_GRAPH_RESIDUAL_CARRIER_FP32 = '1'
    $env:QTB_FASTER_MLP_NARROW_GATE_UP_FP16 = '1'
    $env:QTB_FASTER_STALL_TELEMETRY = '0'
    $env:QTB_FASTER_CODEC_RIGHT_PADDED_DECODE = '1'
    $env:QTB_FASTER_CODEC_RIGHT_PADDED_DECODE_WINDOW_FRAMES = '48'
    $env:QTB_FASTER_CODEC_RIGHT_PADDED_MAX_DECODE_INPUT_FRAMES = '41'
    $env:QTB_FASTER_CODEC_RIGHT_PADDED_CUDA_GRAPH = '1'
    $env:QTB_FASTER_CODEC_RIGHT_PADDED_COMPILE = '0'
    $env:QTB_FASTER_CODEC_RIGHT_PADDED_COMPILE_MODE = ''

    $help = @(& $player --help 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "qwen_tts_play --help failed with exit code $LASTEXITCODE."
    }
    $helpText = $help -join [Environment]::NewLine
    foreach ($requiredOption in '--worker', '--text', '--speaker', '--voice-id', '/voices', '/cancel') {
        if (-not $helpText.Contains($requiredOption)) {
            throw "qwen_tts_play --help does not document $requiredOption."
        }
    }

    $customShapesPath = Join-Path $runDirectory 'customvoice-persistent-shapes.jsonl'
    @(
        [ordered]@{
            label = 'customvoice-ryan-english'
            text = 'Release acceptance confirms persistent CustomVoice playback for Ryan.'
            language = 'English'
            speaker = 'ryan'
        },
        [ordered]@{
            label = 'customvoice-serena-russian'
            text = 'Проверка релизного CustomVoice воспроизведения для Серены.'
            language = 'Russian'
            speaker = 'serena'
        }
    ) | ForEach-Object { $_ | ConvertTo-Json -Compress } | Set-Content -LiteralPath $customShapesPath -Encoding utf8

    $customWorker = Invoke-WorkerBenchmark -Model $customVoiceModel `
        -RequestShapesPath $customShapesPath -Label 'CustomVoice persistent-worker'
    Assert-CompletedAudioRequests -Report $customWorker -Label 'CustomVoice persistent-worker'
    Write-Json (Join-Path $runDirectory 'customvoice-persistent-worker.json') $customWorker

    $profileRejectionPath = Join-Path $runDirectory 'customvoice-profile-rejection.jsonl'
    [ordered]@{
        label = 'customvoice-reject-base-profile'
        text = 'This request must reject a Base voice profile.'
        language = 'English'
        voice_id = 'not-a-customvoice-speaker'
    } | ConvertTo-Json -Compress | Set-Content -LiteralPath $profileRejectionPath -Encoding utf8
    $profileRejectionObserved = $false
    try {
        Invoke-WorkerBenchmark -Model $customVoiceModel -RequestShapesPath $profileRejectionPath `
            -Label 'CustomVoice Base-profile rejection' | Out-Null
    }
    catch {
        if ($_.Exception.Message -match 'registered voice profiles are supported only by qwen base models') {
            $profileRejectionObserved = $true
        }
        else {
            throw
        }
    }
    if (-not $profileRejectionObserved) {
        throw 'CustomVoice incorrectly accepted a Base voice-profile request.'
    }

    $physicalPlayback = @()
    if (-not $SkipPhysicalPlayback) {
        foreach ($case in @(
            @{ label = 'ryan-english'; speaker = 'ryan'; language = 'English'; text = 'Release acceptance listening sample for Ryan.' },
            @{ label = 'serena-russian'; speaker = 'serena'; language = 'Russian'; text = 'Проверка слухового образца релизной сборки для Серены.' }
        )) {
            $caseRoot = Join-Path $runDirectory ("playback-" + $case.label)
            & (Join-Path $PSScriptRoot 'run-cmp50hx-playback-etw-soak.ps1') `
                -Attempts 1 -PlayerPath $player -PythonPath $python -ModelPath $customVoiceModel `
                -RuntimeCachePath $runtimeCache -FasterSourcePath $fasterSource `
                -OutputRoot $caseRoot -Text $case.text -Speaker $case.speaker `
                -Language $case.language -PlaybackPrebufferChunks 2 `
                -WorkerSynthesisWarmup -WorkerWarmupUnboundedPasses 1 `
                -WorkerWarmupMaxOutputChunks 2 -EmitEveryFrames 16 `
                -CodecRightPaddedDecode -CodecRightPaddedCudaGraph `
                -CodecRightPaddedWindowFrames 48 -SkipEtwFollowup
            if ($LASTEXITCODE -ne 0) {
                throw "C++ CLI playback acceptance failed for $($case.label)."
            }
            $summaryPath = Get-ChildItem -LiteralPath $caseRoot -Recurse -Filter summary.json |
                Select-Object -ExpandProperty FullName -First 1
            if (-not $summaryPath) {
                throw "C++ CLI playback acceptance did not produce summary.json for $($case.label)."
            }
            $summary = Get-Content -LiteralPath $summaryPath -Raw | ConvertFrom-Json
            if ([int]$summary.outlier_count -ne 0) {
                throw "C++ CLI playback acceptance observed an outlier for $($case.label)."
            }
            $physicalPlayback += [ordered]@{ label = $case.label; summary_json = $summaryPath }
        }
    }

    $baseProfile = [ordered]@{ status = 'not_run'; reason = 'Base model, registry, and profile ID were not supplied.' }
    if ($baseProfileRequested) {
        $baseShapesPath = Join-Path $runDirectory 'base-profile-persistent-shapes.jsonl'
        @(
            [ordered]@{ label = 'base-profile-first'; text = 'Release acceptance validates a reusable Base voice profile.'; language = 'English'; voice_id = $VoiceId },
            [ordered]@{ label = 'base-profile-second'; text = 'The same persistent worker reuses the registered Base voice profile.'; language = 'English'; voice_id = $VoiceId }
        ) | ForEach-Object { $_ | ConvertTo-Json -Compress } | Set-Content -LiteralPath $baseShapesPath -Encoding utf8
        $firstProcess = Invoke-WorkerBenchmark -Model $baseModel -RequestShapesPath $baseShapesPath `
            -Registry $voiceRegistry -WarmupVoiceId $VoiceId -Label 'Base profile first process'
        Assert-CompletedAudioRequests -Report $firstProcess -Label 'Base profile first process'
        $restartedProcess = Invoke-WorkerBenchmark -Model $baseModel -RequestShapesPath $baseShapesPath `
            -Registry $voiceRegistry -WarmupVoiceId $VoiceId -Label 'Base profile restarted process'
        Assert-CompletedAudioRequests -Report $restartedProcess -Label 'Base profile restarted process'
        $baseProfile = [ordered]@{
            status = 'passed'
            voice_id = $VoiceId
            startup_warmup = 'profile_matched'
            first_process = 'base-profile-first-process.json'
            restarted_process = 'base-profile-restarted-process.json'
        }
        Write-Json (Join-Path $runDirectory 'base-profile-first-process.json') $firstProcess
        Write-Json (Join-Path $runDirectory 'base-profile-restarted-process.json') $restartedProcess
    }

    $summary = [ordered]@{
        schema_version = 1
        generated_at_utc = [DateTime]::UtcNow.ToString('o')
        scope = 'real_model_release_acceptance'
        cli_help = 'passed'
        customvoice_preset_speakers = 'passed'
        customvoice_rejects_base_voice_profiles = $profileRejectionObserved
        physical_playback = if ($SkipPhysicalPlayback) { 'skipped' } else { $physicalPlayback }
        base_voice_profile = $baseProfile
        listening_review = 'pending_human_review'
    }
    $summaryPath = Join-Path $runDirectory 'summary.json'
    Write-Json $summaryPath $summary
    Write-Output "summary_json=$summaryPath"
    Write-Output 'Automated real-model acceptance passed; complete the listening checklist before release.'
}
finally {
    foreach ($name in $environmentNames) {
        [Environment]::SetEnvironmentVariable($name, $previousEnvironment[$name], 'Process')
    }
}
