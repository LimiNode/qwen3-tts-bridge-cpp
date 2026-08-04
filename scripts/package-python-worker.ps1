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
    [string]$QwenSourcePath = "external/python/Qwen3-TTS-streaming",
    [switch]$IncludeFasterQwen,
    [string]$FasterQwenSourcePath = "external/python/faster-qwen3-tts",
    [switch]$AllowDirtySources,
    [switch]$AllowUnversionedSources
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot
$RequiredPythonVersion = "3.11"
$WorkerMarkerFileName = ".qtb-portable-worker-root"

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

function Test-IsUnderPath {
    param(
        [string]$Parent,
        [string]$Path,
        [bool]$AllowEqual = $true
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

    return (
        ($AllowEqual -and $ResolvedPath -eq $ResolvedParent) -or
        $ResolvedPath.StartsWith($ParentPrefix, [StringComparison]::OrdinalIgnoreCase)
    )
}

function Assert-PortableWorkerMarker {
    param(
        [string]$Path
    )

    $MarkerPath = Join-Path $Path $WorkerMarkerFileName
    if (-not (Test-Path -LiteralPath $MarkerPath)) {
        $Message = "Refusing to modify existing portable worker output without marker: $Path. " +
            "Delete it manually if it is safe, or choose a different OutputRoot/WorkerDirectoryName."
        throw $Message
    }
}

function Assert-NotUnderPath {
    param(
        [string]$Parent,
        [string]$Path,
        [string]$Description
    )

    if (Test-IsUnderPath -Parent $Parent -Path $Path -AllowEqual $true) {
        throw "$Description must not be inside source tree: $Parent"
    }
}

function Write-PortableWorkerMarker {
    param(
        [string]$Path
    )

    $MarkerPath = Join-Path $Path $WorkerMarkerFileName
    [IO.File]::WriteAllText(
        $MarkerPath,
        "QwenTTSBridge portable worker output.`r`n",
        [System.Text.UTF8Encoding]::new($false)
    )
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
        "import json, platform, sys, sysconfig; print(json.dumps({'base_prefix': sys.base_prefix, 'executable': sys.executable, 'implementation': platform.python_implementation(), 'version': sys.version, 'version_info': list(sys.version_info[:3]), 'purelib': sysconfig.get_paths()['purelib'], 'platlib': sysconfig.get_paths()['platlib']}))"
    )
    return $EnvironmentJson | ConvertFrom-Json
}

function Get-PythonPackageVersion {
    param(
        [string]$PackageName
    )

    $Code = "import importlib.metadata as m; " +
        "name = '$PackageName'; " +
        "print(m.version(name) if name in {dist.metadata['Name'] for dist in m.distributions()} else '')"
    return Invoke-PythonText @("-c", $Code)
}

function Get-PythonToolVersions {
    return [ordered]@{
        pip = Get-PythonPackageVersion "pip"
        setuptools = Get-PythonPackageVersion "setuptools"
        wheel = Get-PythonPackageVersion "wheel"
        torch = Get-PythonPackageVersion "torch"
        transformers = Get-PythonPackageVersion "transformers"
        torch_cuda = Get-TorchCudaVersion
        torch_cuda_available = Get-TorchCudaAvailable
    }
}

function Get-TorchCudaVersion {
    $Code = "try:`n import torch; print(torch.version.cuda or '')`nexcept Exception:`n print('')"
    return Invoke-PythonText @("-c", $Code)
}

function Get-TorchCudaAvailable {
    $Code = "try:`n import torch; print('true' if torch.cuda.is_available() else 'false')`nexcept Exception:`n print('')"
    return Invoke-PythonText @("-c", $Code)
}

function Get-PipFreeze {
    param(
        [string]$Path
    )

    $Arguments = @(
        "-m",
        "pip",
        "--disable-pip-version-check",
        "freeze"
    )
    if (-not [string]::IsNullOrWhiteSpace($Path)) {
        $Arguments += @("--path", $Path)
    }
    $Output = & $Python @PythonArgs @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "pip freeze failed."
    }
    return @($Output)
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

