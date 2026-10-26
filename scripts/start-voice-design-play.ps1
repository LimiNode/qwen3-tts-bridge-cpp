[CmdletBinding()]
param(
    [string]$BuildDirectory = "build",
    [string]$ConfigPath = "",
    [string]$ModelProfile = "",
    [string]$Python = "",
    [string]$ModelPath = "",
    [Parameter(Mandatory = $true)]
    [string]$Instruction,
    [string]$Text = "Привет! Я рада тебя видеть.",
    [string]$Language = "Russian",
    [ValidateSet("faster", "upstream")]
    [string]$RuntimeBackend = "faster",
    [ValidateSet("default", "cmp50hx-fastest", "cmp50hx-fastest-experimental", "cmp50hx-ultra-low-latency", "cmp50hx-low-latency", "cmp50hx-safe")]
    [string]$RuntimeProfile = "default",
    [string]$Dtype = "auto",
    [string]$AttnImplementation = "",
    [int]$MaxSeqLen = 2048,
    [int]$EmitEveryFrames = 8,
    [int]$DecodeWindowFrames = 80,
    [int]$OverlapSamples = 0,
    [switch]$CollectGenerationTrace,
    [switch]$Interactive,
    [switch]$NoPlayback,
    [switch]$NoTail,
    [string]$FasterSourcePath = "",
    [string]$QwenSourcePath = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

function Resolve-ConfigPath {
    param([Parameter(Mandatory = $true)] [string]$PathValue)

    if ([IO.Path]::IsPathRooted($PathValue)) {
        return [IO.Path]::GetFullPath($PathValue)
    }
    return [IO.Path]::GetFullPath((Join-Path $repoRoot $PathValue))
}

function Resolve-ExistingPath {
    param(
        [Parameter(Mandatory = $true)] [string]$PathValue,
        [Parameter(Mandatory = $true)] [string]$Name
    )

    $candidate = if ([IO.Path]::IsPathRooted($PathValue)) {
        $PathValue
    }
    else {
        Join-Path $repoRoot $PathValue
    }
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
        throw "$Name was not found: $candidate"
    }
    return (Resolve-Path -LiteralPath $candidate).Path
}

function Resolve-ExistingDirectory {
    param(
        [Parameter(Mandatory = $true)] [string]$PathValue,
        [Parameter(Mandatory = $true)] [string]$Name
    )

    $candidate = if ([IO.Path]::IsPathRooted($PathValue)) {
        $PathValue
    }
    else {
        Join-Path $repoRoot $PathValue
    }
    if (-not (Test-Path -LiteralPath $candidate -PathType Container)) {
        throw "$Name was not found: $candidate"
    }
    return (Resolve-Path -LiteralPath $candidate).Path
}

$runtimeConfig = $null
if (-not [string]::IsNullOrWhiteSpace($ConfigPath)) {
    $resolvedConfigPath = Resolve-ConfigPath $ConfigPath
    if (-not (Test-Path -LiteralPath $resolvedConfigPath -PathType Leaf)) {
        throw "VoiceDesign runtime config was not found: $resolvedConfigPath"
    }
    $runtimeConfig = Get-Content -LiteralPath $resolvedConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($runtimeConfig.schema_version -ne 1) {
        throw "VoiceDesign runtime config must use schema_version 1: $resolvedConfigPath"
    }
}

$selectedProfile = if ($ModelProfile) {
    $ModelProfile
}
elseif ($runtimeConfig -and $runtimeConfig.default_model_profile) {
    [string]$runtimeConfig.default_model_profile
}
else {
    ""
}
$profile = $null
if ($selectedProfile) {
    if (-not $runtimeConfig -or -not $runtimeConfig.model_profiles) {
        throw "VoiceDesign model profile '$selectedProfile' was not found in the runtime config"
    }
    $profileProperty = $runtimeConfig.model_profiles.PSObject.Properties[$selectedProfile]
    if ($null -eq $profileProperty) {
        throw "VoiceDesign model profile was not found: $selectedProfile"
    }
    $profile = $profileProperty.Value
}

