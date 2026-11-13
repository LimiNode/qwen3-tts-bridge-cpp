[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$CliPath,

    [Parameter(Mandatory = $true)]
    [string]$PythonPath,

    [Parameter(Mandatory = $true)]
    [string]$ModelPath,

    [Parameter(Mandatory = $true)]
    [string]$ConfigPath,

    [string]$ModelFamily = 'base-1.7b',
    [string]$VoiceId = '',
    [string]$Speaker = '',
    [string]$Instruction = '',
    [string]$Language = 'Russian',
    [string]$Device = 'cuda',
    [string]$Dtype = 'float16',
    [ValidateSet('faster', 'upstream')]
    [string]$RuntimeBackend = 'faster',
    [string]$Text = 'Installed CLI real-model acceptance sample.',
    [string]$OutputRoot = '.tmp\base-acceptance\installed-cli-real-model',
    [switch]$SkipPlay
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
$repoRoot = Split-Path -Parent $PSScriptRoot

function Resolve-ExistingPath([string]$Path, [string]$Description) {
    $candidate = if ([IO.Path]::IsPathRooted($Path)) { $Path } else { Join-Path $repoRoot $Path }
    if (-not (Test-Path -LiteralPath $candidate)) { throw "$Description was not found: $candidate" }
    return (Resolve-Path -LiteralPath $candidate).Path
}

function Write-JsonAtomic([string]$Path, [object]$Value) {
    $directory = [IO.Path]::GetDirectoryName($Path)
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
    $temporary = Join-Path $directory ('.' + [IO.Path]::GetFileName($Path) + '.' + [guid]::NewGuid().ToString('N') + '.tmp')
    $encoding = [Text.UTF8Encoding]::new($false)
    $bytes = $encoding.GetBytes(($Value | ConvertTo-Json -Depth 20) + [Environment]::NewLine)
    $stream = [IO.File]::Open($temporary, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try { $stream.Write($bytes, 0, $bytes.Length); $stream.Flush($true) }
    finally { $stream.Dispose() }
    try {
        if (Test-Path -LiteralPath $Path) { [IO.File]::Replace($temporary, $Path, $null, $true) }
        else { [IO.File]::Move($temporary, $Path) }
    }
    finally { if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Force } }
}

function Invoke-InstalledCli([string[]]$Arguments, [string]$Label, [string]$LogPath) {
    $previous = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $raw = @(& $cli @Arguments 2>&1)
        $exitCode = $LASTEXITCODE
    }
    finally { $ErrorActionPreference = $previous }
    $text = $raw -join [Environment]::NewLine
    Set-Content -LiteralPath $LogPath -Value $text -Encoding UTF8
    if ($exitCode -ne 0) { throw "$Label failed with exit code $exitCode. See $LogPath`n$text" }
    return [ordered]@{ label = $Label; exit_code = $exitCode; log = $LogPath; output = $text }
}

