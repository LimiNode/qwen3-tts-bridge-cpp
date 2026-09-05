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

function Invoke-Playback([string] $Name, [string] $Worker, [string[]] $WorkerArguments, [string] $Directory) {
    if (-not $PlaybackExecutable) { return [ordered]@{ attempted = $false; reason = "PlaybackExecutable not supplied" } }
    $metrics = Join-Path $Directory "$Name-playback.json"
    $stderr = Join-Path $Directory "$Name-playback.stderr.log"
    $command = [System.Collections.Generic.List[string]]::new()
    [void]$command.Add("--worker"); [void]$command.Add($Worker)
    Add-WorkerArguments $command $WorkerArguments
    [void]$command.Add("--text"); [void]$command.Add($(if ($PlaybackText) { $PlaybackText } else { $Text }))
    [void]$command.Add("--language"); [void]$command.Add($Language)
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
$artifactDirectory = $outputPath + ".artifacts"
$runDirectory = Join-Path $artifactDirectory ((Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssfffZ") + "-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $runDirectory | Out-Null
$pythonResult = Invoke-Benchmark "python" $python $PythonWorkerArgument (Join-Path $runDirectory "python.json") (Join-Path $runDirectory "python.stderr.log") $manifestPath
    $nativeResult = Invoke-Benchmark "native" $native $NativeWorkerArgument (Join-Path $runDirectory "native.json") (Join-Path $runDirectory "native.stderr.log") $manifestPath
    $playback = [ordered]@{
        python = Invoke-Playback "python" $python $PythonWorkerArgument $runDirectory
        native = Invoke-Playback "native" $native $NativeWorkerArgument $runDirectory
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
