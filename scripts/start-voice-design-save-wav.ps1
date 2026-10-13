[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$SaveWavExecutable,
    [Parameter(Mandatory = $true)]
    [string]$Worker,
    [string[]]$WorkerArgument = @(),
    [Parameter(Mandatory = $true)]
    [string]$Text,
    [Parameter(Mandatory = $true)]
    [string]$Instruction,
    [string]$Language = "Russian",
    [string]$Output = "voice-design.wav",
    [string]$ResultJson = "",
    [UInt32]$SampleRate = 24000,
    [UInt32]$Channels = 1,
    [switch]$RequireNaturalEos
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot

function Resolve-RepoPath {
    param([string]$Path)

    if ([IO.Path]::IsPathRooted($Path)) {
        return [IO.Path]::GetFullPath($Path)
    }
    return [IO.Path]::GetFullPath((Join-Path $RepoRoot $Path))
}

function Read-WavMetadata {
    param([string]$Path)

    $stream = [IO.File]::OpenRead($Path)
    $reader = [IO.BinaryReader]::new($stream)
    try {
        if ($stream.Length -lt 12) {
            throw "output WAV is smaller than a RIFF header"
        }
        $riff = [Text.Encoding]::ASCII.GetString($reader.ReadBytes(4))
        [UInt32]$riffSize = $reader.ReadUInt32()
        $wave = [Text.Encoding]::ASCII.GetString($reader.ReadBytes(4))
        if ($riff -ne "RIFF" -or $wave -ne "WAVE") {
            throw "output is not a RIFF/WAVE file"
        }
        if ([UInt64]$riffSize + 8 -ne [UInt64]$stream.Length) {
            throw "RIFF declared size does not match file size"
        }

        $format = $null
        $dataBytes = [UInt64]0
        while ($stream.Position + 8 -le $stream.Length) {
            $chunkId = [Text.Encoding]::ASCII.GetString($reader.ReadBytes(4))
            $chunkSize = [UInt32]$reader.ReadUInt32()
            $chunkStart = $stream.Position
            $chunkEnd = [UInt64]$chunkStart + [UInt64]$chunkSize
            if ($chunkEnd -gt [UInt64]$stream.Length) {
                throw "WAV chunk '$chunkId' extends beyond the physical file"
            }
            if ($chunkId -eq "fmt ") {
                if ($chunkSize -lt 16) {
                    throw "WAV fmt chunk is shorter than PCM format metadata"
                }
                $format = [pscustomobject]@{
                    AudioFormat = [UInt16]$reader.ReadUInt16()
                    Channels = [UInt16]$reader.ReadUInt16()
                    SampleRate = [UInt32]$reader.ReadUInt32()
                    ByteRate = [UInt32]$reader.ReadUInt32()
                    BlockAlign = [UInt16]$reader.ReadUInt16()
                    BitsPerSample = [UInt16]0
                }
                $format.BitsPerSample = [UInt16]$reader.ReadUInt16()
            }
            elseif ($chunkId -eq "data") {
                $dataBytes += [UInt64]$chunkSize
            }
            $paddedEnd = $chunkEnd + ($chunkSize % 2)
            if ($paddedEnd -gt [UInt64]$stream.Length) {
                throw "WAV chunk '$chunkId' has no complete padding byte"
            }
            $stream.Position = [Int64]$paddedEnd
        }

        if ($null -eq $format -or $dataBytes -eq 0) {
            throw "output WAV has no valid format/data payload"
        }
        return [pscustomobject]@{
            AudioFormat = $format.AudioFormat
            Channels = $format.Channels
            SampleRate = $format.SampleRate
            ByteRate = $format.ByteRate
            BlockAlign = $format.BlockAlign
            BitsPerSample = $format.BitsPerSample
            DataBytes = $dataBytes
        }
    }
    finally {
        $reader.Dispose()
        $stream.Dispose()
    }
}

$saveWavPath = Resolve-RepoPath $SaveWavExecutable
$workerPath = Resolve-RepoPath $Worker
$outputPath = Resolve-RepoPath $Output
if ([string]::IsNullOrWhiteSpace($ResultJson)) {
    $resultJsonPath = "$outputPath.json"
}
else {
    $resultJsonPath = Resolve-RepoPath $ResultJson
}

if (-not (Test-Path -LiteralPath $saveWavPath -PathType Leaf)) {
    throw "qwen_tts_save_wav executable was not found: $saveWavPath"
}
if (-not (Test-Path -LiteralPath $workerPath -PathType Leaf)) {
    throw "worker executable was not found: $workerPath"
}
if ($Instruction.Trim().Length -eq 0) {
    throw "VoiceDesign requires a non-empty -Instruction"
}
if ($SampleRate -eq 0 -or $Channels -eq 0) {
    throw "-SampleRate and -Channels must be greater than zero"
}

$outputDirectory = Split-Path -Parent $outputPath
if ($outputDirectory -and -not (Test-Path -LiteralPath $outputDirectory)) {
    New-Item -ItemType Directory -Path $outputDirectory | Out-Null
}

$arguments = @(
    "--worker", $workerPath,
    "--output", $outputPath,
    "--result-json", $resultJsonPath,
    "--text", $Text,
    "--language", $Language,
    "--instruction", $Instruction,
    "--sample-rate", "$SampleRate",
    "--channels", "$Channels"
)
foreach ($argument in $WorkerArgument) {
    $arguments += @("--worker-arg", $argument)
}
if ($RequireNaturalEos) {
    $arguments += "--require-natural-eos"
}

& $saveWavPath @arguments
if ($LASTEXITCODE -ne 0) {
    throw "qwen_tts_save_wav failed with exit code $LASTEXITCODE"
}
if (-not (Test-Path -LiteralPath $outputPath -PathType Leaf)) {
    throw "qwen_tts_save_wav did not create the output WAV"
}
if (-not (Test-Path -LiteralPath $resultJsonPath -PathType Leaf)) {
    throw "qwen_tts_save_wav did not create terminal result JSON"
}

$wav = Read-WavMetadata $outputPath
if ($wav.AudioFormat -ne 1 -or
    $wav.Channels -ne $Channels -or
    $wav.SampleRate -ne $SampleRate -or
    $wav.BitsPerSample -ne 16 -or
    $wav.BlockAlign -ne ($Channels * 2) -or
    $wav.ByteRate -ne ($SampleRate * $Channels * 2)) {
    throw "unexpected WAV format: PCM=$($wav.AudioFormat), channels=$($wav.Channels), sample_rate=$($wav.SampleRate), bits=$($wav.BitsPerSample), block_align=$($wav.BlockAlign), byte_rate=$($wav.ByteRate)"
}

$result = Get-Content -LiteralPath $resultJsonPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($result.terminal_state -ne "completed" -or [UInt64]$result.audio_bytes -eq 0) {
    throw "VoiceDesign result JSON does not report completed non-empty audio"
}
if ([UInt64]$result.audio_bytes -ne $wav.DataBytes) {
    throw "WAV data bytes ($($wav.DataBytes)) do not match result audio_bytes ($($result.audio_bytes))"
}

Write-Output ("VoiceDesign WAV accepted: {0} Hz, {1} channel(s), {2} PCM bytes; result={3}" -f `
    $wav.SampleRate, $wav.Channels, $wav.DataBytes, $resultJsonPath)
