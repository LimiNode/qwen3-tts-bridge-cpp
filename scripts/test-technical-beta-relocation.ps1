[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$PackageRoot,
    [Parameter(Mandatory = $true)]
    [string]$RelocationRoot,
    [Parameter(Mandatory = $true)]
    [string]$CustomVoiceModelPath,
    [Parameter(Mandatory = $true)]
    [string]$CustomVoiceModelManifest,
    [Parameter(Mandatory = $true)]
    [string]$BaseModelPath,
    [Parameter(Mandatory = $true)]
    [string]$BaseModelManifest,
    [Parameter(Mandatory = $true)]
    [string]$VerifierPython,
    [string]$BaseVoiceId = "kraftwerk_robot_ru_bootstrap_fidelity",
    [string]$ReportPath,
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

function Invoke-QwenSmoke {
    param(
        [string]$Bin,
        [string]$Worker,
        [string]$Model,
        [string]$Text,
        [string]$Output,
        [string]$Language,
        [string]$Speaker,
        [string]$VoiceId,
        [int]$TimeoutMilliseconds
    )

    $arguments = @(
        "--worker", (Join-Path $Worker "python\python.exe"),
        "--worker-arg", "-B", "--worker-arg", "-P", "--worker-arg", "-s",
        "--worker-arg", "-m", "--worker-arg", "qwen_tts_bridge_worker",
        "--worker-arg", "qwen", "--worker-arg", "--model-path", "--worker-arg", $Model,
        "--worker-arg", "--runtime-backend", "--worker-arg", "faster",
        "--worker-arg", "--device", "--worker-arg", "cuda",
        "--worker-arg", "--dtype", "--worker-arg", "bfloat16",
        "--worker-arg", "--attn-implementation", "--worker-arg", "sdpa",
        "--worker-arg", "--prefill-backend", "--worker-arg", "eager",
        "--worker-arg", "--no-compile", "--worker-arg", "--no-cuda-graphs",
        "--worker-arg", "--collect-generation-trace",
        "--output", $Output,
        "--text", $Text,
        "--language", $Language,
        "--request-timeout-ms", $TimeoutMilliseconds,
        "--require-natural-eos"
    )
    if ($Speaker) {
        $arguments += @("--speaker", $Speaker)
    }
    if ($VoiceId) {
        $arguments += @(
            "--worker-arg", "--voice-registry-path",
            "--worker-arg", (Join-Path $Worker "..\config\voice-profiles.json"),
            "--voice-id", $VoiceId
        )
    }
    Invoke-Checked -FilePath (Join-Path $Bin "qwen_tts_save_wav.exe") -Arguments $arguments
}

$source = Resolve-ExistingPath $PackageRoot "Technical-beta package"
$customVoiceModel = Resolve-ExistingPath $CustomVoiceModelPath "CustomVoice model"
$customVoiceManifest = Resolve-ExistingPath $CustomVoiceModelManifest "CustomVoice model manifest"
$baseModel = Resolve-ExistingPath $BaseModelPath "Base model"
$baseManifest = Resolve-ExistingPath $BaseModelManifest "Base model manifest"
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
if (-not $ReportPath) {
    $ReportPath = Join-Path $relocationParent "$(Split-Path -Leaf $relocated)-report.json"
}
$report = [IO.Path]::GetFullPath($ReportPath)
if (Test-Path -LiteralPath $report) {
    throw "ReportPath must not already exist: $report"
}

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
        "--model-path", $customVoiceModel,
        "--model-manifest", $customVoiceManifest,
        "--require-cuda"
    )
    Invoke-Checked -FilePath (Join-Path $worker "qwen_tts_doctor.cmd") -Arguments @(
        "--model-path", $baseModel,
        "--model-manifest", $baseManifest,
        "--voice-registry", (Join-Path $relocated "config\voice-profiles.json"),
        "--require-cuda"
    )
    $customOutput = Join-Path $relocationParent "$(Split-Path -Leaf $relocated)-customvoice-eos.wav"
    Invoke-QwenSmoke -Bin $bin -Worker $worker -Model $customVoiceModel `
        -Text "Relocated portable worker reaches natural EOS." -Output $customOutput `
        -Language "English" -Speaker "serena" -VoiceId "" -TimeoutMilliseconds 180000
    $baseOutput = Join-Path $relocationParent "$(Split-Path -Leaf $relocated)-base-eos.wav"
    Invoke-QwenSmoke -Bin $bin -Worker $worker -Model $baseModel `
        -Text "Relocated Base worker reaches natural EOS." -Output $baseOutput `
        -Language "English" -Speaker "" -VoiceId $BaseVoiceId -TimeoutMilliseconds 300000

    Invoke-Checked -FilePath (Join-Path $worker "qwen_tts_doctor.cmd") -Arguments @(
        "--model-path", $customVoiceModel,
        "--model-manifest", $customVoiceManifest,
        "--require-cuda"
    )
    Invoke-Checked -FilePath (Join-Path $worker "qwen_tts_doctor.cmd") -Arguments @(
        "--model-path", $baseModel,
        "--model-manifest", $baseManifest,
        "--voice-registry", (Join-Path $relocated "config\voice-profiles.json"),
        "--require-cuda"
    )
}
finally {
    foreach ($name in $previousEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($name, $previousEnvironment[$name], "Process")
    }
}

$bytecode = Get-ChildItem -LiteralPath $relocated -Recurse -Force -File |
    Where-Object { $_.Extension -in ".pyc", ".pyo" }
if ($bytecode.Count -ne 0) {
    throw "Relocated package wrote Python bytecode."
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

$packageManifest = Get-Content -LiteralPath (Join-Path $relocated "manifests/package-tree-manifest.json") -Raw |
    ConvertFrom-Json
$voiceManifest = Get-Content -LiteralPath (Join-Path $relocated "manifests/voice-assets-manifest.json") -Raw |
    ConvertFrom-Json
$reportValue = [ordered]@{
    schema_version = 1
    validation_kind = "same_host_relocated_private_runtime"
    package = [ordered]@{
        package_tree_manifest_sha256 = $packageManifest.package_tree_manifest_sha256
        voice_assets_manifest_sha256 = $voiceManifest.voice_assets_manifest_sha256
    }
    smokes = [ordered]@{
        custom_voice = [ordered]@{
            terminal_state = "completed"
            termination_reason = "eos"
            output_sha256 = (Get-FileHash -LiteralPath $customOutput -Algorithm SHA256).Hash.ToLowerInvariant()
        }
        base = [ordered]@{
            terminal_state = "completed"
            termination_reason = "eos"
            voice_id = $BaseVoiceId
            output_sha256 = (Get-FileHash -LiteralPath $baseOutput -Algorithm SHA256).Hash.ToLowerInvariant()
        }
    }
    post_smoke = [ordered]@{
        doctor_custom_voice = "passed"
        doctor_base = "passed"
        bytecode_files = 0
        package_tree_manifest = "passed"
        voice_assets_manifest = "passed"
        native_closure = "passed"
    }
}
[IO.File]::WriteAllText(
    $report,
    (($reportValue | ConvertTo-Json -Depth 6) + [Environment]::NewLine),
    [Text.UTF8Encoding]::new($false)
)

Write-Host "Technical-beta relocation smoke passed: $relocated"
Write-Host "Technical-beta relocation report: $report"
