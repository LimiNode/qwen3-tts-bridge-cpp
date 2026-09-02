param(
    [ValidateRange(1, 30)]
    [int]$Attempts = 5,
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
    [string]$Text = 'This repeated native GGML CustomVoice playback measurement checks the CMP 50HX baseline.',
    [ValidateNotNullOrEmpty()]
    [string]$Language = 'english',
    [string]$Speaker = 'ryan',
    [ValidateRange(0, 2147483647)]
    [int]$Seed = 20260806,
    [ValidateNotNullOrEmpty()]
    [string]$WorkloadLabel = 'uncontrolled_no_deliberate_gpu_workload',
    [string]$OutputRoot = 'tmp\cmp50hx-ggml-playback-measurement'
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$smokeLauncher = Join-Path $PSScriptRoot 'run-cmp50hx-ggml-playback-smoke.ps1'
if (-not (Test-Path -LiteralPath $smokeLauncher -PathType Leaf)) {
    throw "Native GGML smoke launcher was not found: $smokeLauncher"
}

function Get-JsonMetricEvents {
    param([string]$LogPath)

    $events = @()
    $rawLog = Get-Content -LiteralPath $LogPath -Raw
    $matches = [regex]::Matches($rawLog, '(?s)qtb_metric\s+(\{.*?\})(?:\r?\n){2}')
    foreach ($match in $matches) {
        # PowerShell wraps redirected native stderr at its formatting width.
        # Metric JSON itself is compact and never intentionally contains newlines.
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

$measurementRoot = Join-Path (Join-Path $repo $OutputRoot) (Get-Date -Format 'yyyyMMddTHHmmssZ')
New-Item -ItemType Directory -Path $measurementRoot -Force | Out-Null
$attemptRecords = @()

for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
    $attemptRoot = Join-Path $measurementRoot ("attempt-{0:D2}" -f $attempt)
    Write-Host "[$attempt/$Attempts] native GGML playback"

    $launcherArgs = @{
        PlayerPath = $PlayerPath
        PythonPath = $PythonPath
        GgmlPythonPath = $GgmlPythonPath
        GgmlCachePath = $GgmlCachePath
        GgmlLibraryPath = $GgmlLibraryPath
        CudaDllPath = $CudaDllPath
        GgmlQuant = $GgmlQuant
        CodecChunkSeconds = $CodecChunkSeconds
        PlaybackPrebufferChunks = $PlaybackPrebufferChunks
        Text = $Text
        Language = $Language
        Speaker = $Speaker
        Seed = $Seed
        WorkloadLabel = $WorkloadLabel
        OutputRoot = $attemptRoot
    }
    & $smokeLauncher @launcherArgs

    $summaryFiles = @(Get-ChildItem -LiteralPath $attemptRoot -Recurse -Filter summary.json -File)
    if ($summaryFiles.Count -ne 1) {
        throw "Expected exactly one smoke summary in $attemptRoot, found $($summaryFiles.Count)"
    }
    $smokeSummary = Get-Content -LiteralPath $summaryFiles[0].FullName -Raw | ConvertFrom-Json
    if (
        -not $smokeSummary.comparison_contract -or
        $smokeSummary.comparison_contract.text_sha256 -ne (Get-TextSha256 $Text) -or
        $smokeSummary.comparison_contract.language -cne $Language -or
        $smokeSummary.comparison_contract.speaker -cne $Speaker -or
        [int]$smokeSummary.comparison_contract.seed -ne $Seed -or
        $smokeSummary.comparison_contract.workload_label -cne $WorkloadLabel
    ) {
        throw "GGML attempt $attempt did not retain the requested comparison contract."
    }
    $playback = Get-Content -LiteralPath $smokeSummary.playback_metrics -Raw | ConvertFrom-Json
    if (-not [bool]$playback.playback_completed) {
        throw "GGML attempt $attempt did not complete physical playback."
    }
    $stderrPath = [string]$smokeSummary.stderr
    $finished = @(Get-JsonMetricEvents $stderrPath | Where-Object { $_.event -eq 'request_finished' } | Select-Object -Last 1)
    if ($finished.Count -ne 1) {
        throw "GGML attempt $attempt did not produce one request_finished metric: $stderrPath"
    }

    $attemptRecords += [ordered]@{
        attempt = $attempt
        smoke_summary = $summaryFiles[0].FullName
        synthesis_ms = [double]$finished[0].synthesis_ms
        first_audio_ms = [double]$finished[0].first_audio_ms
        real_time_factor = [double]$finished[0].real_time_factor
        audio_duration_ms = [double]$finished[0].audio_duration_ms
        audio_chunk_count = [int]$finished[0].audio_chunks
        waveout_queue_starvation_proxy_observations = [int]$playback.queue_empty_before_later_chunk_count
        playback_completed = [bool]$playback.playback_completed
    }
}

$synthesis = [double[]]@($attemptRecords | ForEach-Object { $_.synthesis_ms })
$firstAudio = [double[]]@($attemptRecords | ForEach-Object { $_.first_audio_ms })
$rtf = [double[]]@($attemptRecords | ForEach-Object { $_.real_time_factor })
$starvation = [int[]]@($attemptRecords | ForEach-Object { $_.waveout_queue_starvation_proxy_observations })
$report = [ordered]@{
    schema_version = 1
    measurement = 'repeated_native_ggml_playback_not_faster_pcm_parity'
    runtime_backend = 'ggml'
    generated_utc = (Get-Date).ToUniversalTime().ToString('o')
    configuration = [ordered]@{
        attempts_requested = $Attempts
        quant = $GgmlQuant
        codec_chunk_seconds = $CodecChunkSeconds
        playback_prebuffer_chunks = $PlaybackPrebufferChunks
        speaker = $Speaker
        text_sha256 = Get-TextSha256 $Text
        language = $Language
    }
    comparison_contract = [ordered]@{
        schema_version = 1
        text_sha256 = Get-TextSha256 $Text
        language = $Language
        speaker = $Speaker
        seed = $Seed
        seed_mode = 'fixed'
        attempts_requested = $Attempts
        attempts_completed = $attemptRecords.Count
        playback_prebuffer_chunks = $PlaybackPrebufferChunks
        workload_label = $WorkloadLabel
        etw_capture_enabled = $false
        pcm_capture_enabled = $false
    }
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
$reportPath = Join-Path $measurementRoot 'summary.json'
$report | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $reportPath -Encoding utf8
Write-Host "summary_json=$reportPath"
Write-Host 'Repeated native GGML playback measurement completed; compare quality separately from Faster PCM.'
