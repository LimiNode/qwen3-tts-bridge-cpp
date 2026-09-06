[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string] $BenchmarkExecutable,
    [Parameter(Mandatory = $true)] [string] $PythonWorkerExecutable,
    [Parameter(Mandatory = $true)] [string[]] $PythonWorkerArgument,
    [Parameter(Mandatory = $true)] [string] $NativeWorkerExecutable,
    [Parameter(Mandatory = $true)] [string[]] $NativeWorkerArgument,
    [string] $Text = "Native/Python acceptance request.",
    [string] $RequestManifest = "",
    [string] $Language = "auto",
    [int] $Warmups = 5,
    [int] $Requests = 30,
    [int] $CancelEvery = 0,
    [UInt64] $Seed = 4242,
    [string] $Speaker = "",
    [string] $VoiceId = "",
    [string] $Output = "native-python-matrix.json",
    [string] $PlaybackExecutable = "",
    [string] $PlaybackText = "",
    [string] $PlaybackManifestLabel = "",
    [switch] $SkipGpuSampling
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Resolve-ExistingFile([string] $PathValue, [string] $Name) {
    $resolved = (Resolve-Path -LiteralPath $PathValue -ErrorAction Stop).Path
    if (-not (Test-Path -LiteralPath $resolved -PathType Leaf)) {
        throw "$Name is not a file: $resolved"
    }
    return $resolved
}

function Add-WorkerArguments([System.Collections.Generic.List[string]] $Command, [string[]] $Arguments) {
    foreach ($argument in $Arguments) {
        [void]$Command.Add("--worker-arg")
        [void]$Command.Add($argument)
    }
}

function Start-GpuSampler([string] $Path) {
    if ($SkipGpuSampling) { return $null }
    return Start-Job -ArgumentList $Path -ScriptBlock {
        param($OutputPath)
        while ($true) {
            try {
                $sample = @(nvidia-smi --query-gpu=index,memory.used --format=csv,noheader,nounits 2>$null)
                foreach ($line in $sample) {
                    if ($line) {
                        Add-Content -LiteralPath $OutputPath -Value ((Get-Date).ToUniversalTime().ToString("o") + "," + $line.Trim())
                    }
                }
            } catch { }
            Start-Sleep -Milliseconds 250
        }
    }
}

function Stop-GpuSampler($Job, [string] $Path) {
    $peak = $null
    if ($null -ne $Job) {
        Stop-Job -Job $Job -ErrorAction SilentlyContinue
        Remove-Job -Job $Job -Force -ErrorAction SilentlyContinue
    }
    if (Test-Path -LiteralPath $Path) {
        $values = @(
            Get-Content -LiteralPath $Path | ForEach-Object {
                $parts = $_ -split ","
                if ($parts.Length -ge 3) {
                    $number = 0
                    if ([int]::TryParse($parts[2].Trim(), [ref]$number)) { $number }
                }
            }
        )
        if ($values.Count -gt 0) { $peak = ($values | Measure-Object -Maximum).Maximum }
    }
    return $peak
}

function Invoke-Benchmark(
    [string] $Name,
    [string] $Worker,
    [string[]] $WorkerArguments,
    [string] $ResultPath,
    [string] $StderrPath,
    [string] $ManifestPath) {
    $command = [System.Collections.Generic.List[string]]::new()
    [void]$command.Add("--worker")
    [void]$command.Add($Worker)
    Add-WorkerArguments $command $WorkerArguments
    if ($ManifestPath) {
        [void]$command.Add("--request-manifest"); [void]$command.Add($ManifestPath)
    } else {
        [void]$command.Add("--text"); [void]$command.Add($Text)
        [void]$command.Add("--language"); [void]$command.Add($Language)
        if ($Speaker) { [void]$command.Add("--speaker"); [void]$command.Add($Speaker) }
        if ($VoiceId) { [void]$command.Add("--voice-id"); [void]$command.Add($VoiceId) }
    }
    [void]$command.Add("--warmups"); [void]$command.Add($Warmups.ToString())
    [void]$command.Add("--requests"); [void]$command.Add($Requests.ToString())
    [void]$command.Add("--cancel-every"); [void]$command.Add($CancelEvery.ToString())
    [void]$command.Add("--seed"); [void]$command.Add($Seed.ToString())
    [void]$command.Add("--result-json"); [void]$command.Add($ResultPath)

    Write-Host "[$Name] running benchmark"
    $gpuSamples = Join-Path ([System.IO.Path]::GetDirectoryName($ResultPath)) "$Name-gpu.csv"
    $sampler = Start-GpuSampler $gpuSamples
    try {
        & $BenchmarkExecutable @($command) 2> $StderrPath
        if ($LASTEXITCODE -ne 0) { throw "$Name benchmark failed with exit code $LASTEXITCODE" }
    } finally {
        $peak = Stop-GpuSampler $sampler $gpuSamples
    }
    $result = Get-Content -Raw -LiteralPath $ResultPath | ConvertFrom-Json
    Add-Member -InputObject $result -NotePropertyName host_peak_gpu_memory_used_mib -NotePropertyValue $peak
    return $result
}

