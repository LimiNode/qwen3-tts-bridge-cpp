param(
    [string]$PythonPackageRoot = "dist/QwenTTSBridge",
    [Parameter(Mandatory = $true)]
    [string]$SaveWavExecutable,
    [string]$PlayExecutable,
    [string[]]$RuntimeDependency = @(),
    [string[]]$ConfigExample = @("config/qwen-tts.example.json"),
    [string]$OutputRoot = "dist/QwenTTSBridge-release",
    [string]$Python = "python",
    [switch]$Clean
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$ReleaseMarker = ".qtb-portable-release-root"

function Resolve-InputPath {
    param([string]$Path)

    if ([IO.Path]::IsPathRooted($Path)) {
        return [IO.Path]::GetFullPath($Path)
    }
    return [IO.Path]::GetFullPath((Join-Path $RepoRoot $Path))
}

function Assert-SafeReleaseTarget {
    param([string]$Path)

    $Resolved = [IO.Path]::GetFullPath($Path).TrimEnd("\", "/")
    $Forbidden = @(
        [IO.Path]::GetFullPath($RepoRoot).TrimEnd("\", "/"),
        [IO.Path]::GetPathRoot($Resolved).TrimEnd("\", "/")
    )
    if ($Forbidden -contains $Resolved) {
        throw "Refusing to use broad release output path: $Resolved"
    }
}

function Copy-Tree {
    param([string]$Source, [string]$Destination)

    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    & robocopy $Source $Destination /E /COPY:DAT /DCOPY:DAT /R:1 /W:1 /NFL /NDL /NJH /NJS | Out-Null
    if ($LASTEXITCODE -gt 7) {
        throw "robocopy failed: $Source -> $Destination (exit $LASTEXITCODE)"
    }
}

function Get-FileIdentity {
    param([string]$Path, [string]$RelativePath, [string]$SourceName)

    $Item = Get-Item -LiteralPath $Path
    return [ordered]@{
        path = $RelativePath.Replace("\", "/")
        size_bytes = $Item.Length
        sha256 = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
        source_name = $SourceName
    }
}

$ResolvedPythonPackage = Resolve-InputPath $PythonPackageRoot
$ResolvedSaveWav = Resolve-InputPath $SaveWavExecutable
$ResolvedPlay = if ($PlayExecutable) { Resolve-InputPath $PlayExecutable } else { $null }
$ResolvedOutput = if ([IO.Path]::IsPathRooted($OutputRoot)) {
    [IO.Path]::GetFullPath($OutputRoot)
}
else {
    [IO.Path]::GetFullPath((Join-Path $RepoRoot $OutputRoot))
}
Assert-SafeReleaseTarget $ResolvedOutput

$RequiredPackageFiles = @(
    (Join-Path $ResolvedPythonPackage "qwen-tts.cmd"),
    (Join-Path $ResolvedPythonPackage "worker-python/.qtb-portable-worker-root"),
    (Join-Path $ResolvedPythonPackage "worker-python/build-manifest.json"),
    (Join-Path $ResolvedPythonPackage "worker-python/portable-python-tree-manifest.json")
)
foreach ($Required in $RequiredPackageFiles) {
    if (-not (Test-Path -LiteralPath $Required -PathType Leaf)) {
        throw "Portable Python package is incomplete: $Required"
    }
}
if (-not (Test-Path -LiteralPath $ResolvedSaveWav -PathType Leaf)) {
    throw "Explicit qwen_tts_save_wav executable was not found: $ResolvedSaveWav"
}
if ($ResolvedPlay -and -not (Test-Path -LiteralPath $ResolvedPlay -PathType Leaf)) {
    throw "Explicit qwen_tts_play executable was not found: $ResolvedPlay"
}

& $Python (Join-Path $RepoRoot "scripts/runtime_tree_manifest.py") verify `
    --root (Join-Path $ResolvedPythonPackage "worker-python/python") `
    --manifest (Join-Path $ResolvedPythonPackage "worker-python/portable-python-tree-manifest.json")
if ($LASTEXITCODE -ne 0) {
    throw "Portable Python runtime tree manifest verification failed."
}

$Dependencies = @()
foreach ($Dependency in $RuntimeDependency) {
    $ResolvedDependency = Resolve-InputPath $Dependency
    if (-not (Test-Path -LiteralPath $ResolvedDependency -PathType Leaf)) {
        throw "Explicit runtime dependency was not found: $ResolvedDependency"
    }
    $Dependencies += $ResolvedDependency
}
$Examples = @()
foreach ($Example in $ConfigExample) {
    $ResolvedExample = Resolve-InputPath $Example
    if (-not (Test-Path -LiteralPath $ResolvedExample -PathType Leaf)) {
        throw "Configuration example was not found: $ResolvedExample"
    }
    $Examples += $ResolvedExample
}

if (Test-Path -LiteralPath $ResolvedOutput) {
    if (-not $Clean) {
        throw "Release output already exists; pass -Clean after verifying the target: $ResolvedOutput"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $ResolvedOutput $ReleaseMarker) -PathType Leaf)) {
        throw "Refusing to clean release output without marker: $ResolvedOutput"
    }
    Remove-Item -LiteralPath $ResolvedOutput -Recurse -Force
}

$OutputParent = Split-Path -Parent $ResolvedOutput
New-Item -ItemType Directory -Force -Path $OutputParent | Out-Null
$Staging = Join-Path $OutputParent ("." + (Split-Path -Leaf $ResolvedOutput) + ".assembling")
if (Test-Path -LiteralPath $Staging) {
    if (-not (Test-Path -LiteralPath (Join-Path $Staging $ReleaseMarker) -PathType Leaf)) {
        throw "Refusing to clean release staging without marker: $Staging"
    }
    Remove-Item -LiteralPath $Staging -Recurse -Force
}

try {
    New-Item -ItemType Directory -Force -Path $Staging | Out-Null
    [IO.File]::WriteAllText(
        (Join-Path $Staging $ReleaseMarker),
        "QwenTTSBridge portable release output.`r`n",
        [Text.UTF8Encoding]::new($false)
    )
    Copy-Tree -Source $ResolvedPythonPackage -Destination $Staging

    $Bin = Join-Path $Staging "bin"
    New-Item -ItemType Directory -Force -Path $Bin | Out-Null
    $SaveWavDestination = Join-Path $Bin "qwen_tts_save_wav.exe"
    Copy-Item -LiteralPath $ResolvedSaveWav -Destination $SaveWavDestination
    $PlayDestination = $null
    if ($ResolvedPlay) {
        $PlayDestination = Join-Path $Bin "qwen_tts_play.exe"
        Copy-Item -LiteralPath $ResolvedPlay -Destination $PlayDestination
    }

    $DependencyIdentities = @()
    foreach ($Dependency in $Dependencies) {
        $Name = Split-Path -Leaf $Dependency
        $Destination = Join-Path $Bin $Name
        if (Test-Path -LiteralPath $Destination) {
            throw "Runtime dependency collides with another release file: $Name"
        }
        Copy-Item -LiteralPath $Dependency -Destination $Destination
        $DependencyIdentities += Get-FileIdentity `
            -Path $Destination `
            -RelativePath "bin/$Name" `
            -SourceName $Name
    }

    $ConfigRoot = Join-Path $Staging "config"
    New-Item -ItemType Directory -Force -Path $ConfigRoot | Out-Null
    foreach ($Example in $Examples) {
        Copy-Item -LiteralPath $Example -Destination (Join-Path $ConfigRoot (Split-Path -Leaf $Example))
    }

    $SourceRevision = (& git -C $RepoRoot rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to record source Git revision."
    }
    $ReleaseFiles = @(
        Get-ChildItem -LiteralPath $Staging -Recurse -File |
            Where-Object {
                $_.Name -ne "release-manifest.json" -and
                -not $_.FullName.StartsWith(
                    (Join-Path $Staging "models").TrimEnd("\") + "\",
                    [StringComparison]::OrdinalIgnoreCase
                )
            } |
            Sort-Object FullName |
            ForEach-Object {
                $Relative = $_.FullName.Substring($Staging.Length).TrimStart("\", "/")
                Get-FileIdentity -Path $_.FullName -RelativePath $Relative -SourceName $_.Name
            }
    )
    $Manifest = [ordered]@{
        release_manifest_schema_version = 1
        source_git_revision = $SourceRevision
        generated_at_utc = [DateTime]::UtcNow.ToString("o")
        components = [ordered]@{
            python_worker_build_manifest = Get-FileIdentity `
                -Path (Join-Path $Staging "worker-python/build-manifest.json") `
                -RelativePath "worker-python/build-manifest.json" `
                -SourceName "build-manifest.json"
            save_wav_executable = Get-FileIdentity `
                -Path $SaveWavDestination `
                -RelativePath "bin/qwen_tts_save_wav.exe" `
                -SourceName (Split-Path -Leaf $ResolvedSaveWav)
            play_executable = if ($PlayDestination) {
                Get-FileIdentity `
                    -Path $PlayDestination `
                    -RelativePath "bin/qwen_tts_play.exe" `
                    -SourceName (Split-Path -Leaf $ResolvedPlay)
            }
            else { $null }
            runtime_dependencies = $DependencyIdentities
        }
        release_files = $ReleaseFiles
        mutable_paths = @("models/")
    }
    $ManifestJson = $Manifest | ConvertTo-Json -Depth 8
    [IO.File]::WriteAllText(
        (Join-Path $Staging "release-manifest.json"),
        $ManifestJson,
        [Text.UTF8Encoding]::new($false)
    )
    Move-Item -LiteralPath $Staging -Destination $ResolvedOutput
}
catch {
    if (Test-Path -LiteralPath $Staging) {
        if (Test-Path -LiteralPath (Join-Path $Staging $ReleaseMarker) -PathType Leaf) {
            Remove-Item -LiteralPath $Staging -Recurse -Force
        }
    }
    throw
}

Write-Host "Portable release assembled: $ResolvedOutput"
Write-Host "Release manifest: $(Join-Path $ResolvedOutput 'release-manifest.json')"
