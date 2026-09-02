[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$')]
    [string]$VoiceId,
    [Parameter(Mandatory)]
    [string]$ReferenceAudioPath,
    [string]$ReferenceText = "",
    [switch]$XVectorOnly,
    [string]$TestText = "",
    [string]$VoiceRegistryPath = "config\voice-profiles.local.json",
    [switch]$Save,
    [string]$Python = "",
    [string]$ModelPath = "",
    [string]$BuildDirectory = "build"
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$launcher = Join-Path $PSScriptRoot "start-qwen-tts-clone-play.ps1"
$reference = (Resolve-Path -LiteralPath $ReferenceAudioPath).Path
$registryPath = if ([IO.Path]::IsPathRooted($VoiceRegistryPath)) {
    $VoiceRegistryPath
} else {
    Join-Path $repoRoot $VoiceRegistryPath
}
$registryDirectory = Split-Path -Parent $registryPath
New-Item -ItemType Directory -Force -Path $registryDirectory | Out-Null

if (-not $XVectorOnly -and [string]::IsNullOrWhiteSpace($ReferenceText)) {
    throw "ReferenceText is required unless -XVectorOnly is used"
}
if (-not (Test-Path -LiteralPath $launcher)) {
    throw "Voice playback launcher was not found: $launcher"
}

$registry = if (Test-Path -LiteralPath $registryPath) {
    Get-Content -Raw -LiteralPath $registryPath | ConvertFrom-Json
} else {
    [PSCustomObject]@{ schema_version = 1; voices = @() }
}
if ($registry.schema_version -ne 1 -or $null -eq $registry.voices) {
    throw "Voice registry must use schema_version 1 and contain voices"
}

$voice = @{
    voice_id = $VoiceId
    reference_audio_path = $reference
    reference_text = $ReferenceText
    x_vector_only = [bool]$XVectorOnly
}
$registry | Add-Member -Force -NotePropertyName voices -NotePropertyValue @(
    @($registry.voices | Where-Object { $_.voice_id -ne $VoiceId }) + @($voice)
)

$temporaryRegistry = Join-Path ([IO.Path]::GetTempPath()) ("qwen-tts-voice-profile-" + [guid]::NewGuid().ToString("N") + ".json")
try {
    $registry | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $temporaryRegistry -Encoding utf8
    if ([string]::IsNullOrWhiteSpace($TestText)) {
        $TestText = "This is a test of the new voice profile."
    }
    & $launcher `
        -VoiceRegistryPath $temporaryRegistry `
        -VoiceId $VoiceId `
        -Text $TestText `
        -Python $Python `
        -ModelPath $ModelPath `
        -BuildDirectory $BuildDirectory
    if ($LASTEXITCODE -ne 0) {
        throw "Voice profile test synthesis failed"
    }

    $keepProfile = $Save
    if (-not $Save) {
        $answer = Read-Host "Save voice profile '$VoiceId' to $registryPath? [y/N]"
        $keepProfile = $answer -match '^(?i:y|yes)$'
    }
    if ($keepProfile) {
        $temporaryOutput = "$registryPath.tmp"
        $registry | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $temporaryOutput -Encoding utf8
        Move-Item -LiteralPath $temporaryOutput -Destination $registryPath -Force
        Write-Host "Saved voice profile: $VoiceId"
    } else {
        Write-Host "Discarded voice profile: $VoiceId"
    }
}
finally {
    Remove-Item -LiteralPath $temporaryRegistry -Force -ErrorAction SilentlyContinue
}
