[CmdletBinding()]
param(
    [string]$ReportPath
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Import-Module (Join-Path $PSScriptRoot "TechnicalBetaPublication.psm1") -Force
$temporaryRoot = Join-Path ([IO.Path]::GetTempPath()) "qtb-publication-test-$([Guid]::NewGuid().ToString('N'))"
$caseResults = [System.Collections.Generic.List[object]]::new()

function New-TestPackage {
    param([string]$Path, [string]$Content)

    New-Item -ItemType Directory -Force -Path $Path | Out-Null
    [IO.File]::WriteAllText((Join-Path $Path ".qtb-technical-beta-root"), "test`n")
    [IO.File]::WriteAllText((Join-Path $Path "marker.txt"), $Content)
}

function Assert-Test {
    param([bool]$Condition, [string]$Message)

    if (-not $Condition) {
        throw "Technical-beta publication test failed: $Message"
    }
}

function Get-MarkerSha256 {
    param([string]$PackagePath)

    $marker = Join-Path $PackagePath "marker.txt"
    if (-not (Test-Path -LiteralPath $marker)) {
        return $null
    }
    return (Get-FileHash -LiteralPath $marker -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Write-FaultReport {
    param([string]$Path, [object[]]$Cases)

    if (-not $Path) {
        return
    }
    $report = if ([IO.Path]::IsPathRooted($Path)) {
        [IO.Path]::GetFullPath($Path)
    }
    else {
        [IO.Path]::GetFullPath((Join-Path (Get-Location).Path $Path))
    }
    if (Test-Path -LiteralPath $report) {
        throw "ReportPath must not already exist: $report"
    }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $report) | Out-Null
    $acceptancePass = @($Cases | Where-Object { -not $_.pass }).Count -eq 0
    $value = [ordered]@{
        schema_version = 2
        acceptance_pass = $acceptancePass
        cases = @($Cases)
    }
    [IO.File]::WriteAllText(
        $report,
        (($value | ConvertTo-Json -Depth 5) + [Environment]::NewLine),
        [Text.UTF8Encoding]::new($false)
    )
}

try {
    $cases = @(
        [ordered]@{ name = "replace_success"; has_existing_package = $true; failure_point = ""; validation_failure = $false; expected_final = "new" },
        [ordered]@{ name = "replace_before_backup"; has_existing_package = $true; failure_point = "before_backup"; validation_failure = $false; expected_final = "old" },
        [ordered]@{ name = "replace_after_backup"; has_existing_package = $true; failure_point = "after_backup"; validation_failure = $false; expected_final = "old" },
        [ordered]@{ name = "replace_after_swap"; has_existing_package = $true; failure_point = "after_swap"; validation_failure = $false; expected_final = "old" },
        [ordered]@{ name = "replace_published_validation_failure"; has_existing_package = $true; failure_point = ""; validation_failure = $true; expected_final = "old" },
        [ordered]@{ name = "replace_before_backup_cleanup"; has_existing_package = $true; failure_point = "before_backup_cleanup"; validation_failure = $false; expected_final = "old" },
        [ordered]@{ name = "first_publish_after_swap"; has_existing_package = $false; failure_point = "after_swap"; validation_failure = $false; expected_final = "absent" },
        [ordered]@{ name = "first_publish_validation_failure"; has_existing_package = $false; failure_point = ""; validation_failure = $true; expected_final = "absent" }
    )

    foreach ($case in $cases) {
        $caseRoot = Join-Path $temporaryRoot $case.name
        $final = Join-Path $caseRoot "final"
        $candidate = Join-Path $caseRoot "candidate"
        if ($case.has_existing_package) {
            New-TestPackage -Path $final -Content "old"
        }
        New-TestPackage -Path $candidate -Content "new"
        $oldMarkerSha256 = Get-MarkerSha256 -PackagePath $final
        $newMarkerSha256 = Get-MarkerSha256 -PackagePath $candidate

        $threw = $false
        try {
            Move-TechnicalBetaDirectoryAtomically `
                -Candidate $candidate `
                -Final $final `
                -AllowReplacement `
                -FailurePoint $case.failure_point `
                -ValidatePublished {
                    param($published)
                    Assert-Test -Condition ((Get-Content -Raw (Join-Path $published "marker.txt")) -eq "new") `
                        -Message "published package was not candidate"
                    if ($case.validation_failure) {
                        throw "Injected technical-beta publication validation failure"
                    }
                }
        }
        catch {
            $threw = $true
        }

        $expectedFailure = $case.expected_final -ne "new"
        $finalMarkerSha256 = Get-MarkerSha256 -PackagePath $final
        $finalExists = Test-Path -LiteralPath $final
        $backupCount = @(Get-ChildItem -LiteralPath $caseRoot -Directory -Filter "final.backup-*").Count
        $oldPackageRestored = $case.has_existing_package -and $finalMarkerSha256 -eq $oldMarkerSha256
        $finalPackageAbsent = -not $finalExists
        $newPackageAbsent = $finalPackageAbsent -or $finalMarkerSha256 -ne $newMarkerSha256
        $casePass = switch ($case.expected_final) {
            "new" {
                -not $threw -and $finalMarkerSha256 -eq $newMarkerSha256 -and $backupCount -eq 0
                break
            }
            "old" {
                $threw -and $oldPackageRestored -and $newPackageAbsent -and $backupCount -eq 0
                break
            }
            "absent" {
                $threw -and $finalPackageAbsent -and $backupCount -eq 0
                break
            }
            default {
                throw "Unknown expected final state: $($case.expected_final)"
            }
        }
        $caseResults.Add([ordered]@{
            name = $case.name
            has_existing_package = [bool]$case.has_existing_package
            injected_failure_point = if ($case.failure_point) { $case.failure_point } else { $null }
            validation_failure = [bool]$case.validation_failure
            expected_failure = $expectedFailure
            threw = $threw
            old_marker_sha256 = $oldMarkerSha256
            new_marker_sha256 = $newMarkerSha256
            final_marker_sha256 = $finalMarkerSha256
            old_package_restored = $oldPackageRestored
            final_package_absent = $finalPackageAbsent
            new_package_absent = $newPackageAbsent
            candidate_exists_after = Test-Path -LiteralPath $candidate
            backup_count_after = $backupCount
            pass = $casePass
        })
        Assert-Test -Condition $casePass -Message "publication outcome did not match case: $($case.name)"
    }

    Write-FaultReport -Path $ReportPath -Cases $caseResults.ToArray()
}
finally {
    if (Test-Path -LiteralPath $temporaryRoot) {
        Remove-Item -LiteralPath $temporaryRoot -Recurse -Force
    }
}

Write-Host "Technical-beta publication fault-injection tests passed."