function Get-ProjectRequirement {
    param(
        [string]$ProjectPath
    )

    $PyProjectPath = Join-Path $ProjectPath "pyproject.toml"
    if (-not (Test-Path -LiteralPath $PyProjectPath)) {
        throw "pyproject.toml was not found: $PyProjectPath"
    }

    $PyProject = Get-Content -Raw -LiteralPath $PyProjectPath
    $NameMatch = [regex]::Match($PyProject, '(?m)^name\s*=\s*"([^"]+)"')
    $VersionMatch = [regex]::Match($PyProject, '(?m)^version\s*=\s*"([^"]+)"')
    if (-not $NameMatch.Success -or -not $VersionMatch.Success) {
        throw "Unable to read project name/version from: $PyProjectPath"
    }

    return "$($NameMatch.Groups[1].Value)==$($VersionMatch.Groups[1].Value)"
}

function Remove-StagedPackageArtifacts {
    param(
        [string]$SitePackages,
        [string[]]$PackageNames
    )

    foreach ($PackageName in $PackageNames) {
        Get-ChildItem -LiteralPath $SitePackages -Force |
            Where-Object {
                $_.Name -eq $PackageName -or
                $_.Name -like "$PackageName-*.dist-info" -or
                $_.Name -like "$PackageName-*.egg-info" -or
                $_.Name -like "$PackageName-*.data"
            } |
            Remove-Item -Recurse -Force
    }
}

function Remove-PythonBytecode {
    param(
        [string]$Root
    )

    Get-ChildItem -LiteralPath $Root -Recurse -Directory -Filter "__pycache__" -Force |
        Sort-Object -Property FullName -Descending |
        Remove-Item -Recurse -Force

    Get-ChildItem -LiteralPath $Root -Recurse -File -Filter "*.pyc" -Force |
        Remove-Item -Force
    Get-ChildItem -LiteralPath $Root -Recurse -File -Filter "*.pyo" -Force |
        Remove-Item -Force
}

function Remove-StagedScriptDirectory {
    param(
        [string]$SitePackages
    )

    $ScriptDirectory = Join-Path $SitePackages "bin"
    if (Test-Path -LiteralPath $ScriptDirectory) {
        Remove-Item -LiteralPath $ScriptDirectory -Recurse -Force
    }
}

