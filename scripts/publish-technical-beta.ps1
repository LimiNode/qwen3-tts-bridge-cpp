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
    [switch]$ReplaceExisting
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot
$MarkerName = ".qtb-technical-beta-root"

function Resolve-RepoPath {
    param([string]$Path)

    if ([IO.Path]::IsPathRooted($Path)) {
        return [IO.Path]::GetFullPath($Path)
    }
    return [IO.Path]::GetFullPath((Join-Path $RepoRoot $Path))
}

function Assert-ExistingTechnicalBetaRoot {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath (Join-Path $Path $MarkerName))) {
        throw "Refusing to replace output without technical-beta marker: $Path"
    }
}

function Replace-DirectoryAtomically {
    param([string]$Candidate, [string]$Final, [switch]$AllowReplacement)

    if (-not (Test-Path -LiteralPath $Final)) {
        Move-Item -LiteralPath $Candidate -Destination $Final
        return
    }
    Assert-ExistingTechnicalBetaRoot $Final
    if (-not $AllowReplacement) {
        throw "Output already exists; pass -ReplaceExisting to publish a validated replacement: $Final"
    }

    $backup = "$Final.backup-$([Guid]::NewGuid().ToString('N'))"
    Move-Item -LiteralPath $Final -Destination $backup
    try {
        Move-Item -LiteralPath $Candidate -Destination $Final
    }
    catch {
        if (-not (Test-Path -LiteralPath $Final) -and (Test-Path -LiteralPath $backup)) {
            Move-Item -LiteralPath $backup -Destination $Final
        }
        throw
    }
    Remove-Item -LiteralPath $backup -Recurse -Force
}

function Get-FileSha256 {
    param([string]$Path)

    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

$finalRoot = Resolve-RepoPath $OutputRoot
$candidateRoot = Join-Path $RepoRoot "dist\.p-$([Guid]::NewGuid().ToString('N'))"
$validationRoot = Join-Path (Split-Path -Parent $candidateRoot) `
    "$(Split-Path -Leaf $candidateRoot)-relocated"
$relocationReport = "$validationRoot-report.json"
$acceptancePath = Resolve-RepoPath $AcceptanceOutput
$acceptanceStage = "$acceptancePath.pending-$([Guid]::NewGuid().ToString('N'))"

if (Test-Path -LiteralPath $acceptancePath) {
    throw "AcceptanceOutput already exists; choose a new report path: $acceptancePath"
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

    $packageTree = Get-Content -LiteralPath (Join-Path $candidateRoot "manifests/package-tree-manifest.json") -Raw |
        ConvertFrom-Json
    $voiceAssets = Get-Content -LiteralPath (Join-Path $candidateRoot "manifests/voice-assets-manifest.json") -Raw |
        ConvertFrom-Json
    $customManifest = Get-Content -LiteralPath $CustomVoiceModelManifest -Raw | ConvertFrom-Json
    $baseManifest = Get-Content -LiteralPath $BaseModelManifest -Raw | ConvertFrom-Json
    $relocation = Get-Content -LiteralPath $relocationReport -Raw | ConvertFrom-Json
    $files = Get-ChildItem -LiteralPath $candidateRoot -Recurse -Force -File
    $acceptance = [ordered]@{
        schema_version = 1
        package_id = "QwenTTSBridge-technical-beta-r2"
        source_commit = ((& git rev-parse HEAD).Trim())
        package = [ordered]@{
            file_count = @($files).Count
            size_bytes = [long](($files | Measure-Object -Property Length -Sum).Sum)
            package_tree_manifest_sha256 = $packageTree.package_tree_manifest_sha256
            voice_assets_manifest_sha256 = $voiceAssets.voice_assets_manifest_sha256
            worker_build_manifest_sha256 = Get-FileSha256 (Join-Path $candidateRoot "worker\build-manifest.json")
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
            validation_kind = $relocation.validation_kind
            native_closure = "passed"
            manifests_before_and_after_smokes = "passed"
            custom_voice_natural_eos_sha256 = $relocation.smokes.custom_voice.output_sha256
            base_natural_eos_sha256 = $relocation.smokes.base.output_sha256
            base_voice_id = $BaseVoiceId
            bytecode_files = 0
        }
    }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $acceptanceStage) | Out-Null
    [IO.File]::WriteAllText(
        $acceptanceStage,
        (($acceptance | ConvertTo-Json -Depth 6) + [Environment]::NewLine),
        [Text.UTF8Encoding]::new($false)
    )

    Replace-DirectoryAtomically -Candidate $candidateRoot -Final $finalRoot `
        -AllowReplacement:$ReplaceExisting
    Move-Item -LiteralPath $acceptanceStage -Destination $acceptancePath
}
catch {
    if (Test-Path -LiteralPath $candidateRoot) {
        Remove-Item -LiteralPath $candidateRoot -Recurse -Force
    }
    if (Test-Path -LiteralPath $acceptanceStage) {
        Remove-Item -LiteralPath $acceptanceStage -Force
    }
    throw
}

Write-Host "Technical-beta package published: $finalRoot"
Write-Host "Technical-beta acceptance evidence: $acceptancePath"
