param(
    [string]$PackageRoot = "dist/QwenTTSBridge-release",
    [string]$OutputRoot = ".tmp/portable-user-cli-acceptance",
    [string]$Python = "python",
    [ValidateRange(1, 600)]
    [int]$CommandTimeoutSeconds = 120,
    [switch]$Clean
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$TestMarker = ".qtb-portable-cli-test-root"
$Invocations = [Collections.Generic.List[object]]::new()

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

function Get-Sha256Hex {
    param([Parameter(Mandatory = $true)][string]$Path)

    $HashAlgorithm = [Security.Cryptography.SHA256]::Create()
    $Stream = $null
    try {
        $Stream = [IO.File]::OpenRead($Path)
        return ([BitConverter]::ToString($HashAlgorithm.ComputeHash($Stream))).Replace("-", "").ToLowerInvariant()
    }
    finally {
        if ($Stream) { $Stream.Dispose() }
        $HashAlgorithm.Dispose()
    }
}

function Invoke-Cli {
    param([string[]]$Arguments, [string]$WorkingDirectory)

    $Previous = Get-Location
    $StdoutPath = Join-Path $ResolvedOutput (".invoke-" + [guid]::NewGuid().ToString("N") + ".stdout")
    $StderrPath = Join-Path $ResolvedOutput (".invoke-" + [guid]::NewGuid().ToString("N") + ".stderr")
    $ExitCode = $null
    $TimedOut = $false
    try {
        Set-Location $WorkingDirectory
        # Start the launcher and redirect both streams at the process level.
        # PowerShell otherwise materializes native stderr as NativeCommandError
        # when the caller has $ErrorActionPreference=Stop, even for exit 0.
        $ProcessArguments = foreach ($Argument in $Arguments) {
            $Escaped = [string]$Argument
            if ($Escaped -match '[\s"&<>^|()]' -or $Escaped.Length -eq 0) {
                '"' + $Escaped.Replace('"', '\"') + '"'
            } else {
                $Escaped
            }
        }
        $Process = Start-Process -FilePath $script:Launcher `
            -ArgumentList $ProcessArguments `
            -WorkingDirectory $WorkingDirectory `
            -RedirectStandardOutput $StdoutPath `
            -RedirectStandardError $StderrPath `
            -NoNewWindow -PassThru
        # Windows PowerShell 5.1 must retain the native process handle before
        # waiting; otherwise ExitCode can remain null after a fast child exits.
        $null = $Process.Handle
        if (-not $Process.WaitForExit($CommandTimeoutSeconds * 1000)) {
            $TimedOut = $true
            # Kill the launcher and its descendants, not just cmd.exe. The
            # external watchdog must also work when a worker never exits.
            & taskkill.exe /PID $Process.Id /T /F | Out-Null
            throw "CLI watchdog timeout after $CommandTimeoutSeconds seconds; logs: $StdoutPath, $StderrPath"
        }
        $Process.WaitForExit()
        $ExitCode = $Process.ExitCode
        $Stdout = if (Test-Path -LiteralPath $StdoutPath) {
            Get-Content -Raw -Encoding UTF8 -LiteralPath $StdoutPath
        } else { "" }
        $Stderr = if (Test-Path -LiteralPath $StderrPath) {
            Get-Content -Raw -Encoding UTF8 -LiteralPath $StderrPath
        } else { "" }
    }
    finally {
        Set-Location $Previous
        $Invocations.Add([ordered]@{
            arguments = $Arguments
            stdout = [IO.Path]::GetFileName($StdoutPath)
            stderr = [IO.Path]::GetFileName($StderrPath)
            exit_code = $ExitCode
            timed_out = $TimedOut
        })
    }
    return [pscustomobject]@{
        exit_code = $ExitCode
        stdout = $Stdout
        stderr = $Stderr
        output = $Stdout + $Stderr
    }
}

function Write-TestModel {
    param(
        [string]$Path,
        [string]$ModelType = "voice_design",
        [string]$ModelSize = "1b7"
    )

    New-Item -ItemType Directory -Force -Path (Join-Path $Path "speech_tokenizer") | Out-Null
    $Config = [ordered]@{
        model_type = "qwen3_tts"
        tts_model_type = $ModelType
        tts_model_size = $ModelSize
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

function Write-TestReferenceWav {
    param([string]$Path)

    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Path) | Out-Null
    $FrameCount = 72000
    $DataBytes = $FrameCount * 2
    $Stream = [IO.File]::Create($Path)
    $Writer = [IO.BinaryWriter]::new($Stream, [Text.Encoding]::ASCII, $false)
    try {
        $Writer.Write([Text.Encoding]::ASCII.GetBytes("RIFF"))
        $Writer.Write([int](36 + $DataBytes))
        $Writer.Write([Text.Encoding]::ASCII.GetBytes("WAVEfmt "))
        $Writer.Write([int]16)
        $Writer.Write([int16]1)
        $Writer.Write([int16]1)
        $Writer.Write([int]24000)
        $Writer.Write([int]48000)
        $Writer.Write([int16]2)
        $Writer.Write([int16]16)
        $Writer.Write([Text.Encoding]::ASCII.GetBytes("data"))
        $Writer.Write([int]$DataBytes)
        for ($Index = 0; $Index -lt $FrameCount; $Index++) {
            if ($Index % 2 -eq 0) {
                $Writer.Write([int16]8192)
            }
            else {
                $Writer.Write([int16]-8192)
            }
        }
    }
    finally {
        $Writer.Dispose()
    }
}

$ResolvedPackage = Resolve-PathFromRepo $PackageRoot
$ResolvedOutput = Resolve-PathFromRepo $OutputRoot
if ($ResolvedOutput.TrimEnd("\", "/") -eq $RepoRoot -or
    $ResolvedOutput.TrimEnd("\", "/") -eq [IO.Path]::GetPathRoot($ResolvedOutput).TrimEnd("\", "/") -or
    $ResolvedPackage.StartsWith($ResolvedOutput.TrimEnd("\", "/") + "\", [StringComparison]::OrdinalIgnoreCase) -or
    $ResolvedPackage -eq $ResolvedOutput) {
    throw "Unsafe or overlapping acceptance output: $ResolvedOutput"
}
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

$AcceptancePassed = $false
$FailureReason = "Acceptance did not reach the final checks."
$StartedAt = [DateTime]::UtcNow.ToString("o")
$ManifestPath = $null
$WorkerOriginProbe = $null
try {
$Relocated = Join-Path $ResolvedOutput "перенесённый пакет"
Copy-Tree -Source $ResolvedPackage -Destination $Relocated
$RelocatedIsUnderRepo = [IO.Path]::GetFullPath($Relocated).StartsWith(
    [IO.Path]::GetFullPath($RepoRoot).TrimEnd("\") + "\",
    [StringComparison]::OrdinalIgnoreCase
)
$script:Launcher = Join-Path $Relocated "qwen-tts.cmd"
$ManifestPath = Join-Path $Relocated "release-manifest.json"
if (-not (Test-Path -LiteralPath $script:Launcher -PathType Leaf)) {
    throw "Relocated qwen-tts.cmd was not found: $script:Launcher"
}

$Manifest = Get-Content -Raw -Encoding UTF8 -LiteralPath $ManifestPath | ConvertFrom-Json
if ($Manifest.release_manifest_schema_version -ne 1) {
    throw "Portable release manifest schema is invalid."
}
if (-not (Test-Path -LiteralPath (Join-Path $Relocated "bin/qwen_tts_play.exe") -PathType Leaf)) {
    throw "Portable playback executable was not packaged."
}
$PortableWorkerRoot = Join-Path $Relocated "worker-python"
$PortableWorkerPython = Join-Path $PortableWorkerRoot "python/python.exe"
if (-not (Test-Path -LiteralPath $PortableWorkerPython -PathType Leaf)) {
    throw "Portable worker Python executable was not packaged."
}
$PreviousPythonHome = $env:PYTHONHOME
$PreviousPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONHOME = Join-Path $PortableWorkerRoot "python"
    $env:PYTHONPATH = Join-Path $PortableWorkerRoot "python/Lib/site-packages"
    $WorkerOriginJson = (& $PortableWorkerPython -B -P -s -c `
        "import json, qwen_tts_bridge_worker, sys; print(json.dumps({'module': qwen_tts_bridge_worker.__file__, 'executable': sys.executable, 'python_version': sys.version}, ensure_ascii=True))") -join ""
    if ($LASTEXITCODE -ne 0) {
        throw "Portable worker import probe failed with exit code $LASTEXITCODE."
    }
    try {
        $WorkerOriginProbe = $WorkerOriginJson | ConvertFrom-Json
    }
    catch {
        throw "Portable worker import probe returned invalid JSON: $WorkerOriginJson"
    }
    $ExpectedWorkerPrefix = [IO.Path]::GetFullPath(
        (Join-Path $PortableWorkerRoot "python/Lib/site-packages")
    ).TrimEnd("\")
    $WorkerModuleOrigin = [IO.Path]::GetFullPath([string]$WorkerOriginProbe.module)
    $WorkerExecutableOrigin = [IO.Path]::GetFullPath([string]$WorkerOriginProbe.executable)
    $WorkerOrigin = "$WorkerModuleOrigin`n$WorkerExecutableOrigin"
    if (
        -not $WorkerModuleOrigin.StartsWith(
            $ExpectedWorkerPrefix + "\",
            [StringComparison]::OrdinalIgnoreCase
        ) -or
        -not $WorkerExecutableOrigin.Equals(
            [IO.Path]::GetFullPath($PortableWorkerPython),
            [StringComparison]::OrdinalIgnoreCase
        ) -or
        (-not $RelocatedIsUnderRepo -and
            $WorkerOrigin -match [regex]::Escape($RepoRoot))
    ) {
        throw "Portable worker module origin escaped the relocated package: $WorkerOrigin"
    }
}
finally {
    $env:PYTHONHOME = $PreviousPythonHome
    $env:PYTHONPATH = $PreviousPythonPath
}
foreach ($Entry in $Manifest.release_files) {
    $File = Join-Path $Relocated ([string]$Entry.path).Replace("/", "\")
    if (-not (Test-Path -LiteralPath $File -PathType Leaf)) {
        throw "Release manifest file is missing: $($Entry.path)"
    }
    $ActualHash = Get-Sha256Hex -Path $File
    if ($ActualHash -ne [string]$Entry.sha256) {
        throw "Release manifest hash mismatch: $($Entry.path)"
    }
}

$Model = Join-Path $Relocated "models/Qwen3-TTS-12Hz-1.7B-VoiceDesign"
Write-TestModel $Model
$BaseModel = Join-Path $Relocated "models/Qwen3-TTS-12Hz-1.7B-Base"
Write-TestModel -Path $BaseModel -ModelType "base"
foreach ($Family in @(
    @{ name = "0.6B-Base"; type = "base"; size = "0b6" },
    @{ name = "0.6B-CustomVoice"; type = "custom_voice"; size = "0b6" },
    @{ name = "1.7B-CustomVoice"; type = "custom_voice"; size = "1b7" }
)) {
    Write-TestModel -Path (Join-Path $Relocated ("models/Qwen3-TTS-12Hz-" + $Family.name)) `
        -ModelType $Family.type -ModelSize $Family.size
}
$UnrelatedCwd = Join-Path $ResolvedOutput "unrelated cwd"
New-Item -ItemType Directory -Force -Path $UnrelatedCwd | Out-Null
$ResultRoot = Join-Path $ResolvedOutput "результаты"
New-Item -ItemType Directory -Force -Path $ResultRoot | Out-Null
$ReferenceWav = Join-Path $ResultRoot "reference voice.wav"
$SynthWav = Join-Path $ResultRoot "registered voice.wav"
$SynthReceipt = Join-Path $ResultRoot "registered voice.json"
Write-TestReferenceWav $ReferenceWav
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

    $ModelVerify = Invoke-Cli -WorkingDirectory $UnrelatedCwd -Arguments @(
        "models", "verify", "voice-design"
    )
    if ($ModelVerify.exit_code -ne 0) {
        throw "Relocated models verify failed: $($ModelVerify.output)"
    }

    foreach ($InvalidArguments in @(@("invalid-command"), @("design"))) {
        $Invalid = Invoke-Cli -WorkingDirectory $UnrelatedCwd -Arguments $InvalidArguments
        if ($Invalid.exit_code -eq 0 -or $Invalid.stderr -notmatch "error:") {
            throw "Invalid CLI command/arguments did not fail: $($Invalid.output)"
        }
    }

    $VoicesList = Invoke-Cli -WorkingDirectory $UnrelatedCwd -Arguments @(
        "voices", "list", "--json"
    )
    if ($VoicesList.exit_code -ne 0 -or $VoicesList.output.Trim() -ne "[]") {
        throw "Relocated voices list failed: $($VoicesList.output)"
    }

    $VoiceAdd = Invoke-Cli -WorkingDirectory $UnrelatedCwd -Arguments @(
        "voices", "add", "--id", "portable-test", "--wav", $ReferenceWav,
        "--text", "Portable reference text."
    )
    if ($VoiceAdd.exit_code -ne 0) {
        throw "Relocated voices add failed: $($VoiceAdd.output)"
    }

    $VoiceShow = Invoke-Cli -WorkingDirectory $UnrelatedCwd -Arguments @(
        "voices", "show", "portable-test", "--json"
    )
    if ($VoiceShow.exit_code -ne 0 -or $VoiceShow.output -notmatch 'portable-test') {
        throw "Relocated voices show failed: $($VoiceShow.output)"
    }

    $VoiceVerify = Invoke-Cli -WorkingDirectory $UnrelatedCwd -Arguments @(
        "voices", "verify", "portable-test", "--backend", "python"
    )
    if (
        $VoiceVerify.exit_code -ne 0 -or
        $VoiceVerify.output -notmatch '"status": "compatible"'
    ) {
        throw "Relocated voices verify failed: $($VoiceVerify.output)"
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
    if ($Design.output -match "qtb_metric") {
        throw "Quiet design output leaked worker metrics: $($Design.output)"
    }

    $Synth = Invoke-Cli -WorkingDirectory $UnrelatedCwd -Arguments @(
        "synth",
        "--voice-id", "portable-test",
        "--text", "Portable registered voice synthesis.",
        "--language", "English",
        "--out", $SynthWav,
        "--result-json", $SynthReceipt,
        "--acceptance-mock-worker"
    )
    if ($Synth.exit_code -ne 0) {
        throw "Relocated qwen-tts synth failed: $($Synth.output)"
    }
    if ($Synth.output -match "qtb_metric") {
        throw "Quiet synth output leaked worker metrics: $($Synth.output)"
    }

    $Play = Invoke-Cli -WorkingDirectory $UnrelatedCwd -Arguments @(
        "play",
        "--voice-id", "portable-test",
        "--text", "Portable registered voice playback.",
        "--language", "English",
        "--acceptance-mock-worker",
        "--acceptance-mock-playback"
    )
    if ($Play.exit_code -ne 0) {
        throw "Relocated qwen-tts play failed: $($Play.output)"
    }
    if ($null -ne $Play.output -and $Play.output.Trim().Length -ne 0) {
        throw "Quiet play output was not silent: $($Play.output)"
    }

    $CaptureWav = Join-Path $ResultRoot "play capture.wav"
    $Capture = Invoke-Cli -WorkingDirectory $UnrelatedCwd -Arguments @(
        "play", "--model-family", "custom-1.7b", "--speaker", "ryan",
        "--text", "Portable playback capture.", "--out", $CaptureWav,
        "--acceptance-mock-worker", "--acceptance-mock-playback"
    )
    if ($Capture.exit_code -ne 0) { throw "play --out failed: $($Capture.output)" }

    $Created = Invoke-Cli -WorkingDirectory $UnrelatedCwd -Arguments @(
        "voices", "create", "--id", "portable-created",
        "--sample-text", "A managed reference for reuse.",
        "--instruction", "A calm clear voice.", "--language", "English",
        "--acceptance-mock-worker"
    )
    if ($Created.exit_code -ne 0) { throw "voices create failed: $($Created.output)" }
    $CreatedValue = $Created.stdout | ConvertFrom-Json
    if ($CreatedValue.status -ne "created" -or
        $CreatedValue.voice.provenance.operation -ne "voices create" -or
        $CreatedValue.voice.provenance.reference_text -cne "A managed reference for reuse." -or
        $CreatedValue.voice.source_reference_audio_path) {
        throw "voices create returned invalid managed provenance."
    }
    $CreatedVerify = Invoke-Cli -WorkingDirectory $UnrelatedCwd -Arguments @(
        "voices", "verify", "portable-created", "--backend", "python"
    )
    if ($CreatedVerify.exit_code -ne 0 -or $CreatedVerify.stdout -notmatch '"status": "compatible"') {
        throw "Created voice verification failed: $($CreatedVerify.output)"
    }
    $CreatedSynth = Invoke-Cli -WorkingDirectory $UnrelatedCwd -Arguments @(
        "synth", "--voice-id", "portable-created", "--text", "Reuse the managed voice.",
        "--out", (Join-Path $ResultRoot "created synth.wav"),
        "--result-json", (Join-Path $ResultRoot "created synth.json"), "--acceptance-mock-worker"
    )
    if ($CreatedSynth.exit_code -ne 0) { throw "Created voice synthesis failed: $($CreatedSynth.output)" }

    foreach ($FamilyCase in @(
        @{ family = "base-0.6b"; voice = @("--voice-id", "portable-test") },
        @{ family = "custom-0.6b"; voice = @("--speaker", "ryan") },
        @{ family = "custom-1.7b"; voice = @("--speaker", "serena") },
        @{ family = "voice-design"; voice = @("--instruction", "A calm clear voice.") }
    )) {
        $FamilySynth = Invoke-Cli -WorkingDirectory $UnrelatedCwd -Arguments (@(
            "synth", "--model-family", $FamilyCase.family, "--text", "Explicit family routing.",
            "--out", (Join-Path $ResultRoot ($FamilyCase.family + ".wav")),
            "--result-json", (Join-Path $ResultRoot ($FamilyCase.family + ".json")),
            "--acceptance-mock-worker"
        ) + $FamilyCase.voice)
        if ($FamilySynth.exit_code -ne 0) {
            throw "Family $($FamilyCase.family) failed: $($FamilySynth.output)"
        }
    }

    foreach ($InvalidVoice in @(
        @("--model-family", "custom-0.6b", "--voice-id", "portable-test"),
        @("--model-family", "base-1.7b", "--speaker", "ryan"),
        @("--model-family", "voice-design", "--speaker", "ryan")
    )) {
        $InvalidFamily = Invoke-Cli -WorkingDirectory $UnrelatedCwd -Arguments (@(
            "synth", "--text", "Invalid voice selection.",
            "--out", (Join-Path $ResultRoot "must-not-publish.wav"), "--acceptance-mock-worker"
        ) + $InvalidVoice)
        if ($InvalidFamily.exit_code -eq 0 -or
            (Test-Path -LiteralPath (Join-Path $ResultRoot "must-not-publish.wav"))) {
            throw "Invalid family/voice combination did not fail closed."
        }
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
    if ($FailClosed.output -match "NativeCommandError") {
        throw "Native stderr was converted into a PowerShell error record: $($FailClosed.output)"
    }

    $ProbeOutput = Join-Path $ResolvedOutput "argument-probe.json"
    $ProbeScript = Join-Path $ResolvedOutput "argument-probe.py"
    [IO.File]::WriteAllText(
        $ProbeScript,
        @'
import json
import os
import sys
import time

if "--hang" in sys.argv[1:]:
    time.sleep(30)

with open(os.environ["QTB_ARGUMENT_PROBE_OUTPUT"], "w", encoding="utf-8") as output:
    json.dump(sys.argv[1:], output, ensure_ascii=False)
print("probe diagnostic", file=sys.stderr)
if "--fail" in sys.argv[1:]:
    raise SystemExit(19)
'@,
        [Text.UTF8Encoding]::new($false)
    )
    $ProbeLauncher = Join-Path $ResolvedOutput "argument-probe.cmd"
    # Keep the batch file ASCII without encoding the Unicode output path.
    $ProbeLauncherText = '@echo off' + "`r`n" +
        '"%QTB_ARGUMENT_PROBE_PYTHON%" "%~dp0argument-probe.py" %*' + "`r`n"
    [IO.File]::WriteAllText(
        $ProbeLauncher,
        $ProbeLauncherText,
        [Text.ASCIIEncoding]::new()
    )
    $PreviousProbeOutput = $env:QTB_ARGUMENT_PROBE_OUTPUT
    $PreviousProbePython = $env:QTB_ARGUMENT_PROBE_PYTHON
    $PreviousLauncher = $script:Launcher
    try {
        $env:QTB_ARGUMENT_PROBE_OUTPUT = $ProbeOutput
        $env:QTB_ARGUMENT_PROBE_PYTHON = $Python
        $script:Launcher = $ProbeLauncher
        $ProbeArguments = @(
            "spaced value",
            "Русский `"текст`" \path & tail"
        )
        $Probe = Invoke-Cli -WorkingDirectory $UnrelatedCwd -Arguments $ProbeArguments
        if ($Probe.exit_code -ne 0 -or $Probe.stderr -notmatch "probe diagnostic") {
            throw "Argument probe success case failed: $($Probe.output)"
        }
        # Windows PowerShell 5.1 does not enumerate a root JSON array in the
        # pipeline; @(... | ConvertFrom-Json) would wrap it in a second array.
        $ObservedArguments = Get-Content -Raw -Encoding UTF8 -LiteralPath $ProbeOutput | ConvertFrom-Json
        if (
            $ObservedArguments.Count -ne $ProbeArguments.Count -or
            $ObservedArguments[0] -cne $ProbeArguments[0] -or
            $ObservedArguments[1] -cne $ProbeArguments[1]
        ) {
            throw "Argument probe changed child arguments: $($ObservedArguments | ConvertTo-Json -Compress)"
        }

        $ProbeFailure = Invoke-Cli -WorkingDirectory $UnrelatedCwd -Arguments @("--fail")
        if ($ProbeFailure.exit_code -ne 19 -or $ProbeFailure.stderr -notmatch "probe diagnostic") {
            throw "Argument probe failure case did not preserve stderr/exit code: $($ProbeFailure.output)"
        }

        $PreviousTimeout = $CommandTimeoutSeconds
        try {
            $CommandTimeoutSeconds = 1
            $WatchdogObserved = $false
            try {
                Invoke-Cli -WorkingDirectory $UnrelatedCwd -Arguments @("--hang") | Out-Null
            }
            catch {
                if ($_.Exception.Message -notmatch "CLI watchdog timeout") { throw }
                $WatchdogObserved = $true
            }
            if (-not $WatchdogObserved) { throw "CLI watchdog did not terminate the hanging child." }
        }
        finally { $CommandTimeoutSeconds = $PreviousTimeout }
    }
    finally {
        $script:Launcher = $PreviousLauncher
        $env:QTB_ARGUMENT_PROBE_OUTPUT = $PreviousProbeOutput
        $env:QTB_ARGUMENT_PROBE_PYTHON = $PreviousProbePython
    }
}
finally {
    $env:LOCALAPPDATA = $PreviousLocalAppData
    $env:HF_HUB_CACHE = $PreviousHfHubCache
}

foreach ($OutputWav in Get-ChildItem -LiteralPath $ResultRoot -Filter *.wav) {
& $Python (Join-Path $RepoRoot "tests/python/verify_wav.py") $OutputWav.FullName `
    --sample-rate 24000 --channels 1 --bits-per-sample 16 --min-data-bytes 1
if ($LASTEXITCODE -ne 0) {
    throw "Relocated CLI WAV verification failed."
}
}
foreach ($OutputReceipt in Get-ChildItem -LiteralPath $ResultRoot -Filter *.json) {
$ReceiptValue = Get-Content -Raw -Encoding UTF8 -LiteralPath $OutputReceipt.FullName | ConvertFrom-Json
if (
    $ReceiptValue.schema_version -ne 1 -or
    $ReceiptValue.terminal_state -ne "completed" -or
    $ReceiptValue.completion_metadata_received -ne $true -or
    $ReceiptValue.generation_trace_available -ne $true -or
    $ReceiptValue.termination_reason -ne "eos" -or
    $ReceiptValue.hit_eos -ne $true -or
    $ReceiptValue.hit_max_seq_len -ne $false -or
    $ReceiptValue.hit_max_new_tokens -ne $false -or
    $ReceiptValue.audio_bytes -le 0
) {
    throw "Relocated CLI receipt is invalid: $($OutputReceipt.FullName)"
}
}

$CombinedEvidence = @(
    $List.output,
    $ModelVerify.output,
    $VoicesList.output,
    $VoiceAdd.output,
    $VoiceVerify.output,
    $Design.output,
    $Synth.output,
    $Play.output,
    $FailClosed.output,
    $WorkerOrigin,
    (Get-Content -Raw $ManifestPath)
) -join "`n"
if (-not $RelocatedIsUnderRepo -and
    $CombinedEvidence -match [regex]::Escape($RepoRoot)) {
    throw "Relocated CLI evidence leaked the repository path."
}

Write-Host "portable qwen-tts CLI acceptance passed: $Relocated"
Write-Host "PowerShell: $($PSVersionTable.PSVersion); manifest hashes verified: $($Manifest.release_files.Count)"
Write-Host "Worker origin: $WorkerModuleOrigin"
Write-Host "Argument probe: exact UTF-8 arguments PASS; stderr/exit 19 PASS"
Write-Host "WAV: $Wav"
Write-Host "Receipt: $Receipt"
$AcceptancePassed = $true
}
catch {
    $FailureReason = $_.Exception.Message
    # Write a minimal receipt before rethrowing. This keeps a machine-readable
    # failure even if cleanup or artifact enumeration fails on Windows.
    $FailureSummary = [ordered]@{
        schema_version = 1
        evidence_kind = "portable_cli_mock"
        backend = "mock"
        package_manifest_sha256 = if ($ManifestPath -and (Test-Path -LiteralPath $ManifestPath -PathType Leaf)) {
            Get-Sha256Hex -Path $ManifestPath
        } else { $null }
        case_result = @{ status = "fail"; reason = $FailureReason }
        listening_result = @{ status = "not_assessed"; reason = "Synthetic run did not complete." }
        release_disposition = @{ status = "blocked"; reason = "Mock execution cannot qualify a real-model release." }
    }
    [IO.File]::WriteAllText(
        (Join-Path $ResolvedOutput "cli-acceptance-summary.json"),
        ($FailureSummary | ConvertTo-Json -Depth 8),
        [Text.UTF8Encoding]::new($false)
    )
    throw
}
finally {
    try {
        $Artifacts = @(Get-ChildItem -LiteralPath $ResolvedOutput -File -Recurse |
            Where-Object { $_.FullName -notlike "$Relocated\*" } |
            ForEach-Object {
                [ordered]@{
                    path = $_.FullName.Substring($ResolvedOutput.Length + 1).Replace("\", "/")
                    bytes = $_.Length
                    sha256 = Get-Sha256Hex -Path $_.FullName
                }
            })
        $Summary = [ordered]@{
            schema_version = 1
            evidence_kind = "portable_cli_mock"
            backend = "mock"
            model_revision = "synthetic fixtures; not a Qwen checkpoint"
            package_manifest_sha256 = if ($ManifestPath -and (Test-Path -LiteralPath $ManifestPath -PathType Leaf)) {
                Get-Sha256Hex -Path $ManifestPath
            } else { $null }
            worker_origin = $WorkerOriginProbe
            started_at_utc = $StartedAt
            finished_at_utc = [DateTime]::UtcNow.ToString("o")
            powershell = [string]$PSVersionTable.PSVersion
            os = [Environment]::OSVersion.VersionString
            case_result = @{ status = if ($AcceptancePassed) { "pass" } else { "fail" }; reason = if ($AcceptancePassed) { "Installed mock CLI checks completed." } else { $FailureReason } }
            listening_result = @{ status = "not_assessed"; reason = "Synthetic PCM, not human listening evidence." }
            release_disposition = @{ status = "blocked"; reason = "Mock execution cannot qualify a real-model release." }
            invocations = @($Invocations.ToArray())
            artifacts = $Artifacts
        }
        [IO.File]::WriteAllText((Join-Path $ResolvedOutput "cli-acceptance-summary.json"),
            ($Summary | ConvertTo-Json -Depth 12), [Text.UTF8Encoding]::new($false))
    }
    catch {
        # A cleanup/provenance probe must never erase the failure receipt.
        if (-not (Test-Path -LiteralPath (Join-Path $ResolvedOutput "cli-acceptance-summary.json") -PathType Leaf)) {
            $Fallback = [ordered]@{
                schema_version = 1
                evidence_kind = "portable_cli_mock"
                backend = "mock"
                case_result = @{ status = "fail"; reason = $FailureReason }
                listening_result = @{ status = "not_assessed"; reason = "Synthetic run did not complete." }
                release_disposition = @{ status = "blocked"; reason = "Mock execution cannot qualify a real-model release." }
            }
            [IO.File]::WriteAllText((Join-Path $ResolvedOutput "cli-acceptance-summary.json"),
                ($Fallback | ConvertTo-Json -Depth 8), [Text.UTF8Encoding]::new($false))
        }
    }
}
