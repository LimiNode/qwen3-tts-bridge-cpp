[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string] $BenchmarkExecutable,
    [Parameter(Mandatory = $true)] [string] $PythonWorkerExecutable,
    [Parameter(Mandatory = $true)] [string[]] $PythonWorkerArgument,
    [Parameter(Mandatory = $true)] [string] $NativeWorkerExecutable,
    [Parameter(Mandatory = $true)] [string[]] $NativeWorkerArgument,
    [string] $Text = "Native/Python acceptance request.",
    [string] $WarmupText = "",
    [string] $RequestManifest = "",
    [string] $Language = "auto",
    [int] $Warmups = 5,
    [int] $Requests = 30,
    [int] $CancelEvery = 0,
    [int] $GpuIndex = -1,
    [UInt64] $Seed = 4242,
    [string] $Speaker = "",
    [string] $VoiceId = "",
    [string] $Output = "native-python-matrix.json",
    [string] $PlaybackExecutable = "",
    [string] $PlaybackText = "",
    [string] $PlaybackManifestLabel = "",
    [string] $FasterQwenSourcePath = "",
    [string] $QwenSourcePath = "",
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
    return Start-Job -ArgumentList $Path,$GpuIndex -ScriptBlock {
        param($OutputPath, $SelectedGpuIndex)
        while ($true) {
            try {
                $sample = if ($SelectedGpuIndex -ge 0) {
                    @(nvidia-smi --id=$SelectedGpuIndex --query-gpu=index,memory.used --format=csv,noheader,nounits 2>$null)
                } else {
                    @(nvidia-smi --query-gpu=index,memory.used --format=csv,noheader,nounits 2>$null)
                }
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
    }
    # Global values are defaults for manifest rows as well; a row overrides
    # each field it explicitly contains.
    [void]$command.Add("--language"); [void]$command.Add($Language)
    if ($WarmupText) { [void]$command.Add("--warmup-text"); [void]$command.Add($WarmupText) }
    if ($Speaker) { [void]$command.Add("--speaker"); [void]$command.Add($Speaker) }
    if ($VoiceId) { [void]$command.Add("--voice-id"); [void]$command.Add($VoiceId) }
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

function New-EffectiveManifest([string] $Path, [string] $Destination) {
    if (-not $Path) { return "" }
    $manifestRoot = Split-Path -Parent $Path
    $effectiveRows = @()
    foreach ($line in @(Get-Content -LiteralPath $Path | Where-Object { $_.Trim() })) {
        $row = $line | ConvertFrom-Json
        $property = $row.PSObject.Properties["reference_audio_path"]
        if ($null -ne $property -and -not [string]::IsNullOrWhiteSpace([string]$property.Value)) {
            $source = [string]$property.Value
            if ([System.IO.Path]::IsPathRooted($source)) {
                $resolved = [System.IO.Path]::GetFullPath($source)
            } else {
                $launchCandidate = [System.IO.Path]::GetFullPath((Join-Path (Get-Location) $source))
                $manifestCandidate = [System.IO.Path]::GetFullPath((Join-Path $manifestRoot $source))
                $resolved = if (Test-Path -LiteralPath $launchCandidate -PathType Leaf) {
                    $launchCandidate
                } else {
                    $manifestCandidate
                }
            }
            $row.reference_audio_path = $resolved
        }
        $effectiveRows += ($row | ConvertTo-Json -Compress -Depth 100)
    }
    $effectiveRows | Set-Content -LiteralPath $Destination -Encoding UTF8
    return $Destination
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
    $playLanguage = if ($null -ne $manifestLanguage) { [string]$manifestLanguage } else { $Language }
    [void]$command.Add("--text"); [void]$command.Add($playText)
    [void]$command.Add("--language"); [void]$command.Add($playLanguage)
    $playSpeaker = if ($null -ne (Get-ManifestValue $ManifestSpec "speaker")) { Get-ManifestValue $ManifestSpec "speaker" } else { $Speaker }
    $playVoiceId = if ($null -ne (Get-ManifestValue $ManifestSpec "voice_id")) { Get-ManifestValue $ManifestSpec "voice_id" } else { $VoiceId }
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
    else { Add-OptionalPlaybackArgument $command "--seed" $Seed }
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
if ($GpuIndex -lt -1) { throw "GpuIndex must be -1 (all GPUs) or a non-negative adapter index." }
$python = Resolve-ExistingFile $PythonWorkerExecutable "PythonWorkerExecutable"
$native = Resolve-ExistingFile $NativeWorkerExecutable "NativeWorkerExecutable"
if ($PlaybackExecutable) { $PlaybackExecutable = Resolve-ExistingFile $PlaybackExecutable "PlaybackExecutable" }
$outputPath = [System.IO.Path]::GetFullPath($Output)
$outputDirectory = [System.IO.Path]::GetDirectoryName($outputPath)
if ($outputDirectory) { New-Item -ItemType Directory -Force -Path $outputDirectory | Out-Null }

$manifestPath = ""
if ($RequestManifest) { $manifestPath = Resolve-ExistingFile $RequestManifest "RequestManifest" }
$artifactDirectory = $outputPath + ".artifacts"
$runDirectory = Join-Path $artifactDirectory ((Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssfffZ") + "-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $runDirectory | Out-Null
$effectiveManifestPath = ""
if ($manifestPath) {
    Copy-Item -LiteralPath $manifestPath -Destination (Join-Path $runDirectory "request-manifest.jsonl")
    $effectiveManifestPath = New-EffectiveManifest $manifestPath (Join-Path $runDirectory "effective-request-manifest.jsonl")
}
$playbackManifestSpec = if ($PlaybackExecutable) {
    Get-ManifestPlaybackSpec $effectiveManifestPath $PlaybackManifestLabel
} else {
    $null
}
function Snapshot-ManifestArgument(
    [string[]] $Arguments,
    [string] $DestinationName,
    [string[]] $ArgumentNames = @("--manifest-path")) {
    for ($index = 0; $index -lt $Arguments.Count - 1; $index++) {
        if ($Arguments[$index] -in $ArgumentNames) {
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
function Get-GitSourceProvenance([string] $PathValue, [string] $Label) {
    if (-not (Test-Path -LiteralPath $PathValue)) {
        return [ordered]@{ label = $Label; path = $PathValue; exists = $false }
    }
    $resolved = (Resolve-Path -LiteralPath $PathValue).Path
    $commit = $null
    $dirty = $null
    try {
        $commit = (& git -C $resolved rev-parse HEAD 2>$null).Trim()
        $dirty = [bool]((& git -C $resolved status --porcelain 2>$null).Trim())
    } catch { }
    return [ordered]@{
        label = $Label
        path = $resolved
        exists = $true
        git_commit = $commit
        git_dirty = $dirty
    }
}
function Get-ArgumentPathProvenance([string[]] $Arguments) {
    $known = [ordered]@{}
    $argumentLabels = [ordered]@{
        "--faster-source-path" = "faster_qwen3_tts_source"
        "--qwen-source-path" = "qwen3_tts_source"
        "--source-path" = "worker_source"
    }
    foreach ($entry in $argumentLabels.GetEnumerator()) {
        for ($index = 0; $index -lt $Arguments.Count - 1; $index++) {
            if ($Arguments[$index] -eq $entry.Key) {
                $known[$entry.Value] = Get-GitSourceProvenance $Arguments[$index + 1] $entry.Value
                break
            }
        }
    }
    return $known
}
function Get-ModelPathProvenance([string[]] $Arguments) {
    for ($index = 0; $index -lt $Arguments.Count - 1; $index++) {
        if ($Arguments[$index] -eq "--model-path") {
            $candidate = $Arguments[$index + 1]
            $resolved = if (Test-Path -LiteralPath $candidate) { (Resolve-Path -LiteralPath $candidate).Path } else { $candidate }
            $config = if (Test-Path -LiteralPath (Join-Path $resolved "config.json") -PathType Leaf) { Join-Path $resolved "config.json" } else { $null }
            return [ordered]@{
                path = $resolved
                exists = (Test-Path -LiteralPath $resolved)
                config_sha256 = if ($config) { (Get-FileHash -Algorithm SHA256 -LiteralPath $config).Hash.ToLowerInvariant() } else { $null }
            }
        }
    }
    return $null
}
function Get-PythonPackageProvenance([string] $PythonExecutable) {
    $code = @'
import importlib.metadata as metadata
import json
names = ("faster-qwen3-tts", "qwen-tts", "qwen3-tts-streaming", "torch")
result = {}
for name in names:
    try:
        result[name] = metadata.version(name)
    except metadata.PackageNotFoundError:
        pass
print(json.dumps(result, sort_keys=True))
'@
    try {
        $raw = (& $PythonExecutable -c $code 2>$null | Out-String).Trim()
        if ($LASTEXITCODE -eq 0 -and $raw) { return ($raw | ConvertFrom-Json) }
    } catch { }
    return [ordered]@{}
}
function Get-ReferenceAudioProvenance([string] $ManifestPath) {
    $entries = @()
    if (-not $ManifestPath) { return ,$entries }
    $manifestRoot = Split-Path -Parent $ManifestPath
    $lines = @(Get-Content -LiteralPath $ManifestPath | Where-Object { $_.Trim() })
    if ($lines.Count -eq 0) { return ,$entries }
    $destinationRoot = Join-Path $runDirectory "reference-audio"
    foreach ($lineIndex in 0..($lines.Count - 1)) {
        $row = $lines[$lineIndex] | ConvertFrom-Json
        $property = $row.PSObject.Properties["reference_audio_path"]
        if ($null -eq $property -or [string]::IsNullOrWhiteSpace([string]$property.Value)) { continue }
        $source = [string]$property.Value
        if ([System.IO.Path]::IsPathRooted($source)) {
            $resolved = $source
        } else {
            # The worker receives the manifest value unchanged, so its normal
            # relative-path semantics are rooted at the launch directory.
            $launchCandidate = [System.IO.Path]::GetFullPath((Join-Path (Get-Location) $source)
            )
            $manifestCandidate = Join-Path $manifestRoot $source
            $resolved = if (Test-Path -LiteralPath $launchCandidate -PathType Leaf) {
                $launchCandidate
            } else {
                $manifestCandidate
            }
        }
        $entry = [ordered]@{
            row = $lineIndex + 1
            source_path = $source
            resolved_path = $resolved
            exists = (Test-Path -LiteralPath $resolved -PathType Leaf)
        }
        if ($entry.exists) {
            New-Item -ItemType Directory -Force -Path $destinationRoot | Out-Null
            $destination = Join-Path $destinationRoot ((($lineIndex + 1).ToString("D3")) + "-" + [System.IO.Path]::GetFileName($resolved))
            Copy-Item -LiteralPath $resolved -Destination $destination
            $entry.artifact_path = $destination
            $entry.sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $destination).Hash.ToLowerInvariant()
        }
        $entries += [pscustomobject]$entry
    }
    return ,$entries
}
$pythonSourceProvenance = Get-ArgumentPathProvenance $PythonWorkerArgument
if ($FasterQwenSourcePath) {
    $pythonSourceProvenance["faster_qwen3_tts_source"] = Get-GitSourceProvenance $FasterQwenSourcePath "faster_qwen3_tts_source"
}
if ($QwenSourcePath) {
    $pythonSourceProvenance["qwen3_tts_source"] = Get-GitSourceProvenance $QwenSourcePath "qwen3_tts_source"
}
$nativeRuntimeSnapshot = Snapshot-ManifestArgument $NativeWorkerArgument "native-runtime-manifest.json"
if ($null -eq $nativeRuntimeSnapshot) {
    for ($index = 0; $index -lt $NativeWorkerArgument.Count - 1; $index++) {
        if ($NativeWorkerArgument[$index] -eq "--runtime-dir") {
            $runtimeManifest = Join-Path $NativeWorkerArgument[$index + 1] "manifest.json"
            if (Test-Path -LiteralPath $runtimeManifest -PathType Leaf) {
                $destination = Join-Path $runDirectory "native-runtime-manifest.json"
                Copy-Item -LiteralPath $runtimeManifest -Destination $destination
                $nativeRuntimeSnapshot = [ordered]@{
                    path = $destination
                    sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $destination).Hash.ToLowerInvariant()
                }
            }
        }
    }
}
$pythonProfileSnapshot = Snapshot-ManifestArgument $PythonWorkerArgument "python-runtime-profile-manifest.json" @("--canary-runtime-profile-manifest")
$pythonAllowlistSnapshot = Snapshot-ManifestArgument $PythonWorkerArgument "python-compiled-allowlist-manifest.json" @("--canary-compiled-allowlist-manifest")
$pythonExecutableSnapshot = [ordered]@{
    path = $python
    sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $python).Hash.ToLowerInvariant()
    packages = Get-PythonPackageProvenance $python
    sources = $pythonSourceProvenance
    model = Get-ModelPathProvenance $PythonWorkerArgument
}
$bridgeCommit = $null
try {
    $bridgeCommit = (& git -C (Split-Path -Parent $PSScriptRoot) rev-parse HEAD 2>$null).Trim()
} catch { }
$nativeDllSnapshot = Snapshot-HashArgument $NativeWorkerArgument "--dll-path"
$talkerModelSnapshot = Snapshot-HashArgument $NativeWorkerArgument "--talker-model"
$codecModelSnapshot = Snapshot-HashArgument $NativeWorkerArgument "--codec-model"
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
$pythonResult = Invoke-Benchmark "python" $python $PythonWorkerArgument (Join-Path $runDirectory "python.json") (Join-Path $runDirectory "python.stderr.log") $effectiveManifestPath
    $nativeResult = Invoke-Benchmark "native" $native $NativeWorkerArgument (Join-Path $runDirectory "native.json") (Join-Path $runDirectory "native.stderr.log") $effectiveManifestPath
    $playback = [ordered]@{
        python = Invoke-Playback "python" $python $PythonWorkerArgument $runDirectory $playbackManifestSpec
        native = Invoke-Playback "native" $native $NativeWorkerArgument $runDirectory $playbackManifestSpec
    }
    $gpu = @()
    try {
        $gpu = if ($GpuIndex -ge 0) {
            @(nvidia-smi --id=$GpuIndex --query-gpu=index,name,memory.total,driver_version --format=csv,noheader,nounits 2>$null)
        } else {
            @(nvidia-smi --query-gpu=index,name,memory.total,driver_version --format=csv,noheader,nounits 2>$null)
        }
    } catch { }
    [ordered]@{
        schema_version = 2
        artifact_directory = $runDirectory
        host = [ordered]@{ computer = $env:COMPUTERNAME; gpu = $gpu }
        workload = [ordered]@{
            text = $Text; language = $Language; request_manifest = $manifestPath; effective_request_manifest = $effectiveManifestPath
            warmups = $Warmups; warmup_text = $WarmupText; requests = $Requests; cancel_every = $CancelEvery; gpu_index = $GpuIndex; seed = $Seed
            speaker = $Speaker; voice_id = $VoiceId
            playback_manifest_label = $PlaybackManifestLabel
        }
        evidence = [ordered]@{
            request_manifest = if ($manifestPath) { [ordered]@{ path = (Join-Path $runDirectory "request-manifest.jsonl"); sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $runDirectory "request-manifest.jsonl")).Hash.ToLowerInvariant() } } else { $null }
            effective_request_manifest = if ($effectiveManifestPath) { [ordered]@{ path = $effectiveManifestPath; sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $effectiveManifestPath).Hash.ToLowerInvariant() } } else { $null }
            native_runtime_manifest = $nativeRuntimeSnapshot
            native_dll = $nativeDllSnapshot
            talker_model = $talkerModelSnapshot
            codec_model = $codecModelSnapshot
            benchmark_executable = [ordered]@{ path = $benchmark; sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $benchmark).Hash.ToLowerInvariant() }
            native_worker_executable = [ordered]@{ path = $native; sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $native).Hash.ToLowerInvariant() }
            playback_executable = if ($PlaybackExecutable) { [ordered]@{ path = (Resolve-Path -LiteralPath $PlaybackExecutable).Path; sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $PlaybackExecutable).Hash.ToLowerInvariant() } } else { $null }
            python_worker = $pythonExecutableSnapshot
            python_runtime_profile_manifest = $pythonProfileSnapshot
            python_compiled_allowlist_manifest = $pythonAllowlistSnapshot
            python_sources = $pythonSourceProvenance
            bridge_commit = $bridgeCommit
            reference_audio = Get-ReferenceAudioProvenance $manifestPath
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
