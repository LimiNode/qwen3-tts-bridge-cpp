param(
    [string]$Python = "py",
    [string[]]$PythonArgs,
    [switch]$UseVenv,
    [string]$VenvPath = ".venv-packaging",
    [string]$OutputRoot = "dist/QwenTTSBridge",
    [string]$NuitkaWorkRoot = "tmp/nuitka-worker",
    [switch]$Clean,
    [switch]$DryRun,
    [switch]$AssumeYesForDownloads,
    [switch]$IncludeQwenPackage,
    [ValidateSet("None", "CustomVoice", "VoiceDesign", "VoiceClone", "Full")]
    [string]$QwenProfile = "None",
    [string]$NuitkaReportPath = "",
    [switch]$ShowNuitkaProgress,
    [switch]$ShowNuitkaMemory,
    [switch]$StrictBloatChecks,
    [switch]$GenerateCOnly,
    [string[]]$ExtraNuitkaOptions = @()
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

function Assert-PackagingPythonVersion {
    $VersionOutput = & $Python @PythonArgs -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to run packaging Python. Install Python $RequiredPythonVersion or pass -Python/-PythonArgs explicitly."
    }

    $Version = ($VersionOutput | Select-Object -First 1).Trim()
    if ($Version -ne $RequiredPythonVersion) {
        throw "Packaging Python must be $RequiredPythonVersion; selected Python is $Version. Recreate $VenvPath with Python $RequiredPythonVersion or pass -Python/-PythonArgs explicitly."
    }
}

function Format-CommandLine {
    param(
        [string]$Executable,
        [string[]]$Arguments
    )

    $Items = @($Executable) + $Arguments
    return ($Items | ForEach-Object {
        if ($_ -match "[\s`"]") {
            return '"' + ($_ -replace '"', '\"') + '"'
        }
        return $_
    }) -join " "
}

function Get-QwenPackageConfigOptions {
    param(
        [string]$Profile
    )

    $ConfigPaths = @("worker/packaging/nuitka-qwen-runtime.yml")
    if ($Profile -in @("CustomVoice", "VoiceDesign")) {
        $ConfigPaths += "worker/packaging/nuitka-qwen-narrow-audio.yml"
    }

    return @(
        $ConfigPaths | ForEach-Object {
            "--user-package-configuration-file=$(Resolve-RepoPath $_)"
        }
    )
}

function Get-QwenBaseNuitkaOptions {
    param(
        [string]$Profile
    )

    $Options = @(Get-QwenPackageConfigOptions $Profile)

    return $Options + @(
        # Include only the runtime Qwen modules used by the bridge worker.
        # A broad --include-package=qwen_tts also pulls qwen_tts.cli/demo UI
        # code and encourages Nuitka to inspect much more of Transformers.
        "--include-module=qwen_tts",
        "--include-package=qwen_tts.inference",
        "--include-module=qwen_tts.core",
        "--include-module=qwen_tts.core.models",
        "--include-module=qwen_tts.core.models.configuration_qwen3_tts",
        "--include-module=qwen_tts.core.models.modeling_qwen3_tts",
        "--include-module=qwen_tts.core.models.processing_qwen3_tts",
        "--include-module=qwen_tts.core.tokenizer_12hz.configuration_qwen3_tts_tokenizer_v2",
        "--include-module=qwen_tts.core.tokenizer_12hz.modeling_qwen3_tts_tokenizer_v2",
        "--include-module=qwen_tts.core.tokenizer_12hz.optimized_decoder",
        "--include-module=qwen_tts.core.tokenizer_25hz.configuration_qwen3_tts_tokenizer_v1",
        "--include-module=qwen_tts.core.tokenizer_25hz.modeling_qwen3_tts_tokenizer_v1",
        "--include-package=transformers.distributed",
        "--include-package=transformers.generation",
        "--include-module=transformers.integrations.peft",
        "--include-module=transformers.models.encodec",
        "--include-module=transformers.models.encodec.feature_extraction_encodec",
        "--include-package-data=qwen_tts",
        "--include-distribution-metadata=torch",
        "--nofollow-import-to=qwen_tts.cli",
        "--nofollow-import-to=gradio",
        "--nofollow-import-to=einops.layers.flax",
        "--nofollow-import-to=einops.layers.keras",
        "--nofollow-import-to=einops.layers.oneflow",
        "--nofollow-import-to=einops.layers.paddle",
        "--nofollow-import-to=einops.layers.tensorflow",
        "--nofollow-import-to=torch._dynamo",
        "--nofollow-import-to=torch._inductor",
        "--nofollow-import-to=torch.fx.experimental.symbolic_shapes",
        "--nofollow-import-to=torch.utils._sympy",
        "--noinclude-setuptools-mode=nofollow",
        "--noinclude-pytest-mode=nofollow",
        "--noinclude-IPython-mode=nofollow",
        "--noinclude-dask-mode=nofollow",
        "--noinclude-numba-mode=nofollow",
        "--module-parameter=torch-disable-jit=yes",
        "--module-parameter=numba-disable-jit=yes",
        "--no-deployment-flag=excluded-module-usage",
        "--disable-plugins=transformers"
    )
}

