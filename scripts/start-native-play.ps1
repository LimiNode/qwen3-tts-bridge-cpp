[CmdletBinding()]
param(
    [string]$ConfigPath = (Join-Path $PSScriptRoot '..\config\native-worker.local.json'),
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
$required = 'player', 'worker', 'runtime_dir', 'talker_model', 'codec_model'
foreach ($name in $required) {
    if (-not $config.$name) { throw "native worker config field '$name' is required" }
}

$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
function Resolve-BundlePath([string]$value) {
    if ([System.IO.Path]::IsPathRooted($value)) { return $value }
    return Join-Path $root $value
}

$talkerModel = Resolve-BundlePath $config.talker_model
$codecModel = Resolve-BundlePath $config.codec_model
$download = $config.model_download
$ensureScript = Join-Path $PSScriptRoot 'ensure-native-models.ps1'
$ensureArgs = @(
    '-TalkerModel', $talkerModel,
    '-CodecModel', $codecModel
)
if ($download) {
    if ($download.talker_url) { $ensureArgs += @('-TalkerUrl', [string]$download.talker_url) }
    if ($download.codec_url) { $ensureArgs += @('-CodecUrl', [string]$download.codec_url) }
    if ($download.talker_sha256) { $ensureArgs += @('-TalkerSha256', [string]$download.talker_sha256) }
    if ($download.codec_sha256) { $ensureArgs += @('-CodecSha256', [string]$download.codec_sha256) }
}
$model_missing =
    -not (Test-Path -LiteralPath $talkerModel -PathType Leaf) -or
    -not (Test-Path -LiteralPath $codecModel -PathType Leaf)
if (-not $NoDownload) {
    if ($Offline) {
        $ensureArgs += '-Offline'
    }
    elseif ($model_missing) {
        $ensureArgs += @('-Download', '-RequireHash')
    }
    & $ensureScript @ensureArgs | Out-Host
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

$workerArgs = @(
    '--runtime-dir', (Resolve-BundlePath $config.runtime_dir),
    '--talker-model', $talkerModel,
    '--codec-model', $codecModel
)
if ($config.voice_registry_path) { $workerArgs += @('--voice-registry-path', (Resolve-BundlePath $config.voice_registry_path)) }
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