$cli = Resolve-ExistingPath $CliPath 'Installed qwen-tts CLI'
$python = Resolve-ExistingPath $PythonPath 'Python verifier'
$model = Resolve-ExistingPath $ModelPath 'Model'
$config = Resolve-ExistingPath $ConfigPath 'CLI config'
$outputDirectory = if ([IO.Path]::IsPathRooted($OutputRoot)) { $OutputRoot } else { Join-Path $repoRoot $OutputRoot }
$runDirectory = Join-Path $outputDirectory ([DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ'))
New-Item -ItemType Directory -Force -Path $runDirectory | Out-Null

$previousPythonPath = [Environment]::GetEnvironmentVariable('PYTHONPATH', 'Process')
$previousNoUserSite = [Environment]::GetEnvironmentVariable('PYTHONNOUSERSITE', 'Process')
$previousOffline = [Environment]::GetEnvironmentVariable('HF_HUB_OFFLINE', 'Process')
$previousTransformersOffline = [Environment]::GetEnvironmentVariable('TRANSFORMERS_OFFLINE', 'Process')
try {
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    $env:PYTHONNOUSERSITE = '1'
    $env:HF_HUB_OFFLINE = '1'
    $env:TRANSFORMERS_OFFLINE = '1'

    $prefix = @('--config', $config)
    $base = @('--model-family', $ModelFamily, '--model', $model, '--language', $Language,
        '--device', $Device, '--dtype', $Dtype, '--runtime-backend', $RuntimeBackend,
        '--text', $Text)
    if ($VoiceId) { $base += @('--voice-id', $VoiceId) }
    if ($Speaker) { $base += @('--speaker', $Speaker) }
    if ($Instruction) { $base += @('--instruction', $Instruction) }

    $voiceVerification = $null
    if ($VoiceId) {
        $voiceVerifyLog = Join-Path $runDirectory 'voices-verify.log'
        $voiceVerification = Invoke-InstalledCli (
            $prefix + @('voices', 'verify', $VoiceId, '--backend', 'python')
        ) 'qwen-tts voices verify' $voiceVerifyLog
    }

    $synthPath = Join-Path $runDirectory 'synth.wav'
    $synthLog = Join-Path $runDirectory 'synth.log'
    $synth = Invoke-InstalledCli ($prefix + @('synth') + $base + @('--out', $synthPath)) 'qwen-tts synth' $synthLog
    if (-not (Test-Path -LiteralPath $synthPath) -or (Get-Item -LiteralPath $synthPath).Length -le 44) {
        throw 'qwen-tts synth exited successfully but did not publish a non-empty WAV.'
    }
    $verifyOutput = @(& $python (Join-Path $repoRoot 'tests/python/verify_wav.py') $synthPath --sample-rate 24000 --channels 1 --bits-per-sample 16 --min-data-bytes 1 2>&1)
    if ($LASTEXITCODE -ne 0) { throw "synth WAV verification failed: $($verifyOutput -join [Environment]::NewLine)" }

    $play = $null
    if (-not $SkipPlay) {
        $playPath = Join-Path $runDirectory 'play.wav'
        $playLog = Join-Path $runDirectory 'play.log'
        $play = Invoke-InstalledCli ($prefix + @('play') + $base + @('--out', $playPath)) 'qwen-tts play --out' $playLog
        if (-not (Test-Path -LiteralPath $playPath) -or (Get-Item -LiteralPath $playPath).Length -le 44) {
            throw 'qwen-tts play exited successfully but did not publish a non-empty WAV.'
        }
        $verifyPlayback = @(& $python (Join-Path $repoRoot 'tests/python/verify_wav.py') $playPath --sample-rate 24000 --channels 1 --bits-per-sample 16 --min-data-bytes 1 2>&1)
        if ($LASTEXITCODE -ne 0) { throw "play WAV verification failed: $($verifyPlayback -join [Environment]::NewLine)" }
    }

    $summary = [ordered]@{
        schema_version = 1
        generated_at_utc = [DateTime]::UtcNow.ToString('o')
        scope = 'installed_real_model_cli_acceptance'
        cli_path = $cli
        config_path = $config
        model_path = $model
        model_family = $ModelFamily
        runtime_backend = $RuntimeBackend
        voice_verification = $voiceVerification
        synth = $synth
        play = $play
        listening = [ordered]@{ status = 'not_assessed'; reason = 'Human listening must be recorded separately for these WAV artifacts.' }
        release_disposition = 'conditional'
    }
    Write-JsonAtomic (Join-Path $runDirectory 'summary.json') $summary
    Write-Output "summary_json=$(Join-Path $runDirectory 'summary.json')"
}
finally {
    if ($null -eq $previousPythonPath) { Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue } else { $env:PYTHONPATH = $previousPythonPath }
    if ($null -eq $previousNoUserSite) { Remove-Item Env:PYTHONNOUSERSITE -ErrorAction SilentlyContinue } else { $env:PYTHONNOUSERSITE = $previousNoUserSite }
    if ($null -eq $previousOffline) { Remove-Item Env:HF_HUB_OFFLINE -ErrorAction SilentlyContinue } else { $env:HF_HUB_OFFLINE = $previousOffline }
    if ($null -eq $previousTransformersOffline) { Remove-Item Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue } else { $env:TRANSFORMERS_OFFLINE = $previousTransformersOffline }
}
