param(
    [string]$OutputRoot = "dist/QwenTTSBridge-technical-beta",
    [string]$BuildDirectory = "build-mingw",
    [string]$PackagingVenvPath = ".venv-packaging",
    [string]$QwenSourcePath = "external/python/Qwen3-TTS-streaming",
    [string]$FasterQwenSourcePath = "C:\_repoz\faster-qwen3-tts-v032-stack112-clean",
    [string]$MinGwBin = "C:\MinGW\winlibs-x86_64-posix-seh-gcc-16.1.0-mingw-w64ucrt-14.0.0-r3\mingw64\bin",
    [switch]$Clean
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot
$MarkerName = ".qtb-technical-beta-root"

function Resolve-RepoPath {
    param([string]$Path)

    if ([IO.Path]::IsPathRooted($Path)) {
        return [IO.Path]::GetFullPath($Path)
    }
    return [IO.Path]::GetFullPath((Join-Path $RepoRoot $Path))
}

function Assert-UnderRepo {
    param([string]$Path)

    $Root = [IO.Path]::GetFullPath($RepoRoot).TrimEnd("\", "/")
    $Resolved = [IO.Path]::GetFullPath($Path).TrimEnd("\", "/")
    if ($Resolved -ne $Root -and -not $Resolved.StartsWith(
            "$Root\", [StringComparison]::OrdinalIgnoreCase
        )) {
        throw "Path must be inside the repository: $Resolved"
    }
}

function Assert-ExistingTechnicalBetaRoot {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath (Join-Path $Path $MarkerName))) {
        throw "Refusing to replace output without technical-beta marker: $Path"
    }
}

function Invoke-Checked {
    param(
        [string]$FilePath,
        [string[]]$Arguments
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed: $FilePath $($Arguments -join ' ')"
    }
}

function Get-ImportedDllNames {
    param(
        [string]$ObjectDump,
        [string]$Path
    )

    $Lines = & $ObjectDump -p $Path
    if ($LASTEXITCODE -ne 0) {
        throw "objdump failed for native executable: $Path"
    }
    return @(
        $Lines |
            Select-String -Pattern '^\s*DLL Name:\s*(.+)$' |
            ForEach-Object { $_.Matches[0].Groups[1].Value.Trim() } |
            Sort-Object -Unique
    )
}

function Copy-NativeRuntimeClosure {
    param(
        [string]$SourceDirectory,
        [string]$DestinationDirectory,
        [string]$MinGwDirectory
    )

    if (-not (Test-Path -LiteralPath $MinGwDirectory)) {
        throw "MinGW bin directory was not found: $MinGwDirectory"
    }
    $ObjectDump = Join-Path $MinGwDirectory "objdump.exe"
    if (-not (Test-Path -LiteralPath $ObjectDump)) {
        throw "MinGW objdump.exe was not found: $ObjectDump"
    }

    $NativeNames = @("qwen_tts_save_wav.exe", "qwen_tts_play.exe")
    foreach ($Name in $NativeNames) {
        $Source = Join-Path $SourceDirectory $Name
        if (-not (Test-Path -LiteralPath $Source)) {
            throw "Native example was not found: $Source"
        }
        Copy-Item -LiteralPath $Source -Destination (Join-Path $DestinationDirectory $Name) -Force
    }

    $SystemDlls = @(
        "ADVAPI32.dll", "API-MS-WIN-*.dll", "COMDLG32.dll", "GDI32.dll",
        "KERNEL32.dll", "MSVCRT.dll", "OLE32.dll", "SHELL32.dll", "USER32.dll",
        "WS2_32.dll", "WINMM.dll"
    )
    $Pending = [System.Collections.Generic.Queue[string]]::new()
    Get-ChildItem -LiteralPath $DestinationDirectory -Filter "*.exe" -File |
        ForEach-Object { $Pending.Enqueue($_.FullName) }
    $Inspected = [System.Collections.Generic.HashSet[string]]::new(
        [StringComparer]::OrdinalIgnoreCase
    )
    while ($Pending.Count -gt 0) {
        $Binary = $Pending.Dequeue()
        if (-not $Inspected.Add($Binary)) {
            continue
        }
        foreach ($DllName in Get-ImportedDllNames -ObjectDump $ObjectDump -Path $Binary) {
            if ($SystemDlls | Where-Object { $DllName -like $_ }) {
                continue
            }
            $Destination = Join-Path $DestinationDirectory $DllName
            if (-not (Test-Path -LiteralPath $Destination)) {
                $Source = Join-Path $MinGwDirectory $DllName
                if (-not (Test-Path -LiteralPath $Source)) {
                    throw "Non-system native dependency was not found in MinGW: $DllName"
                }
                Copy-Item -LiteralPath $Source -Destination $Destination -Force
            }
            $Pending.Enqueue($Destination)
        }
    }
}

$FinalRoot = Resolve-RepoPath $OutputRoot
Assert-UnderRepo $FinalRoot
$Parent = Split-Path -Parent $FinalRoot
New-Item -ItemType Directory -Force -Path $Parent | Out-Null
if (Test-Path -LiteralPath $FinalRoot) {
    Assert-ExistingTechnicalBetaRoot $FinalRoot
    if (-not $Clean) {
        throw "Output already exists; pass -Clean to replace it: $FinalRoot"
    }
}

$StageRoot = "$FinalRoot.pending-$([Guid]::NewGuid().ToString('N'))"
$BackupRoot = $null
New-Item -ItemType Directory -Force -Path $StageRoot | Out-Null
[IO.File]::WriteAllText(
    (Join-Path $StageRoot $MarkerName),
    "QwenTTSBridge technical-beta package.`r`n",
    [Text.UTF8Encoding]::new($false)
)

try {
    $PackagingPython = Join-Path (Resolve-RepoPath $PackagingVenvPath) "Scripts/python.exe"
    if (-not (Test-Path -LiteralPath $PackagingPython)) {
        throw "Packaging Python was not found: $PackagingPython"
    }
    $NativeSource = Resolve-RepoPath $BuildDirectory
    if (-not (Test-Path -LiteralPath $NativeSource)) {
        throw "Native build directory was not found: $NativeSource"
    }

    $ProvenanceDirectory = Join-Path $StageRoot "provenance"
    New-Item -ItemType Directory -Force -Path $ProvenanceDirectory | Out-Null
    Copy-Item -LiteralPath (Resolve-RepoPath "docs/voice-assets-provenance.json") `
        -Destination (Join-Path $ProvenanceDirectory "voice-assets-provenance.json") -Force
    $SourceRegistry = Resolve-RepoPath "config/voice-profiles.example.json"
    Invoke-Checked -FilePath $PackagingPython -Arguments @(
        "scripts/voice_assets_manifest.py", "stage",
        "--source-root", $RepoRoot,
        "--source-registry", $SourceRegistry,
        "--output-root", $StageRoot,
        "--registry", "config/voice-profiles.json",
        "--voice-dir", "voices",
        "--provenance", "provenance/voice-assets-provenance.json",
        "--voice-id", "kraftwerk_robot_ru_bootstrap_fidelity",
        "--voice-id", "kraftwerk_robot_ru_bootstrap_warm",
        "--voice-id", "kraftwerk_robot_ru_source_like",
        "--voice-id", "kraftwerk_robot_ru_warm_metal"
    )

    & (Resolve-RepoPath "scripts/package-python-worker.ps1") `
        -UseVenv `
        -VenvPath $PackagingVenvPath `
        -OutputRoot $StageRoot `
        -WorkerDirectoryName "worker" `
        -IncludeQwenFork `
        -QwenSourcePath $QwenSourcePath `
        -IncludeFasterQwen `
        -FasterQwenSourcePath $FasterQwenSourcePath
    if ($LASTEXITCODE -ne 0) {
        throw "Portable worker package build failed."
    }

    $BinDirectory = Join-Path $StageRoot "bin"
    New-Item -ItemType Directory -Force -Path $BinDirectory | Out-Null
    Copy-NativeRuntimeClosure `
        -SourceDirectory $NativeSource `
        -DestinationDirectory $BinDirectory `
        -MinGwDirectory $MinGwBin

    [IO.File]::WriteAllText(
        (Join-Path $StageRoot "README.txt"),
        "QwenTTSBridge technical beta. Models remain external and are selected at runtime.`r`n",
        [Text.UTF8Encoding]::new($false)
    )
    Copy-Item -LiteralPath (Resolve-RepoPath "scripts/start-packaged-qwen-tts.ps1") `
        -Destination (Join-Path $StageRoot "start-qwen-tts.ps1") -Force
    Copy-Item -LiteralPath (Resolve-RepoPath "config/packaged-runtime.local.example.json") `
        -Destination (Join-Path $StageRoot "config/runtime.local.example.json") -Force

    $VoiceManifest = Join-Path $StageRoot "manifests/voice-assets-manifest.json"
    Invoke-Checked -FilePath $PackagingPython -Arguments @(
        "scripts/voice_assets_manifest.py", "build",
        "--root", $StageRoot,
        "--registry", "config/voice-profiles.json",
        "--provenance", "provenance/voice-assets-provenance.json",
        "--output", $VoiceManifest,
        "--temperature", "0.45"
    )
    Invoke-Checked -FilePath $PackagingPython -Arguments @(
        "scripts/voice_assets_manifest.py", "verify",
        "--root", $StageRoot,
        "--manifest", $VoiceManifest
    )

    $PackageManifest = Join-Path $StageRoot "manifests/package-tree-manifest.json"
    Invoke-Checked -FilePath $PackagingPython -Arguments @(
        "scripts/package_tree_manifest.py", "build",
        "--root", $StageRoot,
        "--output", $PackageManifest
    )
    Invoke-Checked -FilePath $PackagingPython -Arguments @(
        "scripts/package_tree_manifest.py", "verify",
        "--root", $StageRoot,
        "--manifest", $PackageManifest
    )

    if (Test-Path -LiteralPath $FinalRoot) {
        $BackupRoot = "$FinalRoot.backup-$([Guid]::NewGuid().ToString('N'))"
        Move-Item -LiteralPath $FinalRoot -Destination $BackupRoot
        try {
            Move-Item -LiteralPath $StageRoot -Destination $FinalRoot
        }
        catch {
            if (-not (Test-Path -LiteralPath $FinalRoot) -and
                (Test-Path -LiteralPath $BackupRoot)) {
                Move-Item -LiteralPath $BackupRoot -Destination $FinalRoot
            }
            throw
        }
        Remove-Item -LiteralPath $BackupRoot -Recurse -Force
        $BackupRoot = $null
    }
    else {
        Move-Item -LiteralPath $StageRoot -Destination $FinalRoot
    }
}
catch {
    if ($null -ne $BackupRoot -and
        -not (Test-Path -LiteralPath $FinalRoot) -and
        (Test-Path -LiteralPath $BackupRoot)) {
        Move-Item -LiteralPath $BackupRoot -Destination $FinalRoot
    }
    if (Test-Path -LiteralPath $StageRoot) {
        Remove-Item -LiteralPath $StageRoot -Recurse -Force
    }
    throw
}

Write-Host "Technical-beta package sealed: $FinalRoot"
