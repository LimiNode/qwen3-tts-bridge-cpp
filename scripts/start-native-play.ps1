[CmdletBinding()]
param(
    [string]$ConfigPath = (Join-Path $PSScriptRoot '..\config\native-worker.local.json'),
    [string]$Text,
    [switch]$NoPlayback
)

$ErrorActionPreference = 'Stop'
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

$workerArgs = @(
    '--runtime-dir', (Resolve-BundlePath $config.runtime_dir),
    '--talker-model', (Resolve-BundlePath $config.talker_model),
    '--codec-model', (Resolve-BundlePath $config.codec_model)
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
