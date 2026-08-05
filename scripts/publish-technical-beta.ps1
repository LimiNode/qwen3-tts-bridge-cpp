[CmdletBinding()]
param(
    [string]$OutputRoot = "dist/QwenTTSBridge-technical-beta",
    [Parameter(Mandatory = $true)]
    [string]$CustomVoiceModelPath,
    [Parameter(Mandatory = $true)]
    [string]$CustomVoiceModelManifest,
    [Parameter(Mandatory = $true)]
    [string]$BaseModelPath,
    [Parameter(Mandatory = $true)]
    [string]$BaseModelManifest,
    [Parameter(Mandatory = $true)]
    [string]$VerifierPython,
    [Parameter(Mandatory = $true)]
    [string]$AcceptanceOutput,
    [string]$BaseVoiceId = "kraftwerk_robot_ru_bootstrap_fidelity",
    [string]$BuildDirectory = "build-mingw",
    [string]$PackagingVenvPath = ".venv-packaging",
    [string]$QwenSourcePath = "external/python/Qwen3-TTS-streaming",
    [string]$FasterQwenSourcePath = "C:\_repoz\faster-qwen3-tts-v032-stack112-clean",
    [string]$MinGwBin = "C:\MinGW\winlibs-x86_64-posix-seh-gcc-16.1.0-mingw-w64ucrt-14.0.0-r3\mingw64\bin",
    [switch]$ReplaceExisting,
    [ValidateSet("", "after_backup", "after_swap", "before_backup_cleanup")]
    [string]$FailurePoint = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot
Import-Module (Join-Path $PSScriptRoot "TechnicalBetaPublication.psm1") -Force

function Resolve-RepoPath {
    param([string]$Path)

    if ([IO.Path]::IsPathRooted($Path)) {
        return [IO.Path]::GetFullPath($Path)
    }
    return [IO.Path]::GetFullPath((Join-Path $RepoRoot $Path))
}

function Get-FileSha256 {
    param([string]$Path)

    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Get-TextSha256 {
    param([string]$Text)

    $bytes = [Text.Encoding]::UTF8.GetBytes($Text)
    $sha256 = [Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($sha256.ComputeHash($bytes))).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $sha256.Dispose()
    }
}

function Get-CleanSourceProvenance {
    $status = @(& git status --porcelain=v1)
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to inspect source worktree status."
    }
    if ($status.Count -ne 0) {
        throw "Technical-beta publication requires a clean source worktree."
    }
    $commit = (& git rev-parse HEAD).Trim()
    $tree = (& git rev-parse "HEAD^{tree}").Trim()
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to resolve source tree provenance."
    }
    $diff = ((& git diff --no-ext-diff --binary HEAD) -join "`n")
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to resolve source diff provenance."
    }
    return [ordered]@{
        source_commit = $commit
        source_tree = $tree
        source_tree_clean = $true
        source_diff_sha256 = Get-TextSha256 $diff
        test_tree_commit = $commit
        package_source_commit = $commit
    }
}

$finalRoot = Resolve-RepoPath $OutputRoot
$finalParent = Split-Path -Parent $finalRoot
$candidateRoot = Join-Path $finalParent ".__qtb-$([Guid]::NewGuid().ToString('N'))"
$validationRoot = Join-Path (Split-Path -Parent $candidateRoot) `
    "$(Split-Path -Leaf $candidateRoot)-relocated"
$relocationReport = "$validationRoot-report.json"
$publishedReport = Join-Path $RepoRoot "tmp\technical-beta-published-$([Guid]::NewGuid().ToString('N')).json"
$acceptancePath = Resolve-RepoPath $AcceptanceOutput
$acceptanceStage = "$acceptancePath.pending-$([Guid]::NewGuid().ToString('N'))"

if (Test-Path -LiteralPath $acceptancePath) {
    throw "AcceptanceOutput already exists; choose a new report path: $acceptancePath"
}
$sourceProvenance = Get-CleanSourceProvenance

# PyTorch loads DLLs by their absolute path. Keep the staging root deliberately
# short so package validation does not fail before the atomic publish step.
$longestStagedDll = Join-Path $candidateRoot `
    "worker\python\Lib\site-packages\torch\lib\cudnn_engines_precompiled64_9.dll"
if ($longestStagedDll.Length -gt 240) {
    throw "Technical-beta staging path is too long for Windows DLL loading ($($longestStagedDll.Length) characters): $longestStagedDll"
}

