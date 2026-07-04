param(
    [string]$WorkerRoot = "dist/QwenTTSBridge/worker-python",
    [switch]$ProbeQwenImport,
    [string[]]$ForbiddenRoots
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

function Resolve-RepoPath {
    param(
        [string]$Path
    )

    if ([IO.Path]::IsPathRooted($Path)) {
        return [IO.Path]::GetFullPath($Path)
    }

    return [IO.Path]::GetFullPath((Join-Path $RepoRoot $Path))
}

$ResolvedWorkerRoot = Resolve-RepoPath $WorkerRoot
$PythonRoot = Join-Path $ResolvedWorkerRoot "python"
$PythonExe = Join-Path $PythonRoot "python.exe"
$SitePackages = Join-Path $PythonRoot "Lib/site-packages"

if (-not (Test-Path -LiteralPath $PythonExe)) {
    throw "Portable worker python.exe was not found: $PythonExe"
}
if (-not (Test-Path -LiteralPath $SitePackages)) {
    throw "Portable worker site-packages was not found: $SitePackages"
}

if ($null -eq $ForbiddenRoots -or $ForbiddenRoots.Count -eq 0) {
    $ForbiddenRoots = @(
        "worker/src",
        ".venv-packaging/Lib/site-packages",
        "external/python/Qwen3-TTS-streaming/qwen_tts"
    )
}

$ResolvedForbiddenRoots = @(
    $ForbiddenRoots |
        ForEach-Object { Resolve-RepoPath $_ } |
        Where-Object { Test-Path -LiteralPath $_ } |
        Sort-Object -Unique
)

$PreviousPythonHome = $env:PYTHONHOME
$PreviousPythonPath = $env:PYTHONPATH
$PreviousPythonNoUserSite = $env:PYTHONNOUSERSITE
$PreviousPythonDontWriteBytecode = $env:PYTHONDONTWRITEBYTECODE
$PreviousForbiddenRoots = $env:QTB_FORBIDDEN_SYS_PATH_ROOTS
$PreviousProbeQwenImport = $env:QTB_PROBE_QWEN_IMPORT
$InspectorPath = Join-Path $PythonRoot "qtb_portable_worker_inspector.py"

try {
    $env:PYTHONHOME = $PythonRoot
    $env:PYTHONPATH = $SitePackages
    $env:PYTHONNOUSERSITE = "1"
    $env:PYTHONDONTWRITEBYTECODE = "1"
    $env:QTB_FORBIDDEN_SYS_PATH_ROOTS = (
        $ResolvedForbiddenRoots -join [IO.Path]::PathSeparator
    )
    if ($ProbeQwenImport) {
        $env:QTB_PROBE_QWEN_IMPORT = "1"
    }
    else {
        $env:QTB_PROBE_QWEN_IMPORT = ""
    }

    $InspectorCode = @'
import importlib.metadata
import importlib.util
import json
import os
import pathlib
import sys


def distribution_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def module_origin(name: str) -> str | None:
    spec = importlib.util.find_spec(name)
    if spec is None:
        return None
    return spec.origin


forbidden_roots = [
    pathlib.Path(path).resolve()
    for path in os.environ.get("QTB_FORBIDDEN_SYS_PATH_ROOTS", "").split(os.pathsep)
    if path
]
source_path_leaks: list[str] = []
for entry in sys.path:
    if not entry:
        continue
    resolved = pathlib.Path(entry).resolve()
    for root in forbidden_roots:
        try:
            resolved.relative_to(root)
        except ValueError:
            continue
        source_path_leaks.append(str(resolved))
        break

import qwen_tts_bridge_worker  # noqa: F401

qwen_import_probed = os.environ.get("QTB_PROBE_QWEN_IMPORT") == "1"
qwen_import_ok = None
if qwen_import_probed:
    import qwen_tts.inference.qwen3_tts_model  # noqa: F401

    qwen_import_ok = True

report = {
    "python": {
        "executable": sys.executable,
        "version": sys.version.split()[0],
        "prefix": sys.prefix,
        "base_prefix": sys.base_prefix,
    },
    "environment": {
        "PYTHONHOME": os.environ.get("PYTHONHOME"),
        "PYTHONPATH": os.environ.get("PYTHONPATH"),
        "PYTHONNOUSERSITE": os.environ.get("PYTHONNOUSERSITE"),
        "PYTHONDONTWRITEBYTECODE": os.environ.get("PYTHONDONTWRITEBYTECODE"),
    },
    "packages": {
        "qwen_tts_bridge_worker": {
            "version": distribution_version("qwen-tts-bridge-worker"),
            "origin": module_origin("qwen_tts_bridge_worker"),
        },
        "qwen_tts": {
            "version": distribution_version("qwen-tts"),
            "origin": module_origin("qwen_tts"),
        },
        "torch": {
            "version": distribution_version("torch"),
            "origin": module_origin("torch"),
        },
        "transformers": {
            "version": distribution_version("transformers"),
            "origin": module_origin("transformers"),
        },
    },
    "qwen_import_probed": qwen_import_probed,
    "qwen_import_ok": qwen_import_ok,
    "source_path_leaks": source_path_leaks,
    "sys_path": sys.path,
}

print(json.dumps(report, indent=2, sort_keys=True))
if source_path_leaks:
    raise SystemExit("portable worker sys.path leaks source paths")
'@

    [IO.File]::WriteAllText(
        $InspectorPath,
        $InspectorCode,
        [System.Text.UTF8Encoding]::new($false)
    )

    & $PythonExe -B -P -s $InspectorPath
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}
finally {
    if (Test-Path -LiteralPath $InspectorPath) {
        Remove-Item -LiteralPath $InspectorPath -Force
    }
    $env:PYTHONHOME = $PreviousPythonHome
    $env:PYTHONPATH = $PreviousPythonPath
    $env:PYTHONNOUSERSITE = $PreviousPythonNoUserSite
    $env:PYTHONDONTWRITEBYTECODE = $PreviousPythonDontWriteBytecode
    $env:QTB_FORBIDDEN_SYS_PATH_ROOTS = $PreviousForbiddenRoots
    $env:QTB_PROBE_QWEN_IMPORT = $PreviousProbeQwenImport
}