function Add-OptionalPlaybackArgument(
    [System.Collections.Generic.List[string]] $Command,
    [string] $Name,
    [object] $Value) {
    if ($null -eq $Value) { return }
    $text = [string]$Value
    if ($text) {
        [void]$Command.Add($Name); [void]$Command.Add($text)
    }
}

function Get-ManifestPlaybackSpec([string] $Path, [string] $Label) {
    if (-not $Path) { return $null }
    $rows = @(Get-Content -LiteralPath $Path | Where-Object { $_.Trim() } | ConvertFrom-Json)
    if ($rows.Count -eq 0) { throw "RequestManifest contains no rows." }
    if ($Label) {
        $matches = @($rows | Where-Object { $_.label -eq $Label })
        if ($matches.Count -ne 1) { throw "PlaybackManifestLabel '$Label' must match exactly one manifest row." }
        return $matches[0]
    }
    if ($rows.Count -gt 1) {
        throw "Playback with RequestManifest requires -PlaybackManifestLabel to select an exact row."
    }
    return $rows[0]
}

function Get-ManifestValue([object] $Spec, [string] $Name) {
    if ($null -eq $Spec) { return $null }
    $property = $Spec.PSObject.Properties[$Name]
    if ($null -eq $property) { return $null }
    return $property.Value
}

function Invoke-Playback(
    [string] $Name,
    [string] $Worker,
    [string[]] $WorkerArguments,
    [string] $Directory,
    [object] $ManifestSpec) {
    if (-not $PlaybackExecutable) { return [ordered]@{ attempted = $false; reason = "PlaybackExecutable not supplied" } }
    $metrics = Join-Path $Directory "$Name-playback.json"
    $stderr = Join-Path $Directory "$Name-playback.stderr.log"
    $command = [System.Collections.Generic.List[string]]::new()
    [void]$command.Add("--worker"); [void]$command.Add($Worker)
    Add-WorkerArguments $command $WorkerArguments
    $manifestText = Get-ManifestValue $ManifestSpec "text"
    $manifestLanguage = Get-ManifestValue $ManifestSpec "language"
    $playText = if ($manifestText) { [string]$manifestText } elseif ($PlaybackText) { $PlaybackText } else { $Text }
    $playLanguage = if ($manifestLanguage) { [string]$manifestLanguage } else { $Language }
    [void]$command.Add("--text"); [void]$command.Add($playText)
    [void]$command.Add("--language"); [void]$command.Add($playLanguage)
    $playSpeaker = if ($null -ne $ManifestSpec) { Get-ManifestValue $ManifestSpec "speaker" } else { $Speaker }
    $playVoiceId = if ($null -ne $ManifestSpec) { Get-ManifestValue $ManifestSpec "voice_id" } else { $VoiceId }
    $playInstruction = Get-ManifestValue $ManifestSpec "instruction"
    $playReferenceAudio = Get-ManifestValue $ManifestSpec "reference_audio_path"
    $playReferenceText = Get-ManifestValue $ManifestSpec "reference_text"
    Add-OptionalPlaybackArgument $command "--speaker" $playSpeaker
    Add-OptionalPlaybackArgument $command "--voice-id" $playVoiceId
    Add-OptionalPlaybackArgument $command "--instruction" $playInstruction
    Add-OptionalPlaybackArgument $command "--reference-audio" $playReferenceAudio
    Add-OptionalPlaybackArgument $command "--reference-text" $playReferenceText
    $playXVectorOnly = Get-ManifestValue $ManifestSpec "x_vector_only"
    $playSeed = Get-ManifestValue $ManifestSpec "seed"
    if ([bool]$playXVectorOnly) { [void]$command.Add("--x-vector-only") }
    if ($null -ne $playSeed) { Add-OptionalPlaybackArgument $command "--seed" $playSeed }
    elseif ($null -eq $ManifestSpec) { Add-OptionalPlaybackArgument $command "--seed" $Seed }
    [void]$command.Add("--playback-metrics-file"); [void]$command.Add($metrics)
    [void]$command.Add("--etw-playback-markers")
    & $PlaybackExecutable @($command) 2> $stderr
    $exitCode = $LASTEXITCODE
    $json = $null
    if (Test-Path -LiteralPath $metrics) { $json = Get-Content -Raw -LiteralPath $metrics | ConvertFrom-Json }
    return [ordered]@{
        attempted = $true
        exit_code = $exitCode
        metrics = $json
        gate_passed = ($exitCode -eq 0 -and $null -ne $json -and $json.playback_completed -and $json.queue_empty_before_later_chunk_count -eq 0)
        stderr_path = $stderr
    }
}

