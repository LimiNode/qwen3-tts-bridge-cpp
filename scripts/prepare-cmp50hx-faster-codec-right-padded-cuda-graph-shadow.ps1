param(
    [string]$SourcePath = 'tmp\cmp50hx-faster-codec-right-padded-shadow',

    [string]$DestinationPath = 'tmp\cmp50hx-faster-codec-right-padded-cuda-graph-shadow'
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$expectedModelSha256 = '5BE53385B0DAB675DD1EED8B4306AFD515C2FAC5C89A43EF7BEA81D2A97C17E8'

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

$source = Resolve-RepoPath $SourcePath 'Right-padded Faster shadow source'
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
    throw "Right-padded Faster shadow has no model.py: $sourceModel"
}
$sourceHash = (Get-FileHash -LiteralPath $sourceModel -Algorithm SHA256).Hash
if ($sourceHash -ne $expectedModelSha256) {
    throw "Right-padded Faster shadow model.py fingerprint is unsupported: expected $expectedModelSha256, got $sourceHash"
}

$patch = Join-Path $PSScriptRoot 'patches\cmp50hx-faster-codec-right-padded-cuda-graph.patch'
if (-not (Test-Path -LiteralPath $patch -PathType Leaf)) {
    throw "Manual codec CUDA graph patch was not found: $patch"
}

Copy-Item -LiteralPath $source -Destination $destination -Recurse -ErrorAction Stop
try {
    & git apply --check "--directory=$destinationRelative" $patch
    if ($LASTEXITCODE -ne 0) {
        throw "Manual codec CUDA graph patch check failed (exit=$LASTEXITCODE)"
    }
    & git apply "--directory=$destinationRelative" $patch
    if ($LASTEXITCODE -ne 0) {
        throw "Manual codec CUDA graph patch apply failed (exit=$LASTEXITCODE)"
    }
    $candidateModel = Join-Path $destination 'faster_qwen3_tts\model.py'
    foreach ($marker in @('def _decode_right_padded_window(', 'def _capture_right_padded_decoder_cuda_graph(')) {
        if (-not (Select-String -LiteralPath $candidateModel -SimpleMatch $marker -Quiet)) {
            throw "Manual codec CUDA graph patch did not add its expected marker: $marker"
        }
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
