[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$AcceptanceReport,
    [Parameter(Mandatory = $true)][string]$FaultReport,
    [Parameter(Mandatory = $true)][string]$Output
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$emptyDiffSha256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

function Test-CommandPassed {
    param([object]$Report, [string]$Name)

    $match = @($Report.commands | Where-Object { $_.name -eq $Name })
    return $match.Count -eq 1 -and $match[0].exit_code -eq 0
}

function Test-NaturalEos {
    param([object]$Smoke)

    $result = @(
        $Smoke.result | Where-Object {
            $null -ne $_.PSObject.Properties["terminal_state"]
        }
    )
    return $result.Count -eq 1 -and
        $result[0].terminal_state -eq "completed" -and
        $result[0].execution_outcome -eq "completed" -and
        $result[0].termination_reason -eq "eos" -and
        $result[0].hit_eos
}

function Test-RelocationEvidence {
    param([object]$Report)

    $requiredCommands = @(
        "verify_package_tree_pre_smoke",
        "verify_voice_assets_pre_smoke",
        "verify_native_closure",
        "doctor_custom_voice_pre_smoke",
        "doctor_base_pre_smoke",
        "doctor_custom_voice_post_smoke",
        "doctor_base_post_smoke",
        "verify_package_tree_post_smoke",
        "verify_voice_assets_post_smoke"
    )
    $commandsPass = @($requiredCommands | Where-Object {
        -not (Test-CommandPassed -Report $Report -Name $_)
    }).Count -eq 0
    $immutableTreePass =
        $Report.package.immutable_tree_policy.pre_smoke_manifest -eq "passed" -and
        $Report.package.immutable_tree_policy.post_smoke_manifest -eq "passed" -and
        $Report.post_smoke.bytecode_files -eq 0 -and
        $Report.post_smoke.package_tree_manifest -eq "passed" -and
        $Report.post_smoke.voice_assets_manifest -eq "passed" -and
        $Report.post_smoke.native_closure -eq "passed"
    return $commandsPass -and
        $immutableTreePass -and
        (Test-NaturalEos -Smoke $Report.smokes.custom_voice) -and
        (Test-NaturalEos -Smoke $Report.smokes.base)
}

function Test-RuntimeIsolation {
    param([object]$Report)

    return $Report.isolation.user_site_disabled -and
        $Report.isolation.bytecode_disabled -and
        $Report.isolation.hf_offline -and
        $Report.isolation.transformers_offline
}

function Get-CleanEvidenceProvenance {
    $dirty = @(& git -C $RepoRoot status --porcelain)
    if ($dirty.Count -ne 0) {
        throw "Evidence verification requires a clean source worktree."
    }
    $commit = (& git -C $RepoRoot rev-parse HEAD).Trim()
    $tree = (& git -C $RepoRoot rev-parse "HEAD^{tree}").Trim()
    if (-not $commit -or -not $tree) {
        throw "Unable to resolve evidence tooling provenance."
    }
    return [ordered]@{
        acceptance_tooling_commit = $commit
        evidence_generation_commit = $commit
        evidence_generation_tree = $tree
        evidence_generation_tree_clean = $true
    }
}

function Get-OriginalAcceptanceReportProvenance {
    param([string]$Path)

    $fullPath = if ([IO.Path]::IsPathRooted($Path)) {
        [IO.Path]::GetFullPath($Path)
    }
    else {
        [IO.Path]::GetFullPath((Join-Path (Get-Location).Path $Path))
    }
    $repoRootPath = [IO.Path]::GetFullPath($RepoRoot).TrimEnd(
        [IO.Path]::DirectorySeparatorChar,
        [IO.Path]::AltDirectorySeparatorChar
    )
    $repoPrefix = "$repoRootPath$([IO.Path]::DirectorySeparatorChar)"
    if (-not $fullPath.StartsWith($repoPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Historical acceptance report must be inside the repository: $fullPath"
    }
    $relativePath = $fullPath.Substring($repoPrefix.Length).Replace("\", "/")
    $commit = (& git -C $RepoRoot log -1 --format=%H -- $relativePath).Trim()
    if (-not $commit) {
        throw "Historical acceptance report is not tracked by Git: $relativePath"
    }
    return [ordered]@{
        original_acceptance_report_commit = $commit
        original_acceptance_report_sha256 = (Get-FileHash -LiteralPath $fullPath -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}

$outputPath = if ([IO.Path]::IsPathRooted($Output)) {
    [IO.Path]::GetFullPath($Output)
}
else {
    [IO.Path]::GetFullPath((Join-Path (Get-Location).Path $Output))
}
if (Test-Path -LiteralPath $outputPath) {
    throw "Output must not already exist: $outputPath"
}
$provenance = Get-CleanEvidenceProvenance
$historical = Get-Content -LiteralPath $AcceptanceReport -Raw | ConvertFrom-Json
$faults = Get-Content -LiteralPath $FaultReport -Raw | ConvertFrom-Json
$historicalReportProvenance = Get-OriginalAcceptanceReportProvenance -Path $AcceptanceReport

$candidate = $historical.acceptance.relocated_candidate
$published = $historical.acceptance.published_destination
$candidateDigest = $candidate.package.package_tree_manifest_sha256
$publishedDigest = $published.package.package_tree_manifest_sha256
$baseVoiceProfileIds = @(
    $candidate.smokes.base.voice_id,
    $published.smokes.base.voice_id
) | Select-Object -Unique
$faultCases = @($faults.cases)
$requiredFaultCases = @(
    "replace_success", "replace_before_backup", "replace_after_backup",
    "replace_after_swap", "replace_published_validation_failure",
    "replace_before_backup_cleanup", "first_publish_after_swap",
    "first_publish_validation_failure"
)
$faultMatrixPass = $faults.schema_version -eq 2 -and $faults.acceptance_pass -and
    $faultCases.Count -eq $requiredFaultCases.Count -and @($requiredFaultCases | Where-Object {
    $requiredCase = $_
    $match = @($faultCases | Where-Object { $_.name -eq $requiredCase })
    $match.Count -ne 1 -or -not $match[0].pass
}).Count -eq 0

$requiredGates = [ordered]@{
    historical_source_clean = [bool]$historical.source.source_tree_clean
    artifact_commit_consistency = (
        $historical.source.source_commit -eq $historical.source.package_source_commit -and
        $historical.source.source_commit -eq $historical.source.test_tree_commit -and
        $historical.source.source_diff_sha256 -eq $emptyDiffSha256
    )
    relocated_candidate_validation = Test-RelocationEvidence -Report $candidate
    published_destination_validation = Test-RelocationEvidence -Report $published
    published_runtime_isolation = Test-RuntimeIsolation -Report $published
    candidate_published_manifest_digest_match = (
        $candidateDigest -eq $publishedDigest -and
        $candidateDigest -eq $historical.package.package_tree_manifest_sha256
    )
    publication_fault_injection = $faultMatrixPass
}
$acceptancePass = @($requiredGates.Values | Where-Object { -not $_ }).Count -eq 0
if (-not $acceptancePass) {
    throw "Technical-beta evidence verification has failed required gates."
}

$report = [ordered]@{
    schema_version = 1
    acceptance_pass = $acceptancePass
    package_id = $historical.package_id
    provenance = [ordered]@{
        artifact_source_commit = $historical.source.package_source_commit
        acceptance_execution_commit = $historical.source.test_tree_commit
        original_acceptance_report_commit = $historicalReportProvenance.original_acceptance_report_commit
        original_acceptance_report_sha256 = $historicalReportProvenance.original_acceptance_report_sha256
        evidence_augmentation = $provenance
    }
    package = [ordered]@{
        candidate_verified_manifest_digest = $candidateDigest
        published_verified_manifest_digest = $publishedDigest
        verified_manifest_digest_algorithm = "sha256(package-tree-manifest)"
        voice_assets_manifest_sha256 = $historical.package.voice_assets_manifest_sha256
        worker_build_manifest_sha256 = $historical.package.worker_build_manifest_sha256
    }
    voice_profile_smoke_scope = [ordered]@{
        custom_voice_smoked = $true
        base_voice_profile_ids = @($baseVoiceProfileIds)
        coverage = "one selected Base profile per destination"
    }
    required_gates = $requiredGates
    fault_injection = [ordered]@{
        schema_version = $faults.schema_version
        acceptance_pass = $faults.acceptance_pass
        cases = $faultCases
    }
}

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $outputPath) | Out-Null
[IO.File]::WriteAllText(
    $outputPath,
    (($report | ConvertTo-Json -Depth 8) + [Environment]::NewLine),
    [Text.UTF8Encoding]::new($false)
)
Write-Host "Technical-beta evidence verification passed."