$benchmark = Resolve-ExistingFile $BenchmarkExecutable "BenchmarkExecutable"
$python = Resolve-ExistingFile $PythonWorkerExecutable "PythonWorkerExecutable"
$native = Resolve-ExistingFile $NativeWorkerExecutable "NativeWorkerExecutable"
$outputPath = [System.IO.Path]::GetFullPath($Output)
$outputDirectory = [System.IO.Path]::GetDirectoryName($outputPath)
if ($outputDirectory) { New-Item -ItemType Directory -Force -Path $outputDirectory | Out-Null }

$manifestPath = ""
if ($RequestManifest) { $manifestPath = Resolve-ExistingFile $RequestManifest "RequestManifest" }
$playbackManifestSpec = if ($PlaybackExecutable) {
    Get-ManifestPlaybackSpec $manifestPath $PlaybackManifestLabel
} else {
    $null
}
$artifactDirectory = $outputPath + ".artifacts"
$runDirectory = Join-Path $artifactDirectory ((Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssfffZ") + "-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $runDirectory | Out-Null
if ($manifestPath) {
    Copy-Item -LiteralPath $manifestPath -Destination (Join-Path $runDirectory "request-manifest.jsonl")
}
function Snapshot-ManifestArgument([string[]] $Arguments, [string] $DestinationName) {
    for ($index = 0; $index -lt $Arguments.Count - 1; $index++) {
        if ($Arguments[$index] -eq "--manifest-path") {
            $candidate = $Arguments[$index + 1]
            if (Test-Path -LiteralPath $candidate -PathType Leaf) {
                $destination = Join-Path $runDirectory $DestinationName
                Copy-Item -LiteralPath $candidate -Destination $destination
                return [ordered]@{ path = $destination; sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $destination).Hash.ToLowerInvariant() }
            }
        }
    }
    return $null
}
function Snapshot-HashArgument([string[]] $Arguments, [string] $ArgumentName) {
    for ($index = 0; $index -lt $Arguments.Count - 1; $index++) {
        if ($Arguments[$index] -eq $ArgumentName) {
            $candidate = $Arguments[$index + 1]
            if (Test-Path -LiteralPath $candidate -PathType Leaf) {
                return [ordered]@{ path = (Resolve-Path -LiteralPath $candidate).Path; sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $candidate).Hash.ToLowerInvariant() }
            }
        }
    }
    return $null
}
$nativeRuntimeSnapshot = Snapshot-ManifestArgument $NativeWorkerArgument "native-runtime-manifest.json"
$nativeDllSnapshot = Snapshot-HashArgument $NativeWorkerArgument "--dll-path"
if ($null -eq $nativeDllSnapshot) {
    for ($index = 0; $index -lt $NativeWorkerArgument.Count - 1; $index++) {
        if ($NativeWorkerArgument[$index] -eq "--runtime-dir") {
            $runtimeDll = Join-Path $NativeWorkerArgument[$index + 1] "qwen.dll"
            if (Test-Path -LiteralPath $runtimeDll -PathType Leaf) {
                $nativeDllSnapshot = [ordered]@{ path = (Resolve-Path -LiteralPath $runtimeDll).Path; sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $runtimeDll).Hash.ToLowerInvariant() }
            }
        }
    }
}
$pythonResult = Invoke-Benchmark "python" $python $PythonWorkerArgument (Join-Path $runDirectory "python.json") (Join-Path $runDirectory "python.stderr.log") $manifestPath
    $nativeResult = Invoke-Benchmark "native" $native $NativeWorkerArgument (Join-Path $runDirectory "native.json") (Join-Path $runDirectory "native.stderr.log") $manifestPath
    $playback = [ordered]@{
        python = Invoke-Playback "python" $python $PythonWorkerArgument $runDirectory $playbackManifestSpec
        native = Invoke-Playback "native" $native $NativeWorkerArgument $runDirectory $playbackManifestSpec
    }
    $gpu = @()
    try { $gpu = @(nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader,nounits 2>$null) } catch { }
    [ordered]@{
        schema_version = 2
        artifact_directory = $runDirectory
        host = [ordered]@{ computer = $env:COMPUTERNAME; gpu = $gpu }
        workload = [ordered]@{
            text = $Text; language = $Language; request_manifest = $manifestPath
            warmups = $Warmups; requests = $Requests; cancel_every = $CancelEvery; seed = $Seed
            speaker = $Speaker; voice_id = $VoiceId
            playback_manifest_label = $PlaybackManifestLabel
        }
        evidence = [ordered]@{
            request_manifest = if ($manifestPath) { [ordered]@{ path = (Join-Path $runDirectory "request-manifest.jsonl"); sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $runDirectory "request-manifest.jsonl")).Hash.ToLowerInvariant() } } else { $null }
            native_runtime_manifest = $nativeRuntimeSnapshot
            native_dll = $nativeDllSnapshot
        }
        python = $pythonResult
        native = $nativeResult
        playback = $playback
    } | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $outputPath -Encoding UTF8
    if ($PlaybackExecutable) {
        foreach ($name in @("python", "native")) {
            if (-not $playback[$name].gate_passed) {
                throw "$name playback acceptance gate failed; see $($playback[$name].stderr_path)"
            }
        }
    }
