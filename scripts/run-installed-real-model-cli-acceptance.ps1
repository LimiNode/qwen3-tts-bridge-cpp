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
$repoRoot = Split-Path -Parent $PSScriptRoot
$script:CurrentStage = 'initialization'
$script:CurrentCommand = @()
$script:CurrentExitCode = $null
$script:Invocations = New-Object 'System.Collections.Generic.List[object]'

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

function Set-RunStage([string]$Stage, [string[]]$Command = @()) {
    $script:CurrentStage = $Stage
    $script:CurrentCommand = @($Command)
    $script:CurrentExitCode = $null
}

function Get-Sha256Hex([string]$Path) {
    $algorithm = [Security.Cryptography.SHA256]::Create()
    $stream = $null
    try {
        $stream = [IO.File]::OpenRead($Path)
        return ([BitConverter]::ToString($algorithm.ComputeHash($stream))).Replace('-', '').ToLowerInvariant()
    }
    finally {
        if ($null -ne $stream) { $stream.Dispose() }
        $algorithm.Dispose()
    }
}

function Get-RunArtifacts {
    $summaryPath = Join-Path $runDirectory 'summary.json'
    return @(
        Get-ChildItem -LiteralPath $runDirectory -File -Recurse |
            Where-Object { -not $_.FullName.Equals($summaryPath, [StringComparison]::OrdinalIgnoreCase) } |
            ForEach-Object {
                [ordered]@{
                    path = $_.FullName.Substring($runDirectory.Length + 1).Replace('\', '/')
                    bytes = $_.Length
                    sha256 = Get-Sha256Hex $_.FullName
                }
            }
    )
}

function Write-RunSummary(
    [string]$CaseStatus,
    [string]$CaseReason,
    [string]$ReleaseStatus,
    [string]$ReleaseReason,
    [switch]$IncludeFailure
) {
    $summary = [ordered]@{
        schema_version = 2
        generated_at_utc = [DateTime]::UtcNow.ToString('o')
        scope = 'installed_real_model_cli_acceptance'
        cli_path = $cli
        config_path = $config
        model_path = $model
        model_family = $ModelFamily
        runtime_backend = $RuntimeBackend
        device = $Device
        dtype = $Dtype
        provenance = [ordered]@{
            cli_path = $cli
            python_verifier = $python
            model_path = $model
            config_path = $config
            runtime_backend = $RuntimeBackend
            device = $Device
            dtype = $Dtype
        }
        verification_harness = [ordered]@{
            wav_verifier_path = Join-Path $repoRoot 'tests/python/verify_wav.py'
            wav_verifier_source = 'repository_checkout'
            installed_cli_pythonpath_removed = $true
            clean_package_independence = 'not_proven'
        }
        voice_verification = $voiceVerification
        synth = $synth
        play = $play
        case_result = [ordered]@{ status = $CaseStatus; reason = $CaseReason }
        listening_result = [ordered]@{
            status = 'not_assessed'
            reason = 'Human listening must be recorded separately for these WAV artifacts.'
        }
        release_disposition = [ordered]@{ status = $ReleaseStatus; reason = $ReleaseReason }
        release_status = $ReleaseStatus
        invocations = @($script:Invocations.ToArray())
        artifacts = Get-RunArtifacts
    }
    if ($IncludeFailure) {
        $summary.failure = [ordered]@{
            stage = $script:CurrentStage
            exit_code = $script:CurrentExitCode
            reason = $CaseReason
            command = @($script:CurrentCommand)
        }
    }
    $summaryPath = Join-Path $runDirectory 'summary.json'
    Write-JsonAtomic $summaryPath $summary
    return $summaryPath
}

function Invoke-InstalledCli([string[]]$Arguments, [string]$Label, [string]$LogPath) {
    Set-RunStage $Label $Arguments
    $previous = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $raw = @(& $cli @Arguments 2>&1)
        $exitCode = $LASTEXITCODE
    }
    finally { $ErrorActionPreference = $previous }
    $text = $raw -join [Environment]::NewLine
    Set-Content -LiteralPath $LogPath -Value $text -Encoding UTF8
    $script:CurrentExitCode = $exitCode
    $script:Invocations.Add([ordered]@{
        label = $Label
        arguments = @($Arguments)
        exit_code = $exitCode
        log = $LogPath
    })
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
    Set-RunStage 'validate synth WAV publication' @($synthPath)
    if (-not (Test-Path -LiteralPath $synthPath) -or (Get-Item -LiteralPath $synthPath).Length -le 44) {
        throw 'qwen-tts synth exited successfully but did not publish a non-empty WAV.'
    }
    $verifyScript = Join-Path $repoRoot 'tests/python/verify_wav.py'
    $verifyLog = Join-Path $runDirectory 'synth-verify.log'
    Set-RunStage 'verify synth WAV with checkout harness' @($python, $verifyScript, $synthPath)
    $verifyOutput = @(& $python $verifyScript $synthPath --sample-rate 24000 --channels 1 --bits-per-sample 16 --min-data-bytes 1 2>&1)
    $verifyExitCode = $LASTEXITCODE
    $script:CurrentExitCode = $verifyExitCode
    Set-Content -LiteralPath $verifyLog -Value ($verifyOutput -join [Environment]::NewLine) -Encoding UTF8
    if ($verifyExitCode -ne 0) { throw "synth WAV verification failed: $($verifyOutput -join [Environment]::NewLine)" }

    $play = $null
    if (-not $SkipPlay) {
        $playPath = Join-Path $runDirectory 'play.wav'
        $playLog = Join-Path $runDirectory 'play.log'
        $play = Invoke-InstalledCli ($prefix + @('play') + $base + @('--out', $playPath)) 'qwen-tts play --out' $playLog
        Set-RunStage 'validate play WAV publication' @($playPath)
        if (-not (Test-Path -LiteralPath $playPath) -or (Get-Item -LiteralPath $playPath).Length -le 44) {
            throw 'qwen-tts play exited successfully but did not publish a non-empty WAV.'
        }
        $verifyPlaybackLog = Join-Path $runDirectory 'play-verify.log'
        Set-RunStage 'verify play WAV with checkout harness' @($python, $verifyScript, $playPath)
        $verifyPlayback = @(& $python $verifyScript $playPath --sample-rate 24000 --channels 1 --bits-per-sample 16 --min-data-bytes 1 2>&1)
        $verifyPlaybackExitCode = $LASTEXITCODE
        $script:CurrentExitCode = $verifyPlaybackExitCode
        Set-Content -LiteralPath $verifyPlaybackLog -Value ($verifyPlayback -join [Environment]::NewLine) -Encoding UTF8
        if ($verifyPlaybackExitCode -ne 0) { throw "play WAV verification failed: $($verifyPlayback -join [Environment]::NewLine)" }
    }

    $summaryPath = Write-RunSummary 'pass' 'Installed CLI commands completed and generated WAVs passed the checkout verifier.' 'conditional' 'Human listening, clean relocation and the remaining release gates are assessed separately.'
    Write-Output "summary_json=$summaryPath"
}
catch {
    $failureReason = $_.Exception.Message
    try {
        $summaryPath = Write-RunSummary 'fail' $failureReason 'blocked' 'The installed CLI acceptance command failed; the retained receipt is not a release acceptance.' -IncludeFailure
        Write-Output "summary_json=$summaryPath"
    }
    catch {
        Write-Warning "Failed to write structured acceptance receipt: $($_.Exception.Message)"
    }
    throw
}
finally {
    if ($null -eq $previousPythonPath) { Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue } else { $env:PYTHONPATH = $previousPythonPath }
    if ($null -eq $previousNoUserSite) { Remove-Item Env:PYTHONNOUSERSITE -ErrorAction SilentlyContinue } else { $env:PYTHONNOUSERSITE = $previousNoUserSite }
    if ($null -eq $previousOffline) { Remove-Item Env:HF_HUB_OFFLINE -ErrorAction SilentlyContinue } else { $env:HF_HUB_OFFLINE = $previousOffline }
    if ($null -eq $previousTransformersOffline) { Remove-Item Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue } else { $env:TRANSFORMERS_OFFLINE = $previousTransformersOffline }
}
