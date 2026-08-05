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
        schema_version = 1
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
        [ordered]@{ name = "success"; failure_point = ""; validation_failure = $false },
        [ordered]@{ name = "before_backup"; failure_point = "before_backup"; validation_failure = $false },
        [ordered]@{ name = "after_backup"; failure_point = "after_backup"; validation_failure = $false },
        [ordered]@{ name = "after_swap"; failure_point = "after_swap"; validation_failure = $false },
        [ordered]@{ name = "post_publish_validation"; failure_point = ""; validation_failure = $true },
        [ordered]@{ name = "before_backup_cleanup"; failure_point = "before_backup_cleanup"; validation_failure = $false }
    )

    foreach ($case in $cases) {
        $caseRoot = Join-Path $temporaryRoot $case.name
        $final = Join-Path $caseRoot "final"
        $candidate = Join-Path $caseRoot "candidate"
        New-TestPackage -Path $final -Content "old"
        New-TestPackage -Path $candidate -Content "new"

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

        $expectedFailure = $case.name -ne "success"
        $finalMarker = [string](Get-Content -LiteralPath (Join-Path $final "marker.txt") -Raw)
        $backupCount = @(Get-ChildItem -LiteralPath $caseRoot -Directory -Filter "final.backup-*").Count
        $casePass = if ($expectedFailure) {
            $threw -and $finalMarker -eq "old" -and $backupCount -eq 0
        }
        else {
            -not $threw -and $finalMarker -eq "new" -and $backupCount -eq 0
        }
        $caseResults.Add([ordered]@{
            name = $case.name
            injected_failure_point = if ($case.failure_point) { $case.failure_point } else { $null }
            validation_failure = [bool]$case.validation_failure
            expected_failure = $expectedFailure
            threw = $threw
            final_marker = $finalMarker
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