function Get-QwenVoiceCloneNuitkaOptions {
    return @(
        "--include-package=librosa",
        "--include-module=soundfile"
    )
}

function Get-QwenFullNuitkaOptions {
    return @(
        "--include-package=qwen_tts",
        "--include-package-data=qwen_tts"
    )
}

function Get-QwenProfileNuitkaOptions {
    param(
        [string]$Profile
    )

    switch ($Profile) {
        "None" {
            return @()
        }
        "CustomVoice" {
            return Get-QwenBaseNuitkaOptions $Profile
        }
        "VoiceDesign" {
            return Get-QwenBaseNuitkaOptions $Profile
        }
        "VoiceClone" {
            return (Get-QwenBaseNuitkaOptions $Profile) + (Get-QwenVoiceCloneNuitkaOptions)
        }
        "Full" {
            return Get-QwenFullNuitkaOptions
        }
    }

    throw "Unsupported QwenProfile: $Profile"
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

$PackageRoot = Resolve-RepoPath $OutputRoot
$NuitkaOutputRoot = Resolve-RepoPath $NuitkaWorkRoot
$EntryPoint = Resolve-RepoPath "worker/packaging/qwen_tts_worker_entry.py"
$WorkerSrc = Resolve-RepoPath "worker/src"
$NuitkaReport = $null

if (-not [string]::IsNullOrWhiteSpace($NuitkaReportPath)) {
    $NuitkaReport = Resolve-RepoPath $NuitkaReportPath
}

Assert-UnderRepo $PackageRoot
Assert-UnderRepo $NuitkaOutputRoot
Assert-UnderRepo $EntryPoint
Assert-UnderRepo $WorkerSrc
if ($null -ne $NuitkaReport) {
    Assert-UnderRepo $NuitkaReport
}

if ([string]::IsNullOrWhiteSpace($env:PYTHONPATH)) {
    $env:PYTHONPATH = $WorkerSrc
}
else {
    $env:PYTHONPATH = "$WorkerSrc$([IO.Path]::PathSeparator)$env:PYTHONPATH"
}

$NuitkaArgs = @(
    "-m",
    "nuitka",
    "--mode=standalone",
    "--output-dir=$NuitkaOutputRoot",
    "--output-filename=qwen_tts_worker.exe",
    "--include-package=qwen_tts_bridge_worker",
    "--remove-output"
)

if ($AssumeYesForDownloads) {
    $NuitkaArgs += "--assume-yes-for-downloads"
}

if ($IncludeQwenPackage) {
    if ($QwenProfile -ne "None") {
        throw "-IncludeQwenPackage cannot be combined with -QwenProfile $QwenProfile."
    }
    $QwenProfile = "CustomVoice"
}

$NuitkaArgs += Get-QwenProfileNuitkaOptions $QwenProfile

if ($StrictBloatChecks) {
    $NuitkaArgs += "--noinclude-default-mode=error"
}

if ($GenerateCOnly) {
    $NuitkaArgs += "--generate-c-only"
}

if ($null -ne $NuitkaReport) {
    $NuitkaArgs += "--report=$NuitkaReport"
}

if ($ShowNuitkaProgress) {
    $NuitkaArgs += "--show-progress"
}

if ($ShowNuitkaMemory) {
    $NuitkaArgs += "--show-memory"
}

$NuitkaArgs += $ExtraNuitkaOptions
$NuitkaArgs += $EntryPoint

Write-Host "Nuitka command:"
Write-Host (Format-CommandLine $Python (@($PythonArgs) + $NuitkaArgs))
Write-Host "Package output: $PackageRoot"

if ($DryRun) {
    return
}

if ($Clean) {
    foreach ($Path in @($PackageRoot, $NuitkaOutputRoot)) {
        Assert-UnderRepo $Path
        if (Test-Path -LiteralPath $Path) {
            Remove-Item -LiteralPath $Path -Recurse -Force
        }
    }
}

if ($null -ne $NuitkaReport) {
    $NuitkaReportParent = Split-Path -Parent $NuitkaReport
    if (-not [string]::IsNullOrWhiteSpace($NuitkaReportParent)) {
        New-Item -ItemType Directory -Force -Path $NuitkaReportParent | Out-Null
    }
}

Invoke-ProjectPython $NuitkaArgs

if ($GenerateCOnly) {
    Write-Host "Generated Nuitka C sources under: $NuitkaOutputRoot"
    return
}

$ExpectedNuitkaDist = Join-Path $NuitkaOutputRoot "qwen_tts_worker_entry.dist"
if (Test-Path -LiteralPath $ExpectedNuitkaDist) {
    $NuitkaDist = $ExpectedNuitkaDist
}
else {
    $DistCandidates = @(
        Get-ChildItem -LiteralPath $NuitkaOutputRoot -Directory -Filter "*.dist"
    )
    if ($DistCandidates.Count -ne 1) {
        throw "Expected one Nuitka .dist directory under $NuitkaOutputRoot."
    }
    $NuitkaDist = $DistCandidates[0].FullName
}

$WorkerOutput = Join-Path $PackageRoot "worker"
if (Test-Path -LiteralPath $WorkerOutput) {
    Assert-UnderRepo $WorkerOutput
    Remove-Item -LiteralPath $WorkerOutput -Recurse -Force
}

New-Item -ItemType Directory -Force -Path $WorkerOutput | Out-Null
Copy-Item -Path (Join-Path $NuitkaDist "*") -Destination $WorkerOutput -Recurse
New-Item -ItemType Directory -Force -Path (Join-Path $PackageRoot "config") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $PackageRoot "models") | Out-Null

