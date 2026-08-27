param(
    [string]$PlayerPath = '',
    [string]$PythonPath = '',
    [string]$GgmlPythonPath = '',
    [string]$GgmlCachePath = '',
    [string]$GgmlLibraryPath = '',
    [string]$CudaDllPath = '',
    [ValidateSet('BF16', 'Q8_0', 'Q4_K_M')]
    [string]$GgmlQuant = 'BF16',
    [ValidateRange(0.1, 30.0)]
    [double]$CodecChunkSeconds = 1.0,
    [ValidateRange(1, 16)]
    [int]$PlaybackPrebufferChunks = 2,
    [string]$Text = 'This is a native GGML CustomVoice playback smoke test.',
    [ValidateNotNullOrEmpty()]
    [string]$Language = 'english',
    [string]$Speaker = 'ryan',
    [ValidateRange(0, 2147483647)]
    [int]$Seed = 20260806,
    [ValidateNotNullOrEmpty()]
    [string]$WorkloadLabel = 'uncontrolled_no_deliberate_gpu_workload',
    [string]$OutputRoot = 'tmp\cmp50hx-ggml-playback-smoke'
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
$repo = Split-Path -Parent $PSScriptRoot

function Resolve-LocalPath {
    param([string]$Path, [string]$Description)
    $candidate = if ([IO.Path]::IsPathRooted($Path)) { $Path } else { Join-Path $repo $Path }
    if (-not (Test-Path -LiteralPath $candidate)) { throw "$Description was not found: $candidate" }
    (Resolve-Path -LiteralPath $candidate).Path
}

function Get-TextSha256 {
    param([Parameter(Mandatory = $true)][string]$Value)

    $hasher = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [Text.Encoding]::UTF8.GetBytes($Value)
        ([BitConverter]::ToString($hasher.ComputeHash($bytes))).Replace('-', '').ToLowerInvariant()
    }
    finally {
        $hasher.Dispose()
    }
}

if (-not $PlayerPath) { $PlayerPath = 'build\cmp50hx-diagnostic-mingw\qwen_tts_play.exe' }
if (-not $PythonPath) { $PythonPath = 'tmp\QwenTTSBridge-technical-beta-r3\QwenTTSBridge-technical-beta-r3\worker\python\python.exe' }
if (-not $GgmlPythonPath) { $GgmlPythonPath = '..\_tmp-qwentts-cpp-python-cmp50hx\src' }
if (-not $GgmlCachePath) { $GgmlCachePath = 'tmp\cmp50hx-qwentts-gguf' }
if (-not $CudaDllPath) { $CudaDllPath = 'C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.3\bin\x64' }

$player = Resolve-LocalPath $PlayerPath 'Playback client'
$python = Resolve-LocalPath $PythonPath 'Sealed Python runtime'
$ggmlPython = Resolve-LocalPath $GgmlPythonPath 'qwentts_cpp source directory'
$ggmlCache = Resolve-LocalPath $GgmlCachePath 'GGUF cache directory'
$cudaDll = Resolve-LocalPath $CudaDllPath 'CUDA runtime DLL directory'
$ggmlLibrary = if ($GgmlLibraryPath) { Resolve-LocalPath $GgmlLibraryPath 'qwen.dll' } else { '' }

$runDirectory = Join-Path (Join-Path $repo $OutputRoot) (Get-Date -Format 'yyyyMMddTHHmmssZ')
New-Item -ItemType Directory -Path $runDirectory -Force | Out-Null
$metrics = Join-Path $runDirectory 'playback-metrics.json'
$stdout = Join-Path $runDirectory 'stdout.log'
$stderr = Join-Path $runDirectory 'stderr.log'

$arguments = @(
    '--worker', $python, '--cwd', $repo,
    '--worker-arg', '-B', '--worker-arg', '-P', '--worker-arg', '-s',
    '--worker-arg', '-m', '--worker-arg', 'qwen_tts_bridge_worker',
    '--worker-arg', 'qwen',
    '--worker-arg', '--model-path', '--worker-arg', 'Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice',
    '--worker-arg', '--runtime-backend', '--worker-arg', 'ggml',
    '--worker-arg', '--ggml-quant', '--worker-arg', $GgmlQuant,
    '--worker-arg', '--ggml-cache-dir', '--worker-arg', $ggmlCache,
    '--worker-arg', '--ggml-python-path', '--worker-arg', $ggmlPython,
    '--worker-arg', '--ggml-cuda-dll-dir', '--worker-arg', $cudaDll,
    '--worker-arg', '--ggml-codec-chunk-seconds', '--worker-arg', $CodecChunkSeconds,
    '--worker-arg', '--device', '--worker-arg', 'cuda',
    '--worker-arg', '--seed', '--worker-arg', $Seed,
    '--worker-arg', '--seed-mode', '--worker-arg', 'fixed',
    '--text', $Text, '--language', $Language, '--speaker', $Speaker,
    '--playback-prebuffer-chunks', $PlaybackPrebufferChunks,
    '--startup-timeout-ms', '240000',
    '--playback-metrics-file', $metrics
)
if ($ggmlLibrary) { $arguments += @('--worker-arg', '--ggml-library-path', '--worker-arg', $ggmlLibrary) }

$previousPythonPath = $env:PYTHONPATH
$previousCudaVisibleDevices = $env:CUDA_VISIBLE_DEVICES
try {
    # The packaged runtime intentionally stays frozen; this launcher opts into
    # the current worker source and local qwentts_cpp adapter for this A/B only.
    $env:PYTHONPATH = "$repo\worker\src;$ggmlPython"
    $env:CUDA_VISIBLE_DEVICES = '0'
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & $player @arguments 1> $stdout 2> $stderr
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
}
finally {
    $env:PYTHONPATH = $previousPythonPath
    $env:CUDA_VISIBLE_DEVICES = $previousCudaVisibleDevices
}
if ($exitCode -ne 0) { throw "GGML playback smoke failed with exit code $exitCode. See $stderr" }
if (-not (Test-Path -LiteralPath $metrics -PathType Leaf)) { throw 'GGML playback smoke completed without metrics.' }

$summary = [ordered]@{
    runtime_backend = 'ggml'
    measurement = 'native_ggml_playback_smoke_not_faster_pcm_parity'
    comparison_contract = [ordered]@{
        schema_version = 1
        text_sha256 = Get-TextSha256 $Text
        language = $Language
        speaker = $Speaker
        seed = $Seed
        seed_mode = 'fixed'
        attempts_requested = 1
        attempts_completed = 1
        playback_prebuffer_chunks = $PlaybackPrebufferChunks
        workload_label = $WorkloadLabel
        etw_capture_enabled = $false
        pcm_capture_enabled = $false
    }
    playback_metrics = $metrics
    stdout = $stdout
    stderr = $stderr
}
$summaryPath = Join-Path $runDirectory 'summary.json'
$summary | ConvertTo-Json | Set-Content -LiteralPath $summaryPath -Encoding utf8
Write-Host "summary_json=$summaryPath"
Write-Host 'Native GGML playback smoke completed; this is not Faster PCM-parity or ETW evidence.'
