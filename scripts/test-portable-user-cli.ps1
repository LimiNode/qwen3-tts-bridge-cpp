param(
    [string]$PackageRoot = "dist/QwenTTSBridge-release",
    [string]$OutputRoot = ".tmp/portable-user-cli-acceptance",
    [string]$Python = "python",
    [switch]$Clean
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$TestMarker = ".qtb-portable-cli-test-root"

function Resolve-PathFromRepo {
    param([string]$Path)

    if ([IO.Path]::IsPathRooted($Path)) {
        return [IO.Path]::GetFullPath($Path)
    }
    return [IO.Path]::GetFullPath((Join-Path $RepoRoot $Path))
}

function Copy-Tree {
    param([string]$Source, [string]$Destination)

    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    & robocopy $Source $Destination /E /COPY:DAT /DCOPY:DAT /R:1 /W:1 /NFL /NDL /NJH /NJS | Out-Null
    if ($LASTEXITCODE -gt 7) {
        throw "robocopy failed: $Source -> $Destination (exit $LASTEXITCODE)"
    }
}

function Invoke-Cli {
    param([string[]]$Arguments, [string]$WorkingDirectory)

    $Previous = Get-Location
    try {
        Set-Location $WorkingDirectory
        $Output = & $script:Launcher @Arguments 2>&1
        $ExitCode = $LASTEXITCODE
    }
    finally {
        Set-Location $Previous
    }
    return [pscustomobject]@{
        exit_code = $ExitCode
        output = @($Output) -join "`n"
    }
}

function Write-TestModel {
    param([string]$Path)

    New-Item -ItemType Directory -Force -Path (Join-Path $Path "speech_tokenizer") | Out-Null
    $Config = [ordered]@{
        model_type = "qwen3_tts"
        tts_model_type = "voice_design"
        tts_model_size = "1b7"
    } | ConvertTo-Json
    [IO.File]::WriteAllText(
        (Join-Path $Path "config.json"),
        $Config,
        [Text.UTF8Encoding]::new($false)
    )
    foreach ($Relative in @(
        "generation_config.json",
        "merges.txt",
        "model.safetensors",
        "preprocessor_config.json",
        "tokenizer_config.json",
        "vocab.json",
        "speech_tokenizer/config.json",
        "speech_tokenizer/model.safetensors",
        "speech_tokenizer/preprocessor_config.json"
    )) {
        $Target = Join-Path $Path $Relative
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Target) | Out-Null
        [IO.File]::WriteAllBytes($Target, [byte[]](1, 2, 3, 4))
    }
}

$ResolvedPackage = Resolve-PathFromRepo $PackageRoot
$ResolvedOutput = Resolve-PathFromRepo $OutputRoot
if (-not (Test-Path -LiteralPath (Join-Path $ResolvedPackage ".qtb-portable-release-root") -PathType Leaf)) {
    throw "Portable release marker was not found: $ResolvedPackage"
}
if (Test-Path -LiteralPath $ResolvedOutput) {
    if (-not $Clean) {
        throw "CLI acceptance output exists; pass -Clean after verifying it: $ResolvedOutput"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $ResolvedOutput $TestMarker) -PathType Leaf)) {
        throw "Refusing to clean CLI acceptance output without marker: $ResolvedOutput"
    }
    Remove-Item -LiteralPath $ResolvedOutput -Recurse -Force
}

New-Item -ItemType Directory -Force -Path $ResolvedOutput | Out-Null
[IO.File]::WriteAllText(
    (Join-Path $ResolvedOutput $TestMarker),
    "QwenTTSBridge portable CLI acceptance output.`r`n",
    [Text.UTF8Encoding]::new($false)
)

$Relocated = Join-Path $ResolvedOutput "перенесённый пакет"
Copy-Tree -Source $ResolvedPackage -Destination $Relocated
$script:Launcher = Join-Path $Relocated "qwen-tts.cmd"
$ManifestPath = Join-Path $Relocated "release-manifest.json"
if (-not (Test-Path -LiteralPath $script:Launcher -PathType Leaf)) {
    throw "Relocated qwen-tts.cmd was not found: $script:Launcher"
}

