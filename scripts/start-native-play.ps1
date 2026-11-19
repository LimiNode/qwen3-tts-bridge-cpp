[CmdletBinding()]
param(
    [string]$ConfigPath = '',
    [string]$VoiceRegistryPath = '',
    [string]$ModelRoot = '',
    [string]$ModelProfile = '',
    [string]$TalkerModel = '',
    [string]$CodecModel = '',
    [string]$Text,
    [string]$Language = 'auto',
    [string]$VoiceId = '',
    [string]$OutputWav = '',
    [string]$ResultJson = '',
    [uint32]$StartupTimeoutMs = 30000,
    [uint32]$RequestTimeoutMs = 300000,
    [switch]$NoPlayback,
    [switch]$NoTtsFront,
    [switch]$NoDownload,
    [switch]$Offline
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if (-not $ConfigPath) {
    $ConfigPath = Join-Path $root 'config/native-worker.local.json'
    if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) {
        $ConfigPath = Join-Path $root 'config/native-package.example.json'
    }
}
if ($NoDownload -and $Offline) {
    throw '-NoDownload and -Offline are mutually exclusive'
}
if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) {
    throw "native worker config was not found: $ConfigPath (copy config/native-worker.example.json to native-worker.local.json)"
}
$config = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
$required = 'player', 'worker', 'runtime_dir'
foreach ($name in $required) {
    if (-not $config.$name) { throw "native worker config field '$name' is required" }
}

if ($OutputWav -and -not $PSBoundParameters.ContainsKey('Text')) {
    throw '-OutputWav requires -Text'
}
if ($ResultJson -and -not $OutputWav) {
    throw '-ResultJson requires -OutputWav'
}
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
if ($Text -and $Text.Contains([string][char]0x0301) -and
    (-not $profile -or $profile.text_render_capability -ne 'explicit_combining_stress')) {
    throw 'Explicit U+0301 stress requires a compatible model profile'
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
if ($config.require_model_hashes) { $ensureParams.RequireHash = $true }
if ($download) {
    if ($download.talker_url) { $ensureParams.TalkerUrl = [string]$download.talker_url }
    if ($download.codec_url) { $ensureParams.CodecUrl = [string]$download.codec_url }
    if ($download.talker_sha256) { $ensureParams.TalkerSha256 = [string]$download.talker_sha256 }
    if ($download.codec_sha256) { $ensureParams.CodecSha256 = [string]$download.codec_sha256 }
}
$model_missing =
    -not (Test-Path -LiteralPath $talkerModel -PathType Leaf) -or
    -not (Test-Path -LiteralPath $codecModel -PathType Leaf)
if ($config.require_model_hashes -or -not $NoDownload) {
    if ($Offline -or $NoDownload) {
        $ensureParams.Offline = $true
    }
    elseif ($model_missing) {
        $ensureParams.Download = $true
        $ensureParams.RequireHash = $true
    }
    & $ensureScript @ensureParams | Out-Host
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

$executable = if ($OutputWav) {
    if (-not $config.save_wav) { throw "native worker config field 'save_wav' is required for -OutputWav" }
    Resolve-BundlePath $config.save_wav
}
else { Resolve-BundlePath $config.player }
$worker = Resolve-BundlePath $config.worker
$args = @('--worker', $worker)
foreach ($value in $workerArgs) { $args += @('--worker-arg', $value) }
if ($OutputWav) {
    if (-not $ResultJson) { $ResultJson = "$OutputWav.result.json" }
    $args += @('--output', $OutputWav, '--result-json', $ResultJson, '--require-natural-eos')
}
elseif ($NoPlayback) { $args += '--no-playback' }
$args += @('--language', $Language, '--startup-timeout-ms', [string]$StartupTimeoutMs,
    '--request-timeout-ms', [string]$RequestTimeoutMs)
if ($VoiceId) { $args += @('--voice-id', $VoiceId) }
if ($NoTtsFront) {
    $args += '--no-tts-front'
}
elseif ($profile -and $profile.text_render_capability -eq 'explicit_combining_stress') {
    # Rendering capability comes from the selected model profile, not from a
    # filename heuristic. The player still owns the frontend composition.
    $args += '--tts-front-explicit-stress'
}
if ($PSBoundParameters.ContainsKey('Text')) { $args += @('--text', $Text) }
& $executable @args
exit $LASTEXITCODE
