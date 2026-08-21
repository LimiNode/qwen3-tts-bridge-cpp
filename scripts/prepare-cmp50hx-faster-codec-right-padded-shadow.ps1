param(
    [string]$SourcePath = 'tmp\cmp50hx-faster-eager-shadow',

    [string]$DestinationPath = 'tmp\cmp50hx-faster-codec-right-padded-shadow'
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$expectedModelSha256 = '9A497CBCEA3CC1E5F9D7241CDBED2C3DB0A35707863E61F2A8C1808B20C3A20D'

function Resolve-RepoPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [string]$Description
    )

    $candidate = if ([IO.Path]::IsPathRooted($Path)) { $Path } else { Join-Path $repo $Path }
    if (-not (Test-Path -LiteralPath $candidate)) {
        throw "$Description was not found: $candidate"
    }
    return (Resolve-Path -LiteralPath $candidate).Path
}

$source = Resolve-RepoPath $SourcePath 'Frozen Faster shadow source'
$destination = if ([IO.Path]::IsPathRooted($DestinationPath)) {
    $DestinationPath
}
else {
    Join-Path $repo $DestinationPath
}
if (Test-Path -LiteralPath $destination) {
    throw "Candidate destination already exists: $destination"
}
$repositoryRoot = [IO.Path]::GetFullPath($repo).TrimEnd('\', '/')
$destinationAbsolute = [IO.Path]::GetFullPath($destination)
if (-not $destinationAbsolute.StartsWith(
        $repositoryRoot + [IO.Path]::DirectorySeparatorChar,
        [StringComparison]::OrdinalIgnoreCase)) {
    throw "Candidate destination must remain under the repository: $destination"
}
$destinationRelative = $destinationAbsolute.Substring($repositoryRoot.Length).TrimStart('\', '/').Replace('\', '/')

$sourceModel = Join-Path $source 'faster_qwen3_tts\model.py'
if (-not (Test-Path -LiteralPath $sourceModel -PathType Leaf)) {
    throw "Frozen Faster shadow has no model.py: $sourceModel"
}
$sourceHash = (Get-FileHash -LiteralPath $sourceModel -Algorithm SHA256).Hash
if ($sourceHash -ne $expectedModelSha256) {
    throw "Frozen Faster shadow model.py fingerprint is unsupported: expected $expectedModelSha256, got $sourceHash"
}

$patch = Join-Path $PSScriptRoot 'patches\cmp50hx-faster-codec-right-padded-decode.patch'
if (-not (Test-Path -LiteralPath $patch -PathType Leaf)) {
    throw "Right-padded codec patch was not found: $patch"
}

Copy-Item -LiteralPath $source -Destination $destination -Recurse -ErrorAction Stop
try {
    & git apply --check "--directory=$destinationRelative" $patch
    if ($LASTEXITCODE -ne 0) {
        throw "Right-padded codec patch check failed (exit=$LASTEXITCODE)"
    }
    & git apply "--directory=$destinationRelative" $patch
    if ($LASTEXITCODE -ne 0) {
        throw "Right-padded codec patch apply failed (exit=$LASTEXITCODE)"
    }
    $candidateModel = Join-Path $destination 'faster_qwen3_tts\model.py'
    if (-not (Select-String -LiteralPath $candidateModel -SimpleMatch `
            'def _decode_right_padded_window(' -Quiet)) {
        throw 'Right-padded codec patch did not add its expected marker'
    }
}
catch {
    if (Test-Path -LiteralPath $destination) {
        Remove-Item -LiteralPath $destination -Recurse -Force
    }
    throw
}

$candidateModel = Join-Path $destination 'faster_qwen3_tts\model.py'
Write-Output "candidate_shadow=$destination"
Write-Output "candidate_model_sha256=$((Get-FileHash -LiteralPath $candidateModel -Algorithm SHA256).Hash)"