try {
    & (Join-Path $PSScriptRoot "package-technical-beta.ps1") `
        -OutputRoot $candidateRoot `
        -BuildDirectory $BuildDirectory `
        -PackagingVenvPath $PackagingVenvPath `
        -QwenSourcePath $QwenSourcePath `
        -FasterQwenSourcePath $FasterQwenSourcePath `
        -MinGwBin $MinGwBin
    if ($LASTEXITCODE -ne 0) {
        throw "Technical-beta package build failed."
    }

    & (Join-Path $PSScriptRoot "test-technical-beta-relocation.ps1") `
        -PackageRoot $candidateRoot `
        -RelocationRoot $validationRoot `
        -CustomVoiceModelPath $CustomVoiceModelPath `
        -CustomVoiceModelManifest $CustomVoiceModelManifest `
        -BaseModelPath $BaseModelPath `
        -BaseModelManifest $BaseModelManifest `
        -VerifierPython $VerifierPython `
        -BaseVoiceId $BaseVoiceId `
        -ReportPath $relocationReport `
        -MinGwBin $MinGwBin
    if ($LASTEXITCODE -ne 0) {
        throw "Technical-beta relocated acceptance failed."
    }

    Move-TechnicalBetaDirectoryAtomically -Candidate $candidateRoot -Final $finalRoot `
        -AllowReplacement:$ReplaceExisting -FailurePoint $FailurePoint -ValidatePublished {
            param($publishedRoot)
            & (Join-Path $PSScriptRoot "test-technical-beta-relocation.ps1") `
                -PackageRoot $publishedRoot `
                -InPlace `
                -CustomVoiceModelPath $CustomVoiceModelPath `
                -CustomVoiceModelManifest $CustomVoiceModelManifest `
                -BaseModelPath $BaseModelPath `
                -BaseModelManifest $BaseModelManifest `
                -VerifierPython $VerifierPython `
                -BaseVoiceId $BaseVoiceId `
                -ReportPath $publishedReport `
                -MinGwBin $MinGwBin
            if ($LASTEXITCODE -ne 0) {
                throw "Published technical-beta validation failed."
            }
        }

    $packageTree = Get-Content -LiteralPath (Join-Path $finalRoot "manifests/package-tree-manifest.json") -Raw | ConvertFrom-Json
    $voiceAssets = Get-Content -LiteralPath (Join-Path $finalRoot "manifests/voice-assets-manifest.json") -Raw | ConvertFrom-Json
    $customManifest = Get-Content -LiteralPath $CustomVoiceModelManifest -Raw | ConvertFrom-Json
    $baseManifest = Get-Content -LiteralPath $BaseModelManifest -Raw | ConvertFrom-Json
    $relocation = Get-Content -LiteralPath $relocationReport -Raw | ConvertFrom-Json
    $published = Get-Content -LiteralPath $publishedReport -Raw | ConvertFrom-Json
    $files = Get-ChildItem -LiteralPath $finalRoot -Recurse -Force -File
    $acceptance = [ordered]@{
        schema_version = 2
        package_id = "QwenTTSBridge-technical-beta-r3"
        source = $sourceProvenance
        package = [ordered]@{
            file_count = @($files).Count
            size_bytes = [long](($files | Measure-Object -Property Length -Sum).Sum)
            package_tree_manifest_sha256 = $packageTree.package_tree_manifest_sha256
            voice_assets_manifest_sha256 = $voiceAssets.voice_assets_manifest_sha256
            worker_build_manifest_sha256 = Get-FileSha256 (Join-Path $finalRoot "worker\build-manifest.json")
            immutable_tree_policy = $published.package.immutable_tree_policy
        }
        models = [ordered]@{
            custom_voice = [ordered]@{
                repository = $customManifest.repository
                revision = $customManifest.revision
                directory_manifest_sha256 = $customManifest.directory_manifest_sha256
            }
            base = [ordered]@{
                repository = $baseManifest.repository
                revision = $baseManifest.revision
                directory_manifest_sha256 = $baseManifest.directory_manifest_sha256
            }
        }
        acceptance = [ordered]@{
            relocated_candidate = $relocation
            published_destination = $published
        }
    }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $acceptanceStage) | Out-Null
    [IO.File]::WriteAllText(
        $acceptanceStage,
        (($acceptance | ConvertTo-Json -Depth 12) + [Environment]::NewLine),
        [Text.UTF8Encoding]::new($false)
    )
    Move-Item -LiteralPath $acceptanceStage -Destination $acceptancePath
    Remove-Item -LiteralPath $publishedReport -Force
}
catch {
    if (Test-Path -LiteralPath $candidateRoot) {
        Remove-Item -LiteralPath $candidateRoot -Recurse -Force
    }
    if (Test-Path -LiteralPath $acceptanceStage) {
        Remove-Item -LiteralPath $acceptanceStage -Force
    }
    if (Test-Path -LiteralPath $publishedReport) {
        Remove-Item -LiteralPath $publishedReport -Force
    }
    throw
}

Write-Host "Technical-beta package published: $finalRoot"
Write-Host "Technical-beta acceptance evidence: $acceptancePath"