if ([string]::IsNullOrWhiteSpace($Python) -and $runtimeConfig -and $runtimeConfig.python) {
    $Python = [string]$runtimeConfig.python
}
if ([string]::IsNullOrWhiteSpace($ModelPath) -and $profile -and $profile.model_path) {
    $ModelPath = [string]$profile.model_path
}
if ([string]::IsNullOrWhiteSpace($ModelPath) -and $runtimeConfig -and $runtimeConfig.model_path) {
    $ModelPath = [string]$runtimeConfig.model_path
}
if (-not $PSBoundParameters.ContainsKey("BuildDirectory") -and $runtimeConfig -and $runtimeConfig.build_directory) {
    $BuildDirectory = [string]$runtimeConfig.build_directory
}
if ($runtimeConfig -and $runtimeConfig.faster_qwen_source_path -and
    [string]::IsNullOrWhiteSpace($FasterSourcePath)) {
    $FasterSourcePath = [string]$runtimeConfig.faster_qwen_source_path
}
if ($runtimeConfig -and $runtimeConfig.qwen_source_path -and
    [string]::IsNullOrWhiteSpace($QwenSourcePath)) {
    $QwenSourcePath = [string]$runtimeConfig.qwen_source_path
}
if ($profile) {
    if (-not $PSBoundParameters.ContainsKey("RuntimeBackend") -and $profile.runtime_backend) {
        $RuntimeBackend = [string]$profile.runtime_backend
    }
    if (-not $PSBoundParameters.ContainsKey("RuntimeProfile") -and $profile.runtime_profile) {
        $RuntimeProfile = [string]$profile.runtime_profile
    }
    if (-not $PSBoundParameters.ContainsKey("Dtype") -and $profile.dtype) {
        $Dtype = [string]$profile.dtype
    }
    if (-not $PSBoundParameters.ContainsKey("MaxSeqLen") -and $profile.max_seq_len) {
        $MaxSeqLen = [int]$profile.max_seq_len
    }
    if (-not $PSBoundParameters.ContainsKey("EmitEveryFrames") -and $profile.emit_every_frames) {
        $EmitEveryFrames = [int]$profile.emit_every_frames
    }
    if (-not $PSBoundParameters.ContainsKey("DecodeWindowFrames") -and $profile.decode_window_frames) {
        $DecodeWindowFrames = [int]$profile.decode_window_frames
    }
}

if ([string]::IsNullOrWhiteSpace($Python)) {
    throw "Python is required; pass -Python or configure it in -ConfigPath"
}
if ([string]::IsNullOrWhiteSpace($ModelPath)) {
    throw "ModelPath is required; pass -ModelPath or configure it in -ConfigPath"
}

$buildRoot = if ([IO.Path]::IsPathRooted($BuildDirectory)) {
    [IO.Path]::GetFullPath($BuildDirectory)
}
else {
    [IO.Path]::GetFullPath((Join-Path $repoRoot $BuildDirectory))
}
$cliPath = Join-Path $buildRoot "qwen_tts_play.exe"

if (-not (Test-Path -LiteralPath $cliPath -PathType Leaf)) {
    throw "qwen_tts_play.exe was not found: $cliPath"
}
if ($Instruction.Trim().Length -eq 0) {
    throw "VoiceDesign requires a non-empty -Instruction"
}

$pythonPath = Resolve-ExistingPath $Python "Python"
$model = Resolve-ExistingPath $ModelPath "VoiceDesign model"

if ([string]::IsNullOrWhiteSpace($QwenSourcePath)) {
    $QwenSourcePath = Join-Path $repoRoot "external\python\Qwen3-TTS-streaming"
}
$qwenSource = Resolve-ExistingDirectory $QwenSourcePath "Qwen3-TTS streaming source"

if ([string]::IsNullOrWhiteSpace($FasterSourcePath)) {
    $FasterSourcePath = Join-Path $repoRoot "external\python\faster-qwen3-tts"
}
$runtimeSource = if ($RuntimeBackend -eq "faster") {
    Resolve-ExistingDirectory $FasterSourcePath "FasterQwen source"
}
else {
    $qwenSource
}

$previousPythonPath = $env:PYTHONPATH
$previousNoUserSite = $env:PYTHONNOUSERSITE
$env:PYTHONPATH = "$runtimeSource;$qwenSource;$repoRoot\worker\src"
$env:PYTHONNOUSERSITE = "1"

$workerArguments = @(
    "-m", "qwen_tts_bridge_worker", "qwen",
    "--model-path", $model,
    "--runtime-backend", $RuntimeBackend,
    "--device", "cuda",
    "--dtype", $Dtype,
    "--max-seq-len", "$MaxSeqLen",
    "--emit-every-frames", "$EmitEveryFrames",
    "--decode-window-frames", "$DecodeWindowFrames",
    "--overlap-samples", "$OverlapSamples"
)
if ($RuntimeBackend -eq "faster" -and $RuntimeProfile -ne "default") {
    $workerArguments += @("--runtime-profile", $RuntimeProfile)
}
if (-not [string]::IsNullOrWhiteSpace($AttnImplementation)) {
    $workerArguments += @("--attn-implementation", $AttnImplementation)
}
if ($CollectGenerationTrace) {
    $workerArguments += "--collect-generation-trace"
}

$arguments = @(
    "--worker", $pythonPath,
    "--cwd", $repoRoot,
    "--startup-timeout-ms", "60000"
)
foreach ($workerArgument in $workerArguments) {
    $arguments += @("--worker-arg", $workerArgument)
}
if (-not $Interactive) {
    $arguments += @("--text", $Text)
}
$arguments += @(
    "--language", $Language,
    "--instruction", $Instruction
)
if ($NoPlayback) {
    $arguments += "--no-playback"
}
if ($NoTail) {
    $arguments += "--no-tail"
}

try {
    & $cliPath @arguments
    $exitCode = $LASTEXITCODE
}
finally {
    if ($null -eq $previousPythonPath) {
        Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    }
    else {
        $env:PYTHONPATH = $previousPythonPath
    }
    if ($null -eq $previousNoUserSite) {
        Remove-Item Env:PYTHONNOUSERSITE -ErrorAction SilentlyContinue
    }
    else {
        $env:PYTHONNOUSERSITE = $previousNoUserSite
    }
}
exit $exitCode
