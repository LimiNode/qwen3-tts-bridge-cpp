[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Import-Module (Join-Path $PSScriptRoot "TechnicalBetaPublication.psm1") -Force
$temporaryRoot = Join-Path ([IO.Path]::GetTempPath()) "qtb-publication-test-$([Guid]::NewGuid().ToString('N'))"

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

try {
    foreach ($failurePoint in @("", "after_backup", "after_swap", "before_backup_cleanup")) {
        $caseName = if ($failurePoint) { $failurePoint } else { "success" }
        $caseRoot = Join-Path $temporaryRoot $caseName
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
                -FailurePoint $failurePoint `
                -ValidatePublished {
                    param($published)
                    Assert-Test -Condition ((Get-Content -Raw (Join-Path $published "marker.txt")) -eq "new") `
                        -Message "published package was not candidate"
                }
        }
        catch {
            $threw = $true
        }

        if ($failurePoint) {
            Assert-Test -Condition $threw -Message "injected failure did not fail: $failurePoint"
            Assert-Test -Condition ((Get-Content -Raw (Join-Path $final "marker.txt")) -eq "old") `
                -Message "rollback did not restore previous package: $failurePoint"
        }
        else {
            Assert-Test -Condition (-not $threw) -Message "success publication unexpectedly failed"
            Assert-Test -Condition ((Get-Content -Raw (Join-Path $final "marker.txt")) -eq "new") `
                -Message "success publication did not install candidate"
        }
        Assert-Test -Condition (@(Get-ChildItem -LiteralPath $caseRoot -Directory -Filter "final.backup-*").Count -eq 0) `
            -Message "backup was left after $failurePoint"
    }
}
finally {
    if (Test-Path -LiteralPath $temporaryRoot) {
        Remove-Item -LiteralPath $temporaryRoot -Recurse -Force
    }
}

Write-Host "Technical-beta publication fault-injection tests passed."
