[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string]$TalkerModel,
    [Parameter(Mandatory = $true)] [string]$CodecModel,
    [string]$TalkerUrl,
    [string]$CodecUrl,
    [string]$TalkerSha256,
    [string]$CodecSha256,
    [switch]$Download,
    [switch]$Offline,
    [switch]$RequireHash
)

$ErrorActionPreference = 'Stop'

function Get-ResolvedFile([string]$Path) {
    return [System.IO.Path]::GetFullPath($Path)
}

function Ensure-Artifact([string]$Path, [string]$Url, [string]$Sha256, [string]$Name) {
    $resolved = Get-ResolvedFile $Path
    $expected = if ($Sha256) { $Sha256.Trim().ToUpperInvariant() } else { '' }
    if (Test-Path -LiteralPath $resolved -PathType Leaf) {
        if ($RequireHash -and -not $expected) {
            throw "$Name exists but no SHA-256 was supplied"
        }
        if ($expected) {
            $actual = (Get-FileHash -LiteralPath $resolved -Algorithm SHA256).Hash
            if ($actual -ne $expected) {
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
    if ($RequireHash -and -not $expected) {
        throw "$Name download requires an explicit SHA-256"
    }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $resolved) | Out-Null
    $partial = "$resolved.partial"
    if (Test-Path -LiteralPath $partial -PathType Leaf) {
        Remove-Item -LiteralPath $partial -Force
    }
    try {
        Invoke-WebRequest -Uri $Url -OutFile $partial
        $actual = (Get-FileHash -LiteralPath $partial -Algorithm SHA256).Hash
        if ($expected -and $actual -ne $expected) {
            throw "$Name download failed SHA-256 validation"
        }
        [System.IO.File]::Move($partial, $resolved)
    }
    catch {
        Remove-Item -LiteralPath $partial -Force -ErrorAction SilentlyContinue
        throw
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