$Manifest = Get-Content -Raw -Encoding UTF8 -LiteralPath $ManifestPath | ConvertFrom-Json
if ($Manifest.release_manifest_schema_version -ne 1) {
    throw "Portable release manifest schema is invalid."
}
foreach ($Entry in $Manifest.release_files) {
    $File = Join-Path $Relocated ([string]$Entry.path).Replace("/", "\")
    if (-not (Test-Path -LiteralPath $File -PathType Leaf)) {
        throw "Release manifest file is missing: $($Entry.path)"
    }
    $ActualHash = (Get-FileHash -LiteralPath $File -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($ActualHash -ne [string]$Entry.sha256) {
        throw "Release manifest hash mismatch: $($Entry.path)"
    }
}

$Model = Join-Path $Relocated "models/Qwen3-TTS-12Hz-1.7B-VoiceDesign"
Write-TestModel $Model
$UnrelatedCwd = Join-Path $ResolvedOutput "unrelated cwd"
New-Item -ItemType Directory -Force -Path $UnrelatedCwd | Out-Null
$ResultRoot = Join-Path $ResolvedOutput "результаты"
New-Item -ItemType Directory -Force -Path $ResultRoot | Out-Null
$Wav = Join-Path $ResultRoot "русский голос.wav"
$Receipt = Join-Path $ResultRoot "русский голос.json"

$PreviousLocalAppData = $env:LOCALAPPDATA
$PreviousHfHubCache = $env:HF_HUB_CACHE
try {
    $env:LOCALAPPDATA = Join-Path $ResolvedOutput "empty-user-config"
    $env:HF_HUB_CACHE = Join-Path $ResolvedOutput "empty-hf-cache"

    $List = Invoke-Cli -WorkingDirectory $UnrelatedCwd -Arguments @("models", "list", "--json")
    if ($List.exit_code -ne 0 -or $List.output -notmatch '"source": "portable"') {
        throw "Relocated models list failed: $($List.output)"
    }

    $Design = Invoke-Cli -WorkingDirectory $UnrelatedCwd -Arguments @(
        "design",
        "--text", "Привет! Это проверка переносимого CLI.",
        "--instruction", "Спокойный женский голос.",
        "--out", $Wav,
        "--result-json", $Receipt,
        "--acceptance-mock-worker"
    )
    if ($Design.exit_code -ne 0) {
        throw "Relocated qwen-tts design failed: $($Design.output)"
    }

    $MissingExe = Join-Path $ResolvedOutput "missing-save-wav.exe"
    $FailClosed = Invoke-Cli -WorkingDirectory $UnrelatedCwd -Arguments @(
        "design",
        "--text", "Не запускать fallback.",
        "--instruction", "Test",
        "--out", (Join-Path $ResultRoot "must-not-exist.wav"),
        "--save-wav-executable", $MissingExe,
        "--acceptance-mock-worker"
    )
    if ($FailClosed.exit_code -eq 0 -or $FailClosed.output -notmatch "explicit.*was not found") {
        throw "Explicit runtime selection did not fail closed: $($FailClosed.output)"
    }
}
finally {
    $env:LOCALAPPDATA = $PreviousLocalAppData
    $env:HF_HUB_CACHE = $PreviousHfHubCache
}

& $Python (Join-Path $RepoRoot "tests/python/verify_wav.py") $Wav `
    --sample-rate 24000 --channels 1 --bits-per-sample 16 --min-data-bytes 1
if ($LASTEXITCODE -ne 0) {
    throw "Relocated CLI WAV verification failed."
}
$ReceiptValue = Get-Content -Raw -Encoding UTF8 -LiteralPath $Receipt | ConvertFrom-Json
if (
    $ReceiptValue.schema_version -ne 1 -or
    $ReceiptValue.terminal_state -ne "completed" -or
    $ReceiptValue.audio_bytes -le 0
) {
    throw "Relocated CLI receipt is invalid: $Receipt"
}

$CombinedEvidence = @($List.output, $Design.output, $FailClosed.output, (Get-Content -Raw $ManifestPath)) -join "`n"
if ($CombinedEvidence -match [regex]::Escape($RepoRoot)) {
    throw "Relocated CLI evidence leaked the repository path."
}

Write-Host "portable qwen-tts CLI acceptance passed: $Relocated"
Write-Host "WAV: $Wav"
Write-Host "Receipt: $Receipt"
