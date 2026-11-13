param(
    [Parameter(Mandatory = $true)]
    [string]$NativeWorkerExecutable,
    [Parameter(Mandatory = $true)]
    [string]$RuntimeRoot,
    [Parameter(Mandatory = $true)]
    [string]$SaveWavExecutable,
    [Parameter(Mandatory = $true)]
    [string]$PlayExecutable,
    [string[]]$ConfigExample = @("config/native-package.example.json"),
    [string]$DependencyPolicy = "config/native-dependency-policy.json",
    [string[]]$DynamicDependency = @(),
    [Parameter(Mandatory = $true)]
    [string[]]$NoticeFile,
    [string]$LaunchInstructions = "docs/native-portable-package.md",
    [string]$OutputRoot = "dist/QwenTTSBridge-native",
    [string]$ZipPath,
    [string]$EngineCommit,
    [string]$Python = "python",
    [switch]$Clean
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$ReleaseMarker = ".qtb-native-release-root"

function Resolve-InputPath {
    param([string]$Path)
    if ([IO.Path]::IsPathRooted($Path)) {
        return [IO.Path]::GetFullPath($Path)
    }
    return [IO.Path]::GetFullPath((Join-Path $RepoRoot $Path))
}

function Assert-SafeTarget {
    param([string]$Path)
    $resolved = [IO.Path]::GetFullPath($Path).TrimEnd("\", "/")
    $repo = [IO.Path]::GetFullPath($RepoRoot).TrimEnd("\", "/")
    $drive = [IO.Path]::GetPathRoot($resolved).TrimEnd("\", "/")
    if ($resolved -eq $repo -or $resolved -eq $drive) {
        throw "Refusing to use broad native release target: $resolved"
    }
}

function Test-SameOrDescendant {
    param([string]$Path, [string]$Root)
    $pathValue = [IO.Path]::GetFullPath($Path).TrimEnd("\", "/")
    $rootValue = [IO.Path]::GetFullPath($Root).TrimEnd("\", "/")
    return $pathValue -eq $rootValue -or
        $pathValue.StartsWith($rootValue + "\", [StringComparison]::OrdinalIgnoreCase)
}

function Assert-NoPathOverlap {
    param([string]$LeftName, [string]$Left, [string]$RightName, [string]$Right)
    if ((Test-SameOrDescendant $Left $Right) -or (Test-SameOrDescendant $Right $Left)) {
        throw "Native release paths overlap: $LeftName=$Left, $RightName=$Right"
    }
}

function Assert-NoReparsePoints {
    param([string]$Root, [string]$Description)
    $rootItem = Get-Item -LiteralPath $Root -Force
    if (($rootItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "$Description is a reparse point: $Root"
    }
    foreach ($item in Get-ChildItem -LiteralPath $Root -Recurse -Force) {
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "$Description contains a reparse point: $($item.FullName)"
        }
    }
}

function Assert-File {
    param([string]$Path, [string]$Description)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Description was not found: $Path"
    }
    $item = Get-Item -LiteralPath $Path -Force
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "$Description is a reparse point: $Path"
    }
}

function Copy-Tree {
    param([string]$Source, [string]$Destination)
    Assert-NoReparsePoints $Source "native runtime"
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    & robocopy $Source $Destination /E /COPY:DAT /DCOPY:DAT /R:1 /W:1 /NFL /NDL /NJH /NJS | Out-Null
    if ($LASTEXITCODE -gt 7) {
        throw "robocopy failed while staging native runtime: $Source -> $Destination (exit $LASTEXITCODE)"
    }
}

function Get-FileIdentity {
    param([string]$Path, [string]$RelativePath, [string]$SourceName)
    $item = Get-Item -LiteralPath $Path
    return [ordered]@{
        path = $RelativePath.Replace("\", "/")
        size_bytes = $item.Length
        sha256 = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
        source_name = $SourceName
    }
}

function Assert-RuntimeManifest {
    param([string]$Root, [string]$ExpectedEngineCommit)

    $manifestPath = Join-Path $Root "manifest.json"
    Assert-File $manifestPath "native runtime manifest"
    $manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
    if ($manifest.schema_version -ne 1 -or $manifest.engine -ne "qwentts.cpp") {
        throw "Native runtime manifest must be qwentts.cpp schema version 1."
    }
    if ($manifest.architecture -ne "x64") {
        throw "Native runtime manifest architecture must be x64."
    }
    if ($manifest.qt_abi_version -ne 6) {
        throw "Native runtime manifest qt_abi_version must be 6."
    }
    if ([string]::IsNullOrWhiteSpace([string]$manifest.engine_commit) -or
        [string]::IsNullOrWhiteSpace([string]$manifest.backend)) {
        throw "Native runtime manifest must declare a non-empty engine commit and backend."
    }
    if ($ExpectedEngineCommit -and [string]$manifest.engine_commit -ne $ExpectedEngineCommit) {
        throw "Native runtime engine commit mismatch: expected $ExpectedEngineCommit, got $($manifest.engine_commit)"
    }
    $listed = @{}
    foreach ($entry in @($manifest.files)) {
        $relative = ([string]$entry.path).Replace("/", "\")
        if ([IO.Path]::IsPathRooted($relative) -or $relative.Contains("..")) {
            throw "Native runtime manifest contains an unsafe path: $($entry.path)"
        }
        $path = Join-Path $Root $relative
        Assert-File $path "native runtime manifest file"
        $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -ne ([string]$entry.sha256).ToLowerInvariant()) {
            throw "Native runtime hash mismatch: $($entry.path)"
        }
        $listed[$relative.ToLowerInvariant()] = $true
    }
    $qwen = Join-Path $Root "qwen.dll"
    Assert-File $qwen "native qwen.dll"
    if (-not $listed.ContainsKey("qwen.dll")) {
        throw "Native runtime manifest does not list qwen.dll."
    }
    foreach ($file in Get-ChildItem -LiteralPath $Root -Recurse -Force -File) {
        if ($file.Name -ieq "manifest.json") { continue }
        $relative = $file.FullName.Substring($Root.Length).TrimStart("\", "/")
        if (-not $listed.ContainsKey($relative.ToLowerInvariant())) {
            throw "Native runtime contains an unmanifested file: $relative"
        }
        if ($file.Name -match "(?i)(^|[-_.])(fake|mock|fixture|test)([-_.]|$)") {
            throw "Refusing to package a test/fake native runtime file: $relative"
        }
        if ($file.Extension -match "(?i)^\.(gguf|bin|safetensors|pt|pth|wav)$") {
            throw "Model or user audio must not be inside native runtime: $relative"
        }
    }
    return $manifest
}

$resolvedWorker = Resolve-InputPath $NativeWorkerExecutable
$resolvedRuntime = Resolve-InputPath $RuntimeRoot
$resolvedSave = Resolve-InputPath $SaveWavExecutable
$resolvedPlay = Resolve-InputPath $PlayExecutable
$resolvedOutput = if ([IO.Path]::IsPathRooted($OutputRoot)) {
    [IO.Path]::GetFullPath($OutputRoot)
}
else {
    [IO.Path]::GetFullPath((Join-Path $RepoRoot $OutputRoot))
}
$resolvedZip = if ($ZipPath) {
    if ([IO.Path]::IsPathRooted($ZipPath)) { [IO.Path]::GetFullPath($ZipPath) }
    else { [IO.Path]::GetFullPath((Join-Path $RepoRoot $ZipPath)) }
}
else { "$resolvedOutput.zip" }
$resolvedStaging = Join-Path (Split-Path -Parent $resolvedOutput) ("." + (Split-Path -Leaf $resolvedOutput) + ".assembling")
$resolvedPolicy = Resolve-InputPath $DependencyPolicy
Assert-SafeTarget $resolvedOutput
Assert-SafeTarget $resolvedZip
Assert-SafeTarget $resolvedStaging
Assert-File $resolvedWorker "native worker executable"
Assert-File $resolvedSave "qwen_tts_save_wav executable"
Assert-File $resolvedPlay "qwen_tts_play executable"
if (-not (Test-Path -LiteralPath $resolvedRuntime -PathType Container)) {
    throw "Native runtime directory was not found: $resolvedRuntime"
}
Assert-File $resolvedPolicy "native dependency policy"
Assert-NoReparsePoints $resolvedRuntime "native runtime"
foreach ($input in @(
    $resolvedRuntime,
    $resolvedWorker,
    $resolvedSave,
    $resolvedPlay,
    $resolvedPolicy
)) {
    Assert-NoPathOverlap "input" $input "output" $resolvedOutput
    Assert-NoPathOverlap "input" $input "staging" $resolvedStaging
    Assert-NoPathOverlap "input" $input "zip" $resolvedZip
}
Assert-NoPathOverlap "output" $resolvedOutput "staging" $resolvedStaging
Assert-NoPathOverlap "output" $resolvedOutput "zip" $resolvedZip
$zipTemp = "$resolvedZip.assembling"
$outputBackup = "$resolvedOutput.previous"
$zipBackup = "$resolvedZip.previous"
Assert-SafeTarget $zipTemp
Assert-SafeTarget $outputBackup
Assert-SafeTarget $zipBackup
foreach ($candidate in @($zipTemp, $outputBackup, $zipBackup)) {
    Assert-NoPathOverlap "temporary" $candidate "input" $resolvedRuntime
}
$runtimeManifest = Assert-RuntimeManifest $resolvedRuntime $EngineCommit

$examples = @()
foreach ($example in $ConfigExample) {
    $path = Resolve-InputPath $example
    Assert-File $path "native configuration example"
    $examples += $path
    Assert-NoPathOverlap "config" $path "output" $resolvedOutput
    Assert-NoPathOverlap "config" $path "staging" $resolvedStaging
    Assert-NoPathOverlap "config" $path "zip" $resolvedZip
}
$notices = @()
foreach ($notice in $NoticeFile) {
    $path = Resolve-InputPath $notice
    Assert-File $path "native third-party notice"
    $notices += $path
    Assert-NoPathOverlap "notice" $path "output" $resolvedOutput
    Assert-NoPathOverlap "notice" $path "staging" $resolvedStaging
    Assert-NoPathOverlap "notice" $path "zip" $resolvedZip
}
$instructions = Resolve-InputPath $LaunchInstructions
Assert-File $instructions "native package launch instructions"
Assert-NoPathOverlap "instructions" $instructions "output" $resolvedOutput
Assert-NoPathOverlap "instructions" $instructions "staging" $resolvedStaging
Assert-NoPathOverlap "instructions" $instructions "zip" $resolvedZip

$outputWasOwned = $false
if (Test-Path -LiteralPath $resolvedOutput) {
    if (-not $Clean) { throw "Native release output exists; pass -Clean after verifying it: $resolvedOutput" }
    if (-not (Test-Path -LiteralPath (Join-Path $resolvedOutput $ReleaseMarker) -PathType Leaf)) {
        throw "Refusing to clean native output without marker: $resolvedOutput"
    }
    $outputWasOwned = $true
}
if (Test-Path -LiteralPath $resolvedZip) {
    if (-not $Clean -or -not $outputWasOwned) {
        throw "Refusing to overwrite an existing native ZIP without an owned output directory: $resolvedZip"
    }
}
$zipIsCanonical = [IO.Path]::GetFullPath($resolvedZip).TrimEnd("\", "/") -ieq
    ([IO.Path]::GetFullPath("$resolvedOutput.zip").TrimEnd("\", "/"))
if ((Test-Path -LiteralPath $resolvedZip) -and -not $zipIsCanonical) {
    throw "Refusing to replace a custom ZIP without a dedicated ownership marker: $resolvedZip"
}
foreach ($candidate in @($zipTemp, $outputBackup, $zipBackup)) {
    if (Test-Path -LiteralPath $candidate) {
        throw "Refusing to overwrite an incomplete native publication artifact: $candidate"
    }
}
$parent = Split-Path -Parent $resolvedOutput
New-Item -ItemType Directory -Force -Path $parent | Out-Null
$staging = $resolvedStaging
if (Test-Path -LiteralPath $staging) {
    if (-not (Test-Path -LiteralPath (Join-Path $staging $ReleaseMarker) -PathType Leaf)) {
        throw "Refusing to clean native staging without marker: $staging"
    }
    Remove-Item -LiteralPath $staging -Recurse -Force
}

try {
    New-Item -ItemType Directory -Force -Path $staging | Out-Null
    [IO.File]::WriteAllText((Join-Path $staging $ReleaseMarker), "QwenTTSBridge native release output.`r`n")
    $bin = Join-Path $staging "bin"
    New-Item -ItemType Directory -Force -Path $bin | Out-Null
    Copy-Item -LiteralPath $resolvedWorker -Destination (Join-Path $bin "qwen_tts_native_worker.exe")
    Copy-Item -LiteralPath $resolvedSave -Destination (Join-Path $bin "qwen_tts_save_wav.exe")
    Copy-Item -LiteralPath $resolvedPlay -Destination (Join-Path $bin "qwen_tts_play.exe")
    Copy-Tree $resolvedRuntime (Join-Path $staging "runtime/qwentts")

    $configRoot = Join-Path $staging "config"
    New-Item -ItemType Directory -Force -Path $configRoot | Out-Null
    foreach ($example in $examples) {
        Copy-Item -LiteralPath $example -Destination (Join-Path $configRoot (Split-Path -Leaf $example))
    }
    Copy-Item -LiteralPath $resolvedPolicy -Destination (Join-Path $configRoot "native-dependency-policy.json")
    $docsRoot = Join-Path $staging "docs"
    New-Item -ItemType Directory -Force -Path $docsRoot | Out-Null
    Copy-Item -LiteralPath $instructions -Destination (Join-Path $docsRoot "native-portable-package.md")
    $licenseRoot = Join-Path $staging "licenses"
    New-Item -ItemType Directory -Force -Path $licenseRoot | Out-Null
    foreach ($notice in $notices) {
        Copy-Item -LiteralPath $notice -Destination (Join-Path $licenseRoot (Split-Path -Leaf $notice))
    }
    New-Item -ItemType Directory -Force -Path (Join-Path $staging "models") | Out-Null
    [IO.File]::WriteAllText((Join-Path $staging "models/.gitkeep"), "")

    $dependencyInventory = Join-Path $staging "dependency-inventory.json"
    $effectiveDynamicDependencies = @($runtimeManifest.dynamic_dependencies) + @($DynamicDependency)
    & $Python (Join-Path $RepoRoot "scripts/audit-native-dependencies.py") `
        --root $staging `
        --policy (Join-Path $staging "config/native-dependency-policy.json") `
        --entry "bin/qwen_tts_native_worker.exe" `
        --entry "bin/qwen_tts_save_wav.exe" `
        --entry "bin/qwen_tts_play.exe" `
        --entry "runtime/qwentts/qwen.dll" `
        $(foreach ($dependency in $effectiveDynamicDependencies) { "--dynamic"; $dependency }) `
        --require-export "qt_version" `
        --require-export "qt_last_error" `
        --require-export "qt_last_finish_reason" `
        --require-export "qt_init_default_params" `
        --require-export "qt_init" `
        --require-export "qt_free" `
        --require-export "qt_tts_default_params_ex" `
        --require-export "qt_synthesize" `
        --require-export "qt_audio_free" `
        --require-export "qt_num_codebooks" `
        --require-export "qt_n_speakers" `
        --require-export "qt_speaker_name" `
        --require-export "qt_duration_sec_to_tokens" `
        --require-export "qt_log_set" `
        --output $dependencyInventory
    if ($LASTEXITCODE -ne 0) { throw "Native dependency audit found unresolved imports." }

    $sourceRevision = (& git -C $RepoRoot rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0) { throw "Unable to record source Git revision." }
    $releaseFiles = @(Get-ChildItem -LiteralPath $staging -Recurse -Force -File | Where-Object {
        $_.Name -ne "release-manifest.json" -and
        $_.Name -ne "SHA256SUMS.txt" -and
        $_.Name -ne $ReleaseMarker
    } | Sort-Object FullName | ForEach-Object {
        $relative = $_.FullName.Substring($staging.Length).TrimStart("\", "/")
        Get-FileIdentity $_.FullName $relative $_.Name
    })
    $manifest = [ordered]@{
        native_release_manifest_schema_version = 1
        source_git_revision = $sourceRevision
        generated_at_utc = [DateTime]::UtcNow.ToString("o")
        engine = [ordered]@{
            name = "qwentts.cpp"
            commit = [string]$runtimeManifest.engine_commit
            abi_version = [int]$runtimeManifest.qt_abi_version
            backend = [string]$runtimeManifest.backend
            runtime_manifest = "runtime/qwentts/manifest.json"
        }
        package_contract = [ordered]@{
            python_required = $false
            models_included = $false
            mutable_paths = @("models/")
            entry_points = @("bin/qwen_tts_native_worker.exe", "bin/qwen_tts_save_wav.exe", "bin/qwen_tts_play.exe")
        }
        dependency_inventory = "dependency-inventory.json"
        files = $releaseFiles
    }
    $manifestPath = Join-Path $staging "release-manifest.json"
    $manifest | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
    $checksumLines = @()
    foreach ($file in Get-ChildItem -LiteralPath $staging -Recurse -Force -File | Where-Object { $_.Name -ne "SHA256SUMS.txt" -and $_.Name -ne $ReleaseMarker } | Sort-Object FullName) {
        $relative = $file.FullName.Substring($staging.Length).TrimStart("\", "/").Replace("\", "/")
        $hash = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        $checksumLines += "$hash  $relative"
    }
    [IO.File]::WriteAllLines((Join-Path $staging "SHA256SUMS.txt"), $checksumLines)
    & $Python (Join-Path $RepoRoot "scripts/verify-native-package.py") `
        --root $staging `
        --archive $zipTemp `
        --create `
        --extract-check
    if ($LASTEXITCODE -ne 0) {
        throw "Native release directory or ZIP verification failed."
    }

    $movedOutputToBackup = $false
    $movedZipToBackup = $false
    $publishedOutput = $false
    $publishedZip = $false
    try {
        if ($outputWasOwned) {
            Move-Item -LiteralPath $resolvedOutput -Destination $outputBackup
            $movedOutputToBackup = $true
        }
        if (Test-Path -LiteralPath $resolvedZip) {
            Move-Item -LiteralPath $resolvedZip -Destination $zipBackup
            $movedZipToBackup = $true
        }
        Move-Item -LiteralPath $staging -Destination $resolvedOutput
        $publishedOutput = $true
        Move-Item -LiteralPath $zipTemp -Destination $resolvedZip
        $publishedZip = $true
        if ($movedOutputToBackup) { Remove-Item -LiteralPath $outputBackup -Recurse -Force }
        if ($movedZipToBackup) { Remove-Item -LiteralPath $zipBackup -Force }
    }
    catch {
        if ($publishedZip -and (Test-Path -LiteralPath $resolvedZip)) {
            Remove-Item -LiteralPath $resolvedZip -Force
        }
        if ($publishedOutput -and (Test-Path -LiteralPath $resolvedOutput)) {
            Remove-Item -LiteralPath $resolvedOutput -Recurse -Force
        }
        if ($movedZipToBackup -and (Test-Path -LiteralPath $zipBackup)) {
            Move-Item -LiteralPath $zipBackup -Destination $resolvedZip
        }
        if ($movedOutputToBackup -and (Test-Path -LiteralPath $outputBackup)) {
            Move-Item -LiteralPath $outputBackup -Destination $resolvedOutput
        }
        throw
    }
}
catch {
    if (Test-Path -LiteralPath $staging) {
        if (Test-Path -LiteralPath (Join-Path $staging $ReleaseMarker) -PathType Leaf) {
            Remove-Item -LiteralPath $staging -Recurse -Force
        }
    }
    if (Test-Path -LiteralPath $zipTemp) {
        Remove-Item -LiteralPath $zipTemp -Force
    }
    throw
}

Write-Host "Native release assembled: $resolvedOutput"
Write-Host "Native ZIP: $resolvedZip"