if ($QwenProfile -ne "None") {
    # Transformers imports transformers.models as a package and also scans that
    # package for at least one default-backend entry in its lazy import table.
    # Qwen imports Auto/Mimi classes through direct submodules, so a tiny
    # placeholder keeps root Transformers startup valid without packaging the
    # whole model zoo.
    $TransformersModels = Join-Path $WorkerOutput "transformers/models"
    New-Item -ItemType Directory -Force -Path $TransformersModels | Out-Null

    $TransformersModelsInit = Join-Path $TransformersModels "__init__.py"
    [IO.File]::WriteAllText($TransformersModelsInit, "", [System.Text.UTF8Encoding]::new($false))

    $TransformersPlaceholder = Join-Path $TransformersModels "qtb_packaging_placeholder.py"
    [IO.File]::WriteAllText($TransformersPlaceholder, @'
__all__ = ["QtbPackagingPlaceholder"]


class QtbPackagingPlaceholder:
    pass
'@, [System.Text.UTF8Encoding]::new($false))

    foreach ($PackageName in @("auto", "mimi")) {
        $TransformersModelPackage = Join-Path $TransformersModels $PackageName
        New-Item -ItemType Directory -Force -Path $TransformersModelPackage | Out-Null

        $TransformersModelPackageInit = Join-Path $TransformersModelPackage "__init__.py"
        if ($PackageName -eq "auto") {
            [IO.File]::WriteAllText($TransformersModelPackageInit, @'
from .configuration_auto import AutoConfig
from .feature_extraction_auto import AutoFeatureExtractor
from .modeling_auto import AutoModel
from .processing_auto import AutoProcessor

__all__ = [
    "AutoConfig",
    "AutoFeatureExtractor",
    "AutoModel",
    "AutoProcessor",
]
'@, [System.Text.UTF8Encoding]::new($false))
        } else {
            [IO.File]::WriteAllText(
                $TransformersModelPackageInit,
                "",
                [System.Text.UTF8Encoding]::new($false)
            )
        }

        $ClassName = "Qtb" + $PackageName.Substring(0, 1).ToUpperInvariant() +
            $PackageName.Substring(1) + "Placeholder"
        $PlaceholderPath = Join-Path $TransformersModelPackage "qtb_packaging_placeholder.py"
        [IO.File]::WriteAllText($PlaceholderPath, @"
__all__ = ["$ClassName"]


class ${ClassName}:
    pass
"@, [System.Text.UTF8Encoding]::new($false))
    }
}

$WorkerExe = Join-Path $WorkerOutput "qwen_tts_worker.exe"
if (-not (Test-Path -LiteralPath $WorkerExe)) {
    throw "Packaged worker executable was not found: $WorkerExe"
}

Write-Host "Packaged worker: $WorkerExe"
