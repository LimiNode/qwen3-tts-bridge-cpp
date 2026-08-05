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
    [ValidateSet("", "before_backup", "after_backup", "after_swap", "before_backup_cleanup")]
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
        artifact_source_commit = $commit
        acceptance_tooling_commit = $commit
        report_generation_commit = $commit
        source_commit = $commit
        source_tree = $tree
        source_tree_clean = $true
        source_diff_sha256 = Get-TextSha256 $diff
        test_tree_commit = $commit
        package_source_commit = $commit
    }
}

function Test-RelocationAcceptanceReport {
    param([object]$Report, [string]$Name)

    $requiredGateNames = @(
        "package_tree_pre_smoke",
        "voice_assets_pre_smoke",
        "native_closure",
        "custom_voice_doctor_pre_smoke",
        "base_doctor_pre_smoke",
        "custom_voice_natural_eos",
        "base_natural_eos",
        "custom_voice_doctor_post_smoke",
        "base_doctor_post_smoke",
        "no_bytecode",
        "package_tree_post_smoke",
        "voice_assets_post_smoke"
    )
    if ($Report.schema_version -ne 4 -or -not $Report.acceptance_pass -or $null -eq $Report.required_gates) {
        throw "$Name report does not declare a passing required-gate set."
    }
    $actualGateNames = @($Report.required_gates.PSObject.Properties.Name)
    if (@($actualGateNames | Where-Object { $_ -notin $requiredGateNames }).Count -ne 0 -or
        @($requiredGateNames | Where-Object { $_ -notin $actualGateNames }).Count -ne 0 -or
        $actualGateNames.Count -ne $requiredGateNames.Count) {
        throw "$Name report does not contain the exact required-gate set."
    }
    foreach ($gateName in $requiredGateNames) {
        if ($Report.required_gates.$gateName -isnot [bool] -or -not $Report.required_gates.$gateName) {
            throw "$Name report has a non-passing required gate: $gateName"
        }
    }
}

function Test-FaultInjectionReport {
    param([object]$Report)

    $requiredCases = @(
        "replace_success", "replace_before_backup", "replace_after_backup",
        "replace_after_swap", "replace_published_validation_failure",
        "replace_before_backup_cleanup", "first_publish_after_swap",
        "first_publish_validation_failure"
    )
    if ($Report.schema_version -ne 2 -or -not $Report.acceptance_pass) {
        throw "Fault-injection report did not pass."
    }
    $actualCaseNames = @($Report.cases | ForEach-Object { $_.name })
    if (@($actualCaseNames | Where-Object { $_ -notin $requiredCases }).Count -ne 0 -or
        @($requiredCases | Where-Object { $_ -notin $actualCaseNames }).Count -ne 0 -or
        $actualCaseNames.Count -ne $requiredCases.Count) {
        throw "Fault-injection report does not contain the exact case set."
    }
    foreach ($name in $requiredCases) {
        $case = @($Report.cases | Where-Object { $_.name -eq $name })
        if ($case.Count -ne 1 -or -not $case[0].pass) {
            throw "Fault-injection report is missing a passing case: $name"
        }
    }
}

function Test-TechnicalBetaEvidenceSchema {
    param([string]$Kind, [string]$ReportPath)

    & $VerifierPython (Join-Path $PSScriptRoot "validate_technical_beta_acceptance.py") `
        --kind $Kind `
        --report $ReportPath
    if ($LASTEXITCODE -ne 0) {
        throw "Technical-beta $Kind evidence failed fail-closed schema validation."
    }
}

$finalRoot = Resolve-RepoPath $OutputRoot
$finalParent = Split-Path -Parent $finalRoot
$candidateRoot = Join-Path $finalParent ".__qtb-$([Guid]::NewGuid().ToString('N'))"
$validationRoot = Join-Path (Split-Path -Parent $candidateRoot) `
    "$(Split-Path -Leaf $candidateRoot)-relocated"
$relocationReport = "$validationRoot-report.json"
$publishedReport = Join-Path $RepoRoot "tmp\technical-beta-published-$([Guid]::NewGuid().ToString('N')).json"
$faultReport = Join-Path $RepoRoot "tmp\technical-beta-publication-faults-$([Guid]::NewGuid().ToString('N')).json"
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
    & (Join-Path $PSScriptRoot "test-technical-beta-publication.ps1") -ReportPath $faultReport
    if ($LASTEXITCODE -ne 0) {
        throw "Technical-beta publication fault-injection tests failed."
    }
    $faultInjection = Get-Content -LiteralPath $faultReport -Raw | ConvertFrom-Json
    Test-TechnicalBetaEvidenceSchema -Kind "fault" -ReportPath $faultReport
    Test-FaultInjectionReport -Report $faultInjection

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
    Test-TechnicalBetaEvidenceSchema -Kind "relocation" -ReportPath $relocationReport
    Test-TechnicalBetaEvidenceSchema -Kind "relocation" -ReportPath $publishedReport
    Test-RelocationAcceptanceReport -Report $relocation -Name "Relocated candidate"
    Test-RelocationAcceptanceReport -Report $published -Name "Published destination"
    $candidateManifestDigest = $relocation.package.verified_manifest_digest
    $publishedManifestDigest = $published.package.verified_manifest_digest
    if ($candidateManifestDigest -ne $publishedManifestDigest) {
        throw "Candidate and published verified manifest digests differ."
    }
    $files = Get-ChildItem -LiteralPath $finalRoot -Recurse -Force -File
    $requiredGates = [ordered]@{
        pre_publish_validation = $relocation.acceptance_pass
        post_publish_validation = $published.acceptance_pass
        verified_manifest_digest_match = $candidateManifestDigest -eq $publishedManifestDigest
        sealed_tree_unchanged = (
            $relocation.post_smoke.sealed_tree_unchanged -and
            $published.post_smoke.sealed_tree_unchanged
        )
        runtime_isolation = (
            $published.isolation.user_site_disabled -and
            $published.isolation.bytecode_disabled -and
            $published.isolation.hf_offline -and
            $published.isolation.transformers_offline
        )
        fault_injection = $faultInjection.acceptance_pass
    }
    $acceptancePass = @($requiredGates.Values | Where-Object { -not $_ }).Count -eq 0
    if (-not $acceptancePass) {
        throw "Technical-beta acceptance has failed required gates."
    }
    $acceptance = [ordered]@{
        schema_version = 4
        acceptance_pass = $acceptancePass
        package_id = "QwenTTSBridge-technical-beta-r3"
        provenance = $sourceProvenance
        source = $sourceProvenance
        package = [ordered]@{
            file_count = @($files).Count
            size_bytes = [long](($files | Measure-Object -Property Length -Sum).Sum)
            package_tree_manifest_sha256 = $packageTree.package_tree_manifest_sha256
            candidate_verified_manifest_digest = $candidateManifestDigest
            published_verified_manifest_digest = $publishedManifestDigest
            verified_manifest_digest_algorithm = "sha256(package-tree-manifest)"
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
            required_gates = $requiredGates
            fault_injection = $faultInjection
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
    Remove-Item -LiteralPath $faultReport -Force
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
    if (Test-Path -LiteralPath $faultReport) {
        Remove-Item -LiteralPath $faultReport -Force
    }
    throw
}

Write-Host "Technical-beta package published: $finalRoot"
Write-Host "Technical-beta acceptance evidence: $acceptancePath"
