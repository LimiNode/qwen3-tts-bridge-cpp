[CmdletBinding()]
param(
    [string]$ConfigPath = (Join-Path $PSScriptRoot '..\config\native-worker.local.json'),
    [string]$VoiceRegistryPath = '',
    [string]$ModelRoot = '',
    [string]$ModelProfile = '',
    [string]$TalkerModel = '',
    [string]$CodecModel = '',
    [string]$Text,
    [switch]$NoPlayback,
    [switch]$NoDownload,
    [switch]$Offline
)

$ErrorActionPreference = 'Stop'
if ($NoDownload -and $Offline) {
    throw '-NoDownload and -Offline are mutually exclusive'
}
if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) {
    throw "native worker config was not found: $ConfigPath (copy config/native-worker.example.json to native-worker.local.json)"
}
$config = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
$required = 'player', 'worker', 'runtime_dir'
foreach ($name in $required) {
    if (-not $config.$name) { throw "native worker config field '$name' is required" }
}

$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
function Resolve-BundlePath([string]$value) {
    if ([System.IO.Path]::IsPathRooted($value)) { return $value }
    return Join-Path $root $value
}

$selectedProfile = if ($ModelProfile) {
    $ModelProfile
}
elseif ($config.default_model_profile) {
    [string]$config.default_model_profile
}
else {
    ''
}
$profile = $null
if ($selectedProfile) {
    if (-not $config.model_profiles) {
        throw "model profile '$selectedProfile' was requested but model_profiles is not configured"
    }
    $profileProperty = $config.model_profiles.PSObject.Properties[$selectedProfile]
    if ($null -eq $profileProperty) {
        throw "native model profile was not found: $selectedProfile"
    }
    $profile = $profileProperty.Value
}
$configuredModelRoot = if ($ModelRoot) {
    $ModelRoot
}
elseif ($profile -and $profile.model_root) {
    [string]$profile.model_root
}
elseif ($config.model_root) {
    [string]$config.model_root
}
elseif ($env:QWEN_TTS_MODEL_ROOT) {
    $env:QWEN_TTS_MODEL_ROOT
}
else {
    $root
}
if (-not [IO.Path]::IsPathRooted($configuredModelRoot)) {
    $configuredModelRoot = Join-Path $root $configuredModelRoot
}
function Resolve-ModelPath([string]$value, [string]$name) {
    if ([string]::IsNullOrWhiteSpace($value)) {
        throw "$name was not configured"
    }
    if ([IO.Path]::IsPathRooted($value)) {
        return $value
    }
    return Join-Path $configuredModelRoot $value
}

$talkerModelValue = if ($TalkerModel) {
    $TalkerModel
}
elseif ($profile) {
    if (-not $profile.talker_model) {
        throw "native model profile '$selectedProfile' must define talker_model or use -TalkerModel"
    }
    [string]$profile.talker_model
}
else {
    [string]$config.talker_model
}
$codecModelValue = if ($CodecModel) {
    $CodecModel
}
elseif ($profile) {
    if (-not $profile.codec_model) {
        throw "native model profile '$selectedProfile' must define codec_model or use -CodecModel"
    }
    [string]$profile.codec_model
}
else {
    [string]$config.codec_model
}
$talkerModel = Resolve-ModelPath $talkerModelValue 'talker model'
$codecModel = Resolve-ModelPath $codecModelValue 'codec model'
$download = if ($profile) { $profile.model_download } else { $config.model_download }
$ensureScript = Join-Path $PSScriptRoot 'ensure-native-models.ps1'
$ensureParams = @{
    TalkerModel = $talkerModel
    CodecModel = $codecModel
}
if ($download) {
    if ($download.talker_url) { $ensureParams.TalkerUrl = [string]$download.talker_url }
    if ($download.codec_url) { $ensureParams.CodecUrl = [string]$download.codec_url }
    if ($download.talker_sha256) { $ensureParams.TalkerSha256 = [string]$download.talker_sha256 }
    if ($download.codec_sha256) { $ensureParams.CodecSha256 = [string]$download.codec_sha256 }
}
$model_missing =
    -not (Test-Path -LiteralPath $talkerModel -PathType Leaf) -or
    -not (Test-Path -LiteralPath $codecModel -PathType Leaf)
if (-not $NoDownload) {
    if ($Offline) {
        $ensureParams.Offline = $true
    }
    elseif ($model_missing) {
        $ensureParams.Download = $true
        $ensureParams.RequireHash = $true
    }
    & $ensureScript @ensureParams | Out-Host
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

$workerArgs = @(
    '--runtime-dir', (Resolve-BundlePath $config.runtime_dir),
    '--talker-model', $talkerModel,
    '--codec-model', $codecModel
)
$voiceRegistryValue = if ($VoiceRegistryPath) {
    $VoiceRegistryPath
}
elseif ($config.voice_registry_path) {
    [string]$config.voice_registry_path
}
else {
    Join-Path $root 'config\voice-profiles.json'
}
if (-not [IO.Path]::IsPathRooted($voiceRegistryValue)) {
    $voiceRegistryValue = Join-Path $root $voiceRegistryValue
}
if (Test-Path -LiteralPath $voiceRegistryValue -PathType Leaf) {
    $workerArgs += @('--voice-registry-path', (Resolve-Path -LiteralPath $voiceRegistryValue).Path)
}
elseif ($VoiceRegistryPath -or $config.voice_registry_path) {
    throw "voice registry was explicitly configured but not found: $voiceRegistryValue"
}
if ($config.stream_max_chunk_frames) { $workerArgs += @('--stream-max-chunk-frames', [string]$config.stream_max_chunk_frames) }
if ($config.warmup_synthesis) {
    $workerArgs += '--warmup-synthesis'
    if ($config.warmup_text) { $workerArgs += @('--warmup-text', [string]$config.warmup_text) }
    if ($config.warmup_language) { $workerArgs += @('--warmup-language', [string]$config.warmup_language) }
    if ($config.warmup_voice_id) { $workerArgs += @('--warmup-voice-id', [string]$config.warmup_voice_id) }
}

$player = Resolve-BundlePath $config.player
$worker = Resolve-BundlePath $config.worker
$args = @('--worker', $worker)
foreach ($value in $workerArgs) { $args += @('--worker-arg', $value) }
if ($NoPlayback) { $args += '--no-playback' }
if ($PSBoundParameters.ContainsKey('Text')) { $args += @('--text', $Text) }
& $player @args
exit $LASTEXITCODE
