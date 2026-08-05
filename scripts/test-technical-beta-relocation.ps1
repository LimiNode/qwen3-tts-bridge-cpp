[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$PackageRoot,
    [Parameter(Mandatory = $true)]
    [string]$RelocationRoot,
    [Parameter(Mandatory = $true)]
    [string]$ModelPath,
    [Parameter(Mandatory = $true)]
    [string]$ModelManifest,
    [Parameter(Mandatory = $true)]
    [string]$VerifierPython,
    [string]$MinGwBin = "C:\MinGW\winlibs-x86_64-posix-seh-gcc-16.1.0-mingw-w64ucrt-14.0.0-r3\mingw64\bin"
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

function Resolve-ExistingPath {
    param([string]$Path, [string]$Name)

    if (-not (Test-Path -LiteralPath $Path)) {
        throw "$Name was not found: $Path"
    }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Invoke-Checked {
    param([string]$FilePath, [string[]]$Arguments)

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed: $FilePath $($Arguments -join ' ')"
    }
}

function Get-ImportedDllNames {
    param([string]$ObjectDump, [string]$Path)

    $lines = & $ObjectDump -p $Path
    if ($LASTEXITCODE -ne 0) {
        throw "objdump failed for native executable: $Path"
    }
    return @(
        $lines |
            Select-String -Pattern '^\s*DLL Name:\s*(.+)$' |
            ForEach-Object { $_.Matches[0].Groups[1].Value.Trim() } |
            Sort-Object -Unique
    )
}

function Assert-NativeClosure {
    param([string]$Root, [string]$ObjectDump)

    $bin = Join-Path $Root "bin"
    $systemDlls = @(
        "ADVAPI32.dll", "API-MS-WIN-*.dll", "COMDLG32.dll", "GDI32.dll",
        "KERNEL32.dll", "MSVCRT.dll", "OLE32.dll", "SHELL32.dll", "USER32.dll",
        "WS2_32.dll", "WINMM.dll"
    )
    $pending = [System.Collections.Generic.Queue[string]]::new()
    Get-ChildItem -LiteralPath $bin -Filter "*.exe" -File |
        ForEach-Object { $pending.Enqueue($_.FullName) }
    $inspected = [System.Collections.Generic.HashSet[string]]::new(
        [StringComparer]::OrdinalIgnoreCase
    )
    while ($pending.Count -gt 0) {
        $binary = $pending.Dequeue()
        if (-not $inspected.Add($binary)) {
            continue
        }
        foreach ($dllName in Get-ImportedDllNames -ObjectDump $ObjectDump -Path $binary) {
            if ($systemDlls | Where-Object { $dllName -like $_ }) {
                continue
            }
            $packageDll = Join-Path $bin $dllName
            if (-not (Test-Path -LiteralPath $packageDll)) {
                throw "Package native dependency is missing: $dllName"
            }
            $pending.Enqueue($packageDll)
        }
    }
}

$source = Resolve-ExistingPath $PackageRoot "Technical-beta package"
$model = Resolve-ExistingPath $ModelPath "Model"
$manifest = Resolve-ExistingPath $ModelManifest "Model manifest"
$python = Resolve-ExistingPath $VerifierPython "Verifier Python"
$minGw = Resolve-ExistingPath $MinGwBin "MinGW bin"
$objectDump = Join-Path $minGw "objdump.exe"
if (-not (Test-Path -LiteralPath $objectDump)) {
    throw "MinGW objdump.exe was not found: $objectDump"
}

if (Test-Path -LiteralPath $RelocationRoot) {
    throw "RelocationRoot must not already exist: $RelocationRoot"
}
$relocated = [IO.Path]::GetFullPath($RelocationRoot)
$relocationParent = Split-Path -Parent $relocated
New-Item -ItemType Directory -Force -Path $relocationParent | Out-Null

& robocopy $source $relocated /E /COPY:DAT /DCOPY:DAT /R:1 /W:1 /NFL /NDL /NJH /NJS | Out-Null
if ($LASTEXITCODE -gt 7) {
    throw "robocopy failed while relocating technical-beta package (exit $LASTEXITCODE)"
}

Invoke-Checked -FilePath $python -Arguments @(
    "scripts/package_tree_manifest.py", "verify",
    "--root", $relocated,
    "--manifest", (Join-Path $relocated "manifests/package-tree-manifest.json")
)
Invoke-Checked -FilePath $python -Arguments @(
    "scripts/voice_assets_manifest.py", "verify",
    "--root", $relocated,
    "--manifest", (Join-Path $relocated "manifests/voice-assets-manifest.json")
)
Assert-NativeClosure -Root $relocated -ObjectDump $objectDump

$previousEnvironment = @{}
foreach ($name in @("PATH", "PYTHONHOME", "PYTHONPATH", "PYTHONNOUSERSITE", "PYTHONDONTWRITEBYTECODE")) {
    $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
}
try {
    $bin = Join-Path $relocated "bin"
    $worker = Join-Path $relocated "worker"
    $env:PATH = "$bin;$env:SystemRoot\System32;$env:SystemRoot"
    $env:PYTHONHOME = Join-Path $worker "python"
    $env:PYTHONPATH = Join-Path $worker "python\Lib\site-packages"
    $env:PYTHONNOUSERSITE = "1"
    $env:PYTHONDONTWRITEBYTECODE = "1"

    Invoke-Checked -FilePath (Join-Path $worker "qwen_tts_doctor.cmd") -Arguments @(
        "--model-path", $model,
        "--model-manifest", $manifest,
        "--require-cuda"
    )
    $output = Join-Path $relocationParent "$(Split-Path -Leaf $relocated)-customvoice-eos.wav"
    Invoke-Checked -FilePath (Join-Path $bin "qwen_tts_save_wav.exe") -Arguments @(
        "--worker", (Join-Path $worker "python\python.exe"),
        "--worker-arg", "-B", "--worker-arg", "-P", "--worker-arg", "-s",
        "--worker-arg", "-m", "--worker-arg", "qwen_tts_bridge_worker",
        "--worker-arg", "qwen", "--worker-arg", "--model-path", "--worker-arg", $model,
        "--worker-arg", "--runtime-backend", "--worker-arg", "faster",
        "--worker-arg", "--device", "--worker-arg", "cuda",
        "--worker-arg", "--dtype", "--worker-arg", "bfloat16",
        "--worker-arg", "--attn-implementation", "--worker-arg", "sdpa",
        "--worker-arg", "--prefill-backend", "--worker-arg", "eager",
        "--worker-arg", "--no-compile", "--worker-arg", "--no-cuda-graphs",
        "--worker-arg", "--collect-generation-trace",
        "--output", $output,
        "--text", "Relocated portable worker reaches natural EOS.",
        "--language", "English", "--speaker", "serena",
        "--request-timeout-ms", "180000", "--require-natural-eos"
    )
}
finally {
    foreach ($name in $previousEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($name, $previousEnvironment[$name], "Process")
    }
}

$bytecode = Get-ChildItem -LiteralPath $relocated -Recurse -Force -File |
    Where-Object { $_.Extension -in ".pyc", ".pyo" }
$cacheDirectories = Get-ChildItem -LiteralPath $relocated -Recurse -Force -Directory |
    Where-Object { $_.Name -eq "__pycache__" }
if ($bytecode.Count -ne 0 -or $cacheDirectories.Count -ne 0) {
    throw "Relocated package wrote Python bytecode."
}
Invoke-Checked -FilePath $python -Arguments @(
    "scripts/package_tree_manifest.py", "verify",
    "--root", $relocated,
    "--manifest", (Join-Path $relocated "manifests/package-tree-manifest.json")
)

Write-Host "Technical-beta relocation smoke passed: $relocated"
