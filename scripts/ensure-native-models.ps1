[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string]$TalkerModel,
    [Parameter(Mandatory = $true)] [string]$CodecModel,
    [string]$TalkerUrl,
    [string]$CodecUrl,
    [string]$TalkerSha256,
    [string]$CodecSha256,
    [switch]$Download,
    [switch]$Offline
)

$ErrorActionPreference = 'Stop'

function Get-ResolvedFile([string]$Path) {
    return [System.IO.Path]::GetFullPath($Path)
}

function Ensure-Artifact([string]$Path, [string]$Url, [string]$Sha256, [string]$Name) {
    $resolved = Get-ResolvedFile $Path
    if (Test-Path -LiteralPath $resolved -PathType Leaf) {
        if ($Sha256) {
            $actual = (Get-FileHash -LiteralPath $resolved -Algorithm SHA256).Hash
            if ($actual -ne $Sha256.ToUpperInvariant()) {
                throw "$Name exists but SHA-256 does not match the requested value"
            }
        }
        return [pscustomobject]@{ name = $Name; path = $resolved; action = 'existing' }
    }
    if ($Offline -or -not $Download) {
        throw "$Name is missing: $resolved (pass -Download with an explicit URL, or install it while offline)"
    }
    if (-not $Url) {
        throw "$Name is missing and no download URL was supplied"
    }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $resolved) | Out-Null
    Invoke-WebRequest -Uri $Url -OutFile $resolved
    if ($Sha256) {
        $actual = (Get-FileHash -LiteralPath $resolved -Algorithm SHA256).Hash
        if ($actual -ne $Sha256.ToUpperInvariant()) {
            Remove-Item -LiteralPath $resolved -Force
            throw "$Name download failed SHA-256 validation"
        }
    }
    return [pscustomobject]@{ name = $Name; path = $resolved; action = 'downloaded' }
}

if ($Offline -and $Download) {
    throw '-Offline and -Download are mutually exclusive'
}

$result = @(
    Ensure-Artifact $TalkerModel $TalkerUrl $TalkerSha256 'talker_model'
    Ensure-Artifact $CodecModel $CodecUrl $CodecSha256 'codec_model'
)
$result | ConvertTo-Json -Depth 3
