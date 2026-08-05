Set-StrictMode -Version Latest

$script:TechnicalBetaMarkerName = ".qtb-technical-beta-root"

function Assert-TechnicalBetaPackageRoot {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath (Join-Path $Path $script:TechnicalBetaMarkerName))) {
        throw "Refusing to replace output without technical-beta marker: $Path"
    }
}

function Invoke-TechnicalBetaFailurePoint {
    param([string]$FailurePoint, [string]$CurrentPoint)

    if ($FailurePoint -eq $CurrentPoint) {
        throw "Injected technical-beta publication failure at: $CurrentPoint"
    }
}

function Move-TechnicalBetaDirectoryAtomically {
    param(
        [Parameter(Mandatory = $true)][string]$Candidate,
        [Parameter(Mandatory = $true)][string]$Final,
        [Parameter(Mandatory = $true)][scriptblock]$ValidatePublished,
        [switch]$AllowReplacement,
        [ValidateSet("", "after_backup", "after_swap", "before_backup_cleanup")]
        [string]$FailurePoint = ""
    )

    $candidatePath = [IO.Path]::GetFullPath($Candidate)
    $finalPath = [IO.Path]::GetFullPath($Final)
    if ([IO.Path]::GetPathRoot($candidatePath) -ne [IO.Path]::GetPathRoot($finalPath)) {
        throw "Candidate and final package paths must use the same volume."
    }
    if (-not (Test-Path -LiteralPath $candidatePath)) {
        throw "Candidate package does not exist: $candidatePath"
    }
    Assert-TechnicalBetaPackageRoot -Path $candidatePath

    $backupPath = $null
    $published = $false
    if (Test-Path -LiteralPath $finalPath) {
        Assert-TechnicalBetaPackageRoot -Path $finalPath
        if (-not $AllowReplacement) {
            throw "Output already exists; pass -ReplaceExisting to publish a validated replacement: $finalPath"
        }
        $backupPath = "$finalPath.backup-$([Guid]::NewGuid().ToString('N'))"
        Move-Item -LiteralPath $finalPath -Destination $backupPath
        try {
            Invoke-TechnicalBetaFailurePoint -FailurePoint $FailurePoint -CurrentPoint "after_backup"
            Move-Item -LiteralPath $candidatePath -Destination $finalPath
            $published = $true
            Invoke-TechnicalBetaFailurePoint -FailurePoint $FailurePoint -CurrentPoint "after_swap"
            & $ValidatePublished $finalPath
            Invoke-TechnicalBetaFailurePoint -FailurePoint $FailurePoint -CurrentPoint "before_backup_cleanup"
            Remove-Item -LiteralPath $backupPath -Recurse -Force
            $backupPath = $null
            return
        }
        catch {
            $publicationError = $_
            if ($published -and (Test-Path -LiteralPath $finalPath)) {
                Remove-Item -LiteralPath $finalPath -Recurse -Force
            }
            if ($null -ne $backupPath -and (Test-Path -LiteralPath $backupPath)) {
                Move-Item -LiteralPath $backupPath -Destination $finalPath
                $backupPath = $null
            }
            throw $publicationError
        }
    }

    try {
        Move-Item -LiteralPath $candidatePath -Destination $finalPath
        $published = $true
        Invoke-TechnicalBetaFailurePoint -FailurePoint $FailurePoint -CurrentPoint "after_swap"
        & $ValidatePublished $finalPath
    }
    catch {
        $publicationError = $_
        if ($published -and (Test-Path -LiteralPath $finalPath)) {
            Remove-Item -LiteralPath $finalPath -Recurse -Force
        }
        throw $publicationError
    }
}

Export-ModuleMember -Function Assert-TechnicalBetaPackageRoot, Move-TechnicalBetaDirectoryAtomically
