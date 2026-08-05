[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$PackageRoot,
    [string]$RelocationRoot,
    [switch]$InPlace,
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

$CommandResults = [System.Collections.Generic.List[object]]::new()

function Invoke-Checked {
    param(
        [string]$Name,
        [string]$FilePath,
        [string[]]$Arguments
    )

    $started = [DateTime]::UtcNow
    & $FilePath @Arguments
    $exitCode = $LASTEXITCODE
    $CommandResults.Add([ordered]@{
        name = $Name
        exit_code = $exitCode
        duration_ms = [math]::Round(([DateTime]::UtcNow - $started).TotalMilliseconds, 3)
    })
    if ($exitCode -ne 0) {
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
        [int]$TimeoutMilliseconds,
        [string]$ResultJson
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
        "--result-json", $ResultJson,
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
    Invoke-Checked -Name "smoke_$([IO.Path]::GetFileNameWithoutExtension($Output))" `
        -FilePath (Join-Path $Bin "qwen_tts_save_wav.exe") -Arguments $arguments
    if (-not (Test-Path -LiteralPath $ResultJson)) {
        throw "Smoke did not write result JSON: $ResultJson"
    }
    $result = Get-Content -LiteralPath $ResultJson -Raw | ConvertFrom-Json
    if (
        $result.schema_version -ne 1 -or
        $result.terminal_state -ne "completed" -or
        -not $result.completion_metadata_received -or
        $result.execution_outcome -ne "completed" -or
        $result.termination_reason -ne "eos" -or
        -not $result.hit_eos -or
        $result.hit_max_seq_len -or
        $result.hit_max_new_tokens -or
        $result.audio_chunks -lt 1 -or
        $result.audio_bytes -lt 1 -or
        $result.codec_frame_count -lt 1
    ) {
        throw "Smoke result JSON does not prove one natural-EOS completion: $ResultJson"
    }
    return $result
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

if ($InPlace -and $RelocationRoot) {
    throw "RelocationRoot cannot be used with -InPlace"
}
if (-not $InPlace -and -not $RelocationRoot) {
    throw "RelocationRoot is required unless -InPlace is selected"
}
if ($InPlace) {
    $relocated = $source
}
else {
    if (Test-Path -LiteralPath $RelocationRoot) {
        throw "RelocationRoot must not already exist: $RelocationRoot"
    }
    $relocated = [IO.Path]::GetFullPath($RelocationRoot)
}
$relocationParent = Split-Path -Parent $relocated
New-Item -ItemType Directory -Force -Path $relocationParent | Out-Null
if (-not $ReportPath) {
    $ReportPath = Join-Path $relocationParent "$(Split-Path -Leaf $relocated)-report.json"
}
$report = [IO.Path]::GetFullPath($ReportPath)
if (Test-Path -LiteralPath $report) {
    throw "ReportPath must not already exist: $report"
}

if (-not $InPlace) {
    & robocopy $source $relocated /E /COPY:DAT /DCOPY:DAT /R:1 /W:1 /NFL /NDL /NJH /NJS | Out-Null
    if ($LASTEXITCODE -gt 7) {
        throw "robocopy failed while relocating technical-beta package (exit $LASTEXITCODE)"
    }
    $CommandResults.Add([ordered]@{
        name = "relocate_package"
        exit_code = 0
        duration_ms = 0
    })
}

Invoke-Checked -Name "verify_package_tree_pre_smoke" -FilePath $python -Arguments @(
    "scripts/package_tree_manifest.py", "verify",
    "--root", $relocated,
    "--manifest", (Join-Path $relocated "manifests/package-tree-manifest.json")
)
Invoke-Checked -Name "verify_voice_assets_pre_smoke" -FilePath $python -Arguments @(
    "scripts/voice_assets_manifest.py", "verify",
    "--root", $relocated,
    "--manifest", (Join-Path $relocated "manifests/voice-assets-manifest.json")
)
Assert-NativeClosure -Root $relocated -ObjectDump $objectDump
$CommandResults.Add([ordered]@{
    name = "verify_native_closure"
    exit_code = 0
    duration_ms = 0
})

$previousEnvironment = @{}
foreach ($name in @(
    "PATH", "PYTHONHOME", "PYTHONPATH", "PYTHONNOUSERSITE", "PYTHONDONTWRITEBYTECODE",
    "HF_HOME", "HF_HUB_CACHE", "TRANSFORMERS_CACHE", "TORCH_HOME", "XDG_CACHE_HOME",
    "HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"
)) {
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
    $env:HF_HOME = Join-Path $worker "runtime-cache\huggingface"
    $env:HF_HUB_CACHE = Join-Path $worker "runtime-cache\huggingface\hub"
    $env:TRANSFORMERS_CACHE = Join-Path $worker "runtime-cache\transformers"
    $env:TORCH_HOME = Join-Path $worker "runtime-cache\torch"
    $env:XDG_CACHE_HOME = Join-Path $worker "runtime-cache"
    $env:HF_HUB_OFFLINE = "1"
    $env:TRANSFORMERS_OFFLINE = "1"
    Push-Location $worker

    Invoke-Checked -Name "doctor_custom_voice_pre_smoke" `
        -FilePath (Join-Path $worker "qwen_tts_doctor.cmd") -Arguments @(
        "--model-path", $customVoiceModel,
        "--model-manifest", $customVoiceManifest,
        "--require-cuda"
    )
    Invoke-Checked -Name "doctor_base_pre_smoke" `
        -FilePath (Join-Path $worker "qwen_tts_doctor.cmd") -Arguments @(
        "--model-path", $baseModel,
        "--model-manifest", $baseManifest,
        "--voice-registry", (Join-Path $relocated "config\voice-profiles.json"),
        "--require-cuda"
    )
    $customOutput = Join-Path $relocationParent "$(Split-Path -Leaf $relocated)-customvoice-eos.wav"
    $customResultJson = Join-Path $relocationParent "$(Split-Path -Leaf $relocated)-customvoice-eos.json"
    $customSmoke = Invoke-QwenSmoke -Bin $bin -Worker $worker -Model $customVoiceModel `
        -Text "Relocated portable worker reaches natural EOS." -Output $customOutput `
        -Language "English" -Speaker "serena" -VoiceId "" -TimeoutMilliseconds 180000 `
        -ResultJson $customResultJson
    $baseOutput = Join-Path $relocationParent "$(Split-Path -Leaf $relocated)-base-eos.wav"
    $baseResultJson = Join-Path $relocationParent "$(Split-Path -Leaf $relocated)-base-eos.json"
    $baseSmoke = Invoke-QwenSmoke -Bin $bin -Worker $worker -Model $baseModel `
        -Text "Relocated Base worker reaches natural EOS." -Output $baseOutput `
        -Language "English" -Speaker "" -VoiceId $BaseVoiceId -TimeoutMilliseconds 300000 `
        -ResultJson $baseResultJson

    Invoke-Checked -Name "doctor_custom_voice_post_smoke" `
        -FilePath (Join-Path $worker "qwen_tts_doctor.cmd") -Arguments @(
        "--model-path", $customVoiceModel,
        "--model-manifest", $customVoiceManifest,
        "--require-cuda"
    )
    Invoke-Checked -Name "doctor_base_post_smoke" `
        -FilePath (Join-Path $worker "qwen_tts_doctor.cmd") -Arguments @(
        "--model-path", $baseModel,
        "--model-manifest", $baseManifest,
        "--voice-registry", (Join-Path $relocated "config\voice-profiles.json"),
        "--require-cuda"
    )
}
finally {
    if ((Get-Location).Path -eq $worker) {
        Pop-Location
    }
    foreach ($name in $previousEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($name, $previousEnvironment[$name], "Process")
    }
}

$bytecode = Get-ChildItem -LiteralPath $relocated -Recurse -Force -File |
    Where-Object { $_.Extension -in ".pyc", ".pyo" }
if ($bytecode.Count -ne 0) {
    throw "Relocated package wrote Python bytecode."
}
Invoke-Checked -Name "verify_package_tree_post_smoke" -FilePath $python -Arguments @(
    "scripts/package_tree_manifest.py", "verify",
    "--root", $relocated,
    "--manifest", (Join-Path $relocated "manifests/package-tree-manifest.json")
)
Invoke-Checked -Name "verify_voice_assets_post_smoke" -FilePath $python -Arguments @(
    "scripts/voice_assets_manifest.py", "verify",
    "--root", $relocated,
    "--manifest", (Join-Path $relocated "manifests/voice-assets-manifest.json")
)

$packageManifest = Get-Content -LiteralPath (Join-Path $relocated "manifests/package-tree-manifest.json") -Raw |
    ConvertFrom-Json
$voiceManifest = Get-Content -LiteralPath (Join-Path $relocated "manifests/voice-assets-manifest.json") -Raw |
    ConvertFrom-Json
$reportValue = [ordered]@{
    schema_version = 2
    validation_kind = if ($InPlace) { "same_host_published_private_runtime" } else { "same_host_relocated_private_runtime" }
    package = [ordered]@{
        package_tree_manifest_sha256 = $packageManifest.package_tree_manifest_sha256
        voice_assets_manifest_sha256 = $voiceManifest.voice_assets_manifest_sha256
        immutable_tree_policy = [ordered]@{
            sealed_files = "all"
            sealed_directories = "all_except_empty_named_mutable_directories"
            mutable_empty_directory_names = @($packageManifest.mutable_empty_directory_names)
            pre_smoke_manifest = "passed"
            post_smoke_manifest = "passed"
        }
    }
    isolation = [ordered]@{
        working_directory = "package_worker"
        pythonhome = "package_worker_python"
        pythonpath = "package_worker_site_packages"
        user_site_disabled = $true
        bytecode_disabled = $true
        hf_offline = $true
        transformers_offline = $true
        base_voice_registry = "package_config/voice-profiles.json"
    }
    commands = @($CommandResults)
    smokes = [ordered]@{
        custom_voice = [ordered]@{
            result = $customSmoke
            output_sha256 = (Get-FileHash -LiteralPath $customOutput -Algorithm SHA256).Hash.ToLowerInvariant()
        }
        base = [ordered]@{
            voice_id = $BaseVoiceId
            result = $baseSmoke
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
