param(
    [string]$Python = "py",
    [string[]]$PythonArgs,
    [switch]$UseVenv,
    [string]$VenvPath = ".venv-packaging",
    [string]$OutputRoot = "dist/QwenTTSBridge",
    [string]$WorkerDirectoryName = "worker-python",
    [switch]$Clean,
    [switch]$DryRun,
    [switch]$IncludeQwenFork,
    [string]$QwenSourcePath = "external/python/Qwen3-TTS-streaming"
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot
$RequiredPythonVersion = "3.11"

if (-not $PSBoundParameters.ContainsKey("PythonArgs")) {
    if ($Python -eq "py") {
        $PythonArgs = @("-3.11")
    }
    else {
        $PythonArgs = @()
    }
}

function Resolve-RepoPath {
    param(
        [string]$Path
    )

    if ([IO.Path]::IsPathRooted($Path)) {
        return [IO.Path]::GetFullPath($Path)
    }

    return [IO.Path]::GetFullPath((Join-Path $RepoRoot $Path))
}

function Assert-UnderRepo {
    param(
        [string]$Path
    )

    $ResolvedRepoRoot = [IO.Path]::GetFullPath($RepoRoot)
    $ResolvedPath = [IO.Path]::GetFullPath($Path)
    $RepoPrefix = $ResolvedRepoRoot.TrimEnd(
        [IO.Path]::DirectorySeparatorChar,
        [IO.Path]::AltDirectorySeparatorChar
    ) + [IO.Path]::DirectorySeparatorChar
    if (
        $ResolvedPath -ne $ResolvedRepoRoot -and
        -not $ResolvedPath.StartsWith(
            $RepoPrefix,
            [StringComparison]::OrdinalIgnoreCase
        )
    ) {
        throw "Path must be inside the repository: $ResolvedPath"
    }
}

function Assert-StrictChildPath {
    param(
        [string]$Parent,
        [string]$Path,
        [string]$Description
    )

    $ResolvedParent = [IO.Path]::GetFullPath($Parent).TrimEnd(
        [IO.Path]::DirectorySeparatorChar,
        [IO.Path]::AltDirectorySeparatorChar
    )
    $ResolvedPath = [IO.Path]::GetFullPath($Path).TrimEnd(
        [IO.Path]::DirectorySeparatorChar,
        [IO.Path]::AltDirectorySeparatorChar
    )
    $ParentPrefix = $ResolvedParent + [IO.Path]::DirectorySeparatorChar
    if (
        $ResolvedPath -eq $ResolvedParent -or
        -not $ResolvedPath.StartsWith(
            $ParentPrefix,
            [StringComparison]::OrdinalIgnoreCase
        )
    ) {
        throw "$Description must be a strict child of: $ResolvedParent"
    }
}

function Assert-RelativeDirectoryName {
    param(
        [string]$Name
    )

    if ([string]::IsNullOrWhiteSpace($Name)) {
        throw "WorkerDirectoryName must not be empty."
    }
    if ([IO.Path]::IsPathRooted($Name)) {
        throw "WorkerDirectoryName must be a relative directory name, not an absolute path."
    }
    if ($Name -eq "." -or $Name -eq "..") {
        throw "WorkerDirectoryName must not be '.' or '..'."
    }
    if (
        $Name.Contains([string][IO.Path]::DirectorySeparatorChar) -or
        $Name.Contains([string][IO.Path]::AltDirectorySeparatorChar)
    ) {
        throw "WorkerDirectoryName must be a single directory name without path separators."
    }
    if ($Name.IndexOfAny([IO.Path]::GetInvalidFileNameChars()) -ge 0) {
        throw "WorkerDirectoryName contains invalid path characters: $Name"
    }
}

function Resolve-VenvPython {
    param(
        [string]$Path
    )

    $ResolvedVenvPath = Resolve-RepoPath $Path
    return Join-Path $ResolvedVenvPath "Scripts/python.exe"
}

function Invoke-ProjectPython {
    param(
        [string[]]$Arguments
    )

    & $Python @PythonArgs @Arguments
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

function Invoke-PythonText {
    param(
        [string[]]$Arguments
    )

    $Output = & $Python @PythonArgs @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed: $Python $($PythonArgs -join ' ') $($Arguments -join ' ')"
    }
    return ($Output -join "`n").Trim()
}

function Assert-PackagingPythonVersion {
    $Version = Invoke-PythonText @(
        "-c",
        "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
    )
    if ($Version -ne $RequiredPythonVersion) {
        throw "Portable worker packaging Python must be $RequiredPythonVersion; selected Python is $Version. Recreate $VenvPath with Python $RequiredPythonVersion or pass -Python/-PythonArgs explicitly."
    }
}

function Get-PythonEnvironmentInfo {
    $EnvironmentJson = Invoke-PythonText @(
        "-c",
        "import json, sys, sysconfig; print(json.dumps({'base_prefix': sys.base_prefix, 'executable': sys.executable, 'purelib': sysconfig.get_paths()['purelib'], 'platlib': sysconfig.get_paths()['platlib']}))"
    )
    return $EnvironmentJson | ConvertFrom-Json
}

function Copy-DirectoryContents {
    param(
        [string]$Source,
        [string]$Destination
    )

    if (-not (Test-Path -LiteralPath $Source)) {
        throw "Source directory was not found: $Source"
    }

    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    Copy-Item -Path (Join-Path $Source "*") -Destination $Destination -Recurse -Force
}

function Remove-EditableInstallArtifacts {
    param(
        [string]$SitePackages
    )

    Get-ChildItem -LiteralPath $SitePackages -Filter "__editable__*" -Force |
        Remove-Item -Force
}

function Write-WorkerLauncher {
    param(
        [string]$LauncherPath
    )

    $LauncherContent = @'
@echo off
setlocal
set "WORKER_ROOT=%~dp0"
set "PYTHONHOME=%WORKER_ROOT%python"
set "PYTHONPATH=%WORKER_ROOT%python\Lib\site-packages"
set "PYTHONNOUSERSITE=1"
"%WORKER_ROOT%python\python.exe" -P -s -m qwen_tts_bridge_worker %*
'@
    [IO.File]::WriteAllText(
        $LauncherPath,
        $LauncherContent.Replace("`n", "`r`n"),
        [System.Text.UTF8Encoding]::new($false)
    )
}

if ($UseVenv) {
    $VenvPython = Resolve-VenvPython $VenvPath
    if (-not (Test-Path -LiteralPath $VenvPython)) {
        $Message = "Python virtual environment was not found at $VenvPath. " +
            "Run scripts/setup-python-packaging.ps1 -UseVenv first."
        throw $Message
    }

    $Python = $VenvPython
    $PythonArgs = @()
}

Assert-PackagingPythonVersion
$PythonEnvironment = Get-PythonEnvironmentInfo

Assert-RelativeDirectoryName $WorkerDirectoryName

$PackageRoot = Resolve-RepoPath $OutputRoot
$WorkerOutput = Join-Path $PackageRoot $WorkerDirectoryName
$PythonOutput = Join-Path $WorkerOutput "python"
$SitePackagesOutput = Join-Path $PythonOutput "Lib/site-packages"
$WorkerPackageSource = Resolve-RepoPath "worker/src/qwen_tts_bridge_worker"
$LauncherPath = Join-Path $WorkerOutput "qwen_tts_worker.cmd"

Assert-UnderRepo $PackageRoot
Assert-UnderRepo $WorkerOutput
Assert-UnderRepo $WorkerPackageSource
Assert-StrictChildPath -Parent $RepoRoot -Path $WorkerOutput -Description "WorkerOutput"
Assert-StrictChildPath -Parent $PackageRoot -Path $WorkerOutput -Description "WorkerOutput"

$BasePrefix = [IO.Path]::GetFullPath([string]$PythonEnvironment.base_prefix)
$PureLib = [IO.Path]::GetFullPath([string]$PythonEnvironment.purelib)
$PlatLib = [IO.Path]::GetFullPath([string]$PythonEnvironment.platlib)

if (-not (Test-Path -LiteralPath (Join-Path $BasePrefix "python.exe"))) {
    throw "Python base runtime does not contain python.exe: $BasePrefix"
}
if (-not (Test-Path -LiteralPath $PureLib)) {
    throw "Python purelib site-packages path was not found: $PureLib"
}
if (-not (Test-Path -LiteralPath $PlatLib)) {
    throw "Python platlib site-packages path was not found: $PlatLib"
}

$QwenPackageSource = $null
if ($IncludeQwenFork) {
    $ResolvedQwenSourcePath = Resolve-RepoPath $QwenSourcePath
    $QwenPackageSource = Join-Path $ResolvedQwenSourcePath "qwen_tts"
    if (-not (Test-Path -LiteralPath $QwenPackageSource)) {
        throw "Qwen package source was not found: $QwenPackageSource"
    }
}

Write-Host "Portable Python worker source runtime: $BasePrefix"
Write-Host "Portable Python worker source site-packages: $PureLib"
Write-Host "Portable Python worker output: $WorkerOutput"
Write-Host "Portable Python worker launcher: $LauncherPath"
if ($IncludeQwenFork) {
    Write-Host "Portable Python worker includes Qwen fork: $QwenPackageSource"
}

if ($DryRun) {
    return
}

if ($Clean -and (Test-Path -LiteralPath $WorkerOutput)) {
    Assert-UnderRepo $WorkerOutput
    Remove-Item -LiteralPath $WorkerOutput -Recurse -Force
}

New-Item -ItemType Directory -Force -Path $WorkerOutput | Out-Null
if (Test-Path -LiteralPath $PythonOutput) {
    Assert-UnderRepo $PythonOutput
    Remove-Item -LiteralPath $PythonOutput -Recurse -Force
}

Copy-DirectoryContents -Source $BasePrefix -Destination $PythonOutput

if (Test-Path -LiteralPath $SitePackagesOutput) {
    Remove-Item -LiteralPath $SitePackagesOutput -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $SitePackagesOutput | Out-Null
Copy-DirectoryContents -Source $PureLib -Destination $SitePackagesOutput
if ($PlatLib -ne $PureLib) {
    Copy-DirectoryContents -Source $PlatLib -Destination $SitePackagesOutput
}

Remove-EditableInstallArtifacts -SitePackages $SitePackagesOutput

$WorkerPackageDestination = Join-Path $SitePackagesOutput "qwen_tts_bridge_worker"
if (Test-Path -LiteralPath $WorkerPackageDestination) {
    Remove-Item -LiteralPath $WorkerPackageDestination -Recurse -Force
}
Copy-Item -LiteralPath $WorkerPackageSource -Destination $WorkerPackageDestination -Recurse

if ($null -ne $QwenPackageSource) {
    $QwenPackageDestination = Join-Path $SitePackagesOutput "qwen_tts"
    if (Test-Path -LiteralPath $QwenPackageDestination) {
        Remove-Item -LiteralPath $QwenPackageDestination -Recurse -Force
    }
    Copy-Item -LiteralPath $QwenPackageSource -Destination $QwenPackageDestination -Recurse
}

Write-WorkerLauncher -LauncherPath $LauncherPath
New-Item -ItemType Directory -Force -Path (Join-Path $PackageRoot "config") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $PackageRoot "models") | Out-Null

if (-not (Test-Path -LiteralPath $LauncherPath)) {
    throw "Portable Python worker launcher was not found: $LauncherPath"
}

Write-Host "Portable Python worker launcher: $LauncherPath"