function Install-ProjectWheelToTarget {
    param(
        [string]$ProjectPath,
        [string]$SitePackages,
        [string]$WheelWorkRoot,
        [string]$WheelArtifactRoot,
        [string]$Label
    )

    $Requirement = Get-ProjectRequirement $ProjectPath
    $WheelDir = Join-Path $WheelWorkRoot $Label
    if (Test-Path -LiteralPath $WheelDir) {
        Remove-Item -LiteralPath $WheelDir -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $WheelDir | Out-Null
    $SourceCopy = Join-Path $WheelDir "source"
    Copy-DirectoryContents -Source $ProjectPath -Destination $SourceCopy
    foreach ($GeneratedName in @(".git", "build", "dist")) {
        $GeneratedPath = Join-Path $SourceCopy $GeneratedName
        if (Test-Path -LiteralPath $GeneratedPath) {
            Remove-Item -LiteralPath $GeneratedPath -Recurse -Force
        }
    }
    Get-ChildItem -LiteralPath $SourceCopy -Directory -Filter "*.egg-info" -Force |
        Remove-Item -Recurse -Force
    Remove-PythonBytecode -Root $SourceCopy

    Invoke-ProjectPython @(
        "-m",
        "pip",
        "wheel",
        "--disable-pip-version-check",
        "--no-build-isolation",
        "--no-deps",
        "--wheel-dir",
        $WheelDir,
        $SourceCopy
    ) | Out-Host

    $Wheels = @(Get-ChildItem -LiteralPath $WheelDir -Filter "*.whl" -File)
    if ($Wheels.Count -ne 1) {
        throw "Expected one wheel for $Label under $WheelDir; found $($Wheels.Count)."
    }
    $Wheel = $Wheels[0]
    New-Item -ItemType Directory -Force -Path $WheelArtifactRoot | Out-Null
    $ArtifactPath = Join-Path $WheelArtifactRoot $Wheel.Name
    Copy-Item -LiteralPath $Wheel.FullName -Destination $ArtifactPath -Force

    Remove-StagedScriptDirectory -SitePackages $SitePackages
    Invoke-ProjectPython @(
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--no-warn-script-location",
        "--no-index",
        "--find-links",
        $WheelDir,
        "--no-deps",
        "--target",
        $SitePackages,
        $Requirement
    ) | Out-Host
    Remove-StagedScriptDirectory -SitePackages $SitePackages

    return [pscustomobject]@{
        label = $Label
        requirement = $Requirement
        wheel = $Wheel.Name
        wheel_sha256 = Get-FileSha256 $Wheel.FullName
        wheel_artifact = "wheels/$($Wheel.Name)"
        source = Get-SourceManifest $ProjectPath
    }
}

function Get-FileSha256 {
    param(
        [string]$Path
    )

    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Get-SourceManifest {
    param(
        [string]$ProjectPath
    )

    $ResolvedProjectPath = [IO.Path]::GetFullPath($ProjectPath)
    $PortablePath = Get-PortableSourcePath $ResolvedProjectPath
    $Commit = $null
    $Dirty = $null
    $TrackedChanges = $null

    $InsideWorkTree = & git -C $ResolvedProjectPath rev-parse --is-inside-work-tree 2>$null
    if ($LASTEXITCODE -eq 0 -and (($InsideWorkTree | Select-Object -First 1) -eq "true")) {
        $CommitOutput = & git -C $ResolvedProjectPath rev-parse HEAD 2>$null
        if ($LASTEXITCODE -eq 0) {
            $Commit = ($CommitOutput | Select-Object -First 1).Trim()
        }

        $StatusOutput = & git -C $ResolvedProjectPath status --porcelain 2>$null
        if ($LASTEXITCODE -eq 0) {
            $TrackedChanges = @($StatusOutput)
            $Dirty = $TrackedChanges.Count -gt 0
        }
    }

    return [pscustomobject]@{
        path = $PortablePath.path
        path_kind = $PortablePath.kind
        git_commit = $Commit
        git_dirty = $Dirty
        git_status = $TrackedChanges
    }
}

function Get-PortableSourcePath {
    param(
        [string]$Path
    )

    $ResolvedRepoRoot = [IO.Path]::GetFullPath($RepoRoot).TrimEnd(
        [IO.Path]::DirectorySeparatorChar,
        [IO.Path]::AltDirectorySeparatorChar
    )
    $ResolvedPath = [IO.Path]::GetFullPath($Path)
    $RepoPrefix = $ResolvedRepoRoot + [IO.Path]::DirectorySeparatorChar
    if ($ResolvedPath.StartsWith($RepoPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        $Relative = $ResolvedPath.Substring($RepoPrefix.Length).Replace("\", "/")
        return [pscustomobject]@{
            kind = "repo_relative"
            path = $Relative
        }
    }

    return [pscustomobject]@{
        kind = "external_name"
        path = Split-Path -Leaf $ResolvedPath
    }
}

function Assert-CleanSources {
    param(
        [object[]]$Wheels
    )

    if ($AllowDirtySources) {
        return
    }

    $DirtyLabels = @(
        $Wheels |
            Where-Object { $null -ne $_.source.git_dirty -and $_.source.git_dirty } |
            ForEach-Object { $_.label }
    )
    if ($DirtyLabels.Count -gt 0) {
        throw "Refusing to package dirty source trees: $($DirtyLabels -join ', '). Pass -AllowDirtySources for a local diagnostic build."
    }

    if ($AllowUnversionedSources) {
        return
    }

    $UnversionedLabels = @(
        $Wheels |
            Where-Object { $null -eq $_.source.git_commit } |
            ForEach-Object { $_.label }
    )
    if ($UnversionedLabels.Count -gt 0) {
        throw "Refusing to package unversioned source trees: $($UnversionedLabels -join ', '). Pass -AllowUnversionedSources for a local diagnostic build."
    }
}

function Write-BuildManifest {
    param(
        [string]$Path,
        [object[]]$Wheels,
        [object]$PythonEnvironment,
        [object]$ToolVersions,
        [string[]]$PipFreeze,
        [string]$PortableRuntimeTreeManifest
    )

    $Manifest = [ordered]@{
        generated_at_utc = [DateTime]::UtcNow.ToString("o")
        python = [ordered]@{
            base_prefix = Get-PortableSourcePath ([string]$PythonEnvironment.base_prefix)
            implementation = [string]$PythonEnvironment.implementation
            version = [string]$PythonEnvironment.version
            version_info = $PythonEnvironment.version_info
            purelib = Get-PortableSourcePath ([string]$PythonEnvironment.purelib)
            platlib = Get-PortableSourcePath ([string]$PythonEnvironment.platlib)
        }
        python_tools = $ToolVersions
        pip_freeze = $PipFreeze
        wheels = $Wheels
        portable_runtime_tree_manifest = [ordered]@{
            path = Split-Path -Leaf $PortableRuntimeTreeManifest
            sha256 = Get-FileSha256 $PortableRuntimeTreeManifest
        }
    }
    $Json = $Manifest | ConvertTo-Json -Depth 8
    [IO.File]::WriteAllText(
        $Path,
        $Json,
        [System.Text.UTF8Encoding]::new($false)
    )
}

function Remove-EditableInstallArtifacts {
    param(
        [string]$SitePackages
    )

    Get-ChildItem -LiteralPath $SitePackages -Filter "__editable__*" -Force |
        Remove-Item -Force
    Get-ChildItem -LiteralPath $SitePackages -Filter "*.egg-link" -Force |
        Remove-Item -Force
    $DistutilsPrecedence = Join-Path $SitePackages "distutils-precedence.pth"
    if (Test-Path -LiteralPath $DistutilsPrecedence) {
        Remove-Item -LiteralPath $DistutilsPrecedence -Force
    }
    $EasyInstall = Join-Path $SitePackages "easy-install.pth"
    if (Test-Path -LiteralPath $EasyInstall) {
        Remove-Item -LiteralPath $EasyInstall -Force
    }
}

function Assert-PortableSitePaths {
    param(
        [string]$SitePackages
    )

    foreach ($PathFile in Get-ChildItem -LiteralPath $SitePackages -Filter "*.pth" -Force) {
        $Lines = Get-Content -LiteralPath $PathFile.FullName -ErrorAction Stop
        foreach ($Line in $Lines) {
            $Trimmed = $Line.Trim()
            if ([string]::IsNullOrWhiteSpace($Trimmed) -or $Trimmed.StartsWith("#")) {
                continue
            }
            if ($Trimmed -match '^import(\s|\t)') {
                throw "Portable worker site-packages must not contain executable .pth entries: $($PathFile.FullName)"
            }

            $CandidatePath = $Trimmed
            if (-not [IO.Path]::IsPathRooted($CandidatePath)) {
                $CandidatePath = Join-Path $SitePackages $CandidatePath
            }
            $ResolvedCandidate = [IO.Path]::GetFullPath($CandidatePath)
            if (-not (Test-IsUnderPath -Parent $SitePackages -Path $ResolvedCandidate -AllowEqual $false)) {
                throw "Portable worker .pth entry points outside staged site-packages: $($PathFile.FullName) -> $Trimmed"
            }
        }
    }
}

function Invoke-StagedPythonIsolationProbe {
    param(
        [string]$PythonRoot,
        [string]$SitePackages,
        [string[]]$ForbiddenRoots,
        [switch]$ProbeQwenImport,
        [switch]$ProbeFasterQwenImport
    )

    $StagedPython = Join-Path $PythonRoot "python.exe"
    if (-not (Test-Path -LiteralPath $StagedPython)) {
        throw "Staged Python executable was not found: $StagedPython"
    }

    $PreviousPythonHome = $env:PYTHONHOME
    $PreviousPythonPath = $env:PYTHONPATH
    $PreviousPythonNoUserSite = $env:PYTHONNOUSERSITE
    $PreviousPythonDontWriteBytecode = $env:PYTHONDONTWRITEBYTECODE
    $PreviousForbiddenRoots = $env:QTB_FORBIDDEN_SYS_PATH_ROOTS
    $PreviousProbeQwenImport = $env:QTB_PROBE_QWEN_IMPORT
    $PreviousProbeFasterQwenImport = $env:QTB_PROBE_FASTER_QWEN_IMPORT
    $ProbePath = Join-Path $PythonRoot "qtb_portable_isolation_probe.py"

    try {
        $env:PYTHONHOME = $PythonRoot
        $env:PYTHONPATH = $SitePackages
        $env:PYTHONNOUSERSITE = "1"
        $env:PYTHONDONTWRITEBYTECODE = "1"
        $env:QTB_FORBIDDEN_SYS_PATH_ROOTS = (
            $ForbiddenRoots |
                Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
                ForEach-Object { [IO.Path]::GetFullPath($_) } |
                Sort-Object -Unique
        ) -join [IO.Path]::PathSeparator
        if ($ProbeQwenImport) {
            $env:QTB_PROBE_QWEN_IMPORT = "1"
        }
        else {
            $env:QTB_PROBE_QWEN_IMPORT = ""
        }
        if ($ProbeFasterQwenImport) {
            $env:QTB_PROBE_FASTER_QWEN_IMPORT = "1"
        }
        else {
            $env:QTB_PROBE_FASTER_QWEN_IMPORT = ""
        }

        $ProbeCode = @'
import os
import pathlib
import sys

forbidden_roots = [
    pathlib.Path(path).resolve()
    for path in os.environ.get("QTB_FORBIDDEN_SYS_PATH_ROOTS", "").split(os.pathsep)
    if path
]
leaks = []
for entry in sys.path:
    if not entry:
        continue
    resolved = pathlib.Path(entry).resolve()
    for root in forbidden_roots:
        try:
            resolved.relative_to(root)
        except ValueError:
            continue
        leaks.append(str(resolved))
        break

if leaks:
    raise SystemExit("portable worker sys.path leaks source paths: " + "; ".join(leaks))

import qwen_tts_bridge_worker  # noqa: F401

if os.environ.get("QTB_PROBE_QWEN_IMPORT") == "1":
    import qwen_tts.inference.qwen3_tts_model  # noqa: F401

if os.environ.get("QTB_PROBE_FASTER_QWEN_IMPORT") == "1":
    import faster_qwen3_tts  # noqa: F401
'@
        [IO.File]::WriteAllText(
            $ProbePath,
            $ProbeCode,
            [System.Text.UTF8Encoding]::new($false)
        )

        & $StagedPython -P -s $ProbePath
        if ($LASTEXITCODE -ne 0) {
            throw "Portable worker staged Python isolation probe failed."
        }
    }
    finally {
        if (Test-Path -LiteralPath $ProbePath) {
            Remove-Item -LiteralPath $ProbePath -Force
        }
        $env:PYTHONHOME = $PreviousPythonHome
        $env:PYTHONPATH = $PreviousPythonPath
        $env:PYTHONNOUSERSITE = $PreviousPythonNoUserSite
        $env:PYTHONDONTWRITEBYTECODE = $PreviousPythonDontWriteBytecode
        $env:QTB_FORBIDDEN_SYS_PATH_ROOTS = $PreviousForbiddenRoots
        $env:QTB_PROBE_QWEN_IMPORT = $PreviousProbeQwenImport
        $env:QTB_PROBE_FASTER_QWEN_IMPORT = $PreviousProbeFasterQwenImport
    }
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
set "PYTHONDONTWRITEBYTECODE=1"
"%WORKER_ROOT%python\python.exe" -B -P -s -m qwen_tts_bridge_worker %*
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
$PythonToolVersions = Get-PythonToolVersions

Assert-RelativeDirectoryName $WorkerDirectoryName

$PackageRoot = Resolve-RepoPath $OutputRoot
$WorkerOutput = Join-Path $PackageRoot $WorkerDirectoryName
$PythonOutput = Join-Path $WorkerOutput "python"
$SitePackagesOutput = Join-Path $PythonOutput "Lib/site-packages"
$WheelWorkRoot = Join-Path $WorkerOutput ".wheel-build"
$WheelArtifactRoot = Join-Path $WorkerOutput "wheels"
$PortableRuntimeTreeManifestPath = Join-Path $WorkerOutput "portable-python-tree-manifest.json"
$WorkerPackageSource = Resolve-RepoPath "worker/src/qwen_tts_bridge_worker"
$WorkerProjectSource = Resolve-RepoPath "worker"
$LauncherPath = Join-Path $WorkerOutput "qwen_tts_worker.cmd"
$DoctorLauncherPath = Join-Path $WorkerOutput "qwen_tts_doctor.cmd"

Assert-UnderRepo $PackageRoot
Assert-UnderRepo $WorkerOutput
Assert-UnderRepo $WorkerPackageSource
Assert-UnderRepo $WorkerProjectSource
Assert-StrictChildPath -Parent $RepoRoot -Path $WorkerOutput -Description "WorkerOutput"
Assert-StrictChildPath -Parent $PackageRoot -Path $WorkerOutput -Description "WorkerOutput"
Assert-NotUnderPath -Parent $WorkerProjectSource -Path $WorkerOutput -Description "WorkerOutput"

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
    Assert-NotUnderPath -Parent $ResolvedQwenSourcePath -Path $WorkerOutput -Description "WorkerOutput"
}

$FasterQwenPackageSource = $null
if ($IncludeFasterQwen) {
    $ResolvedFasterQwenSourcePath = Resolve-RepoPath $FasterQwenSourcePath
    $FasterQwenPackageSource = Join-Path $ResolvedFasterQwenSourcePath "faster_qwen3_tts"
    if (-not (Test-Path -LiteralPath $FasterQwenPackageSource)) {
        throw "faster-qwen3-tts package source was not found: $FasterQwenPackageSource"
    }
    Assert-NotUnderPath -Parent $ResolvedFasterQwenSourcePath -Path $WorkerOutput -Description "WorkerOutput"
}

Write-Host "Portable Python worker source runtime: $BasePrefix"
Write-Host "Portable Python worker source site-packages: $PureLib"
Write-Host "Portable Python worker output: $WorkerOutput"
Write-Host "Portable Python worker launcher: $LauncherPath"
if ($IncludeQwenFork) {
    Write-Host "Portable Python worker includes Qwen fork: $QwenPackageSource"
}
if ($IncludeFasterQwen) {
    Write-Host "Portable Python worker includes faster-qwen3-tts: $FasterQwenPackageSource"
}

if ($DryRun) {
    return
}

if (Test-Path -LiteralPath $WorkerOutput) {
    Assert-UnderRepo $WorkerOutput
    Assert-PortableWorkerMarker $WorkerOutput
    if ($Clean) {
        Remove-Item -LiteralPath $WorkerOutput -Recurse -Force
    }
}

New-Item -ItemType Directory -Force -Path $WorkerOutput | Out-Null
Write-PortableWorkerMarker $WorkerOutput
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
Remove-StagedPackageArtifacts `
    -SitePackages $SitePackagesOutput `
    -PackageNames @(
        "qwen_tts_bridge_worker",
        "qwen-tts-bridge-worker",
        "qwen_tts",
        "qwen-tts",
        "faster_qwen3_tts",
        "faster-qwen3-tts"
    )

$WheelReports = @()

$WheelReports += Install-ProjectWheelToTarget `
    -ProjectPath $WorkerProjectSource `
    -SitePackages $SitePackagesOutput `
    -WheelWorkRoot $WheelWorkRoot `
    -WheelArtifactRoot $WheelArtifactRoot `
    -Label "worker"

if ($null -ne $QwenPackageSource) {
    $WheelReports += Install-ProjectWheelToTarget `
        -ProjectPath $ResolvedQwenSourcePath `
        -SitePackages $SitePackagesOutput `
        -WheelWorkRoot $WheelWorkRoot `
        -WheelArtifactRoot $WheelArtifactRoot `
        -Label "qwen"
}

if ($null -ne $FasterQwenPackageSource) {
    $WheelReports += Install-ProjectWheelToTarget `
        -ProjectPath $ResolvedFasterQwenSourcePath `
        -SitePackages $SitePackagesOutput `
        -WheelWorkRoot $WheelWorkRoot `
        -WheelArtifactRoot $WheelArtifactRoot `
        -Label "faster-qwen"
}

Assert-CleanSources -Wheels $WheelReports
$PythonPipFreeze = Get-PipFreeze -Path $SitePackagesOutput

if (Test-Path -LiteralPath $WheelWorkRoot) {
    Remove-Item -LiteralPath $WheelWorkRoot -Recurse -Force
}

function Write-DoctorLauncher {
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
set "PYTHONDONTWRITEBYTECODE=1"
"%WORKER_ROOT%python\python.exe" -B -P -s -m qwen_tts_bridge_worker.doctor --portable-root "%WORKER_ROOT%." %*
'@
    [IO.File]::WriteAllText(
        $LauncherPath,
        $LauncherContent.Replace("`n", "`r`n"),
        [System.Text.UTF8Encoding]::new($false)
    )
}

Assert-PortableSitePaths -SitePackages $SitePackagesOutput
Invoke-StagedPythonIsolationProbe `
    -PythonRoot $PythonOutput `
    -SitePackages $SitePackagesOutput `
    -ForbiddenRoots @(
        $WorkerPackageSource,
        $PureLib,
        $PlatLib,
        $QwenPackageSource,
        $FasterQwenPackageSource
    ) `
    -ProbeQwenImport:($null -ne $QwenPackageSource) `
    -ProbeFasterQwenImport:($null -ne $FasterQwenPackageSource)

# The probe imports the staged runtime. Seal the final tree only after removing
# every transient file it could have created.
Remove-PythonBytecode -Root $PythonOutput
Invoke-ProjectPython @(
    "scripts/runtime_tree_manifest.py",
    "build",
    "--root",
    $PythonOutput,
    "--output",
    $PortableRuntimeTreeManifestPath
)
Invoke-ProjectPython @(
    "scripts/runtime_tree_manifest.py",
    "verify",
    "--root",
    $PythonOutput,
    "--manifest",
    $PortableRuntimeTreeManifestPath
)

Write-BuildManifest `
    -Path (Join-Path $WorkerOutput "build-manifest.json") `
    -Wheels $WheelReports `
    -PythonEnvironment $PythonEnvironment `
    -ToolVersions $PythonToolVersions `
    -PipFreeze $PythonPipFreeze `
    -PortableRuntimeTreeManifest $PortableRuntimeTreeManifestPath

Write-WorkerLauncher -LauncherPath $LauncherPath
Write-DoctorLauncher -LauncherPath $DoctorLauncherPath
New-Item -ItemType Directory -Force -Path (Join-Path $PackageRoot "config") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $PackageRoot "models") | Out-Null

if (
    -not (Test-Path -LiteralPath $LauncherPath) -or
    -not (Test-Path -LiteralPath $DoctorLauncherPath)
) {
    throw "Portable Python worker launchers were not found under: $WorkerOutput"
}

Write-Host "Portable Python worker launcher: $LauncherPath"
Write-Host "Portable Python worker doctor: $DoctorLauncherPath"
