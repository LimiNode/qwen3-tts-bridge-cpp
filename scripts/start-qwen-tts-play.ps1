[CmdletBinding()]
param(
    [string]$ProfilePath = "config/rtx4090-48gb-faster-customvoice-frequency-exact-allowlist-r10-internal-opt-in.json",
    [string]$Python = "",
    [string]$FasterQwenSourcePath = "",
    [string]$ModelPath = "",
    [string]$Speaker = "",
    [string]$Language = "",
    [string]$Instruction = "",
    [string]$Text = "",
    [string]$BuildDirectory = "build",
    [uint32]$StartupTimeoutMs = 300000,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$localConfigPath = Join-Path $repoRoot "config\playback-runtime.local.json"
$exampleConfigPath = Join-Path $repoRoot "config\playback-runtime.local.example.json"

function Get-ConfigValue([object]$config, [string]$name) {
    if ($null -eq $config) {
        return ""
    }
    $property = $config.PSObject.Properties[$name]
    if ($null -eq $property -or $null -eq $property.Value) {
        return ""
    }
    return [string]$property.Value
}

function Resolve-RepoOrAbsolutePath([string]$path) {
    if ([string]::IsNullOrWhiteSpace($path)) {
        return ""
    }
    $candidate = if ([System.IO.Path]::IsPathRooted($path)) {
        $path
    } else {
        Join-Path $repoRoot $path
    }
    if (-not (Test-Path -LiteralPath $candidate)) {
        throw "Path was not found: $candidate"
    }
    return (Resolve-Path -LiteralPath $candidate).Path
}

$localConfig = $null
if (Test-Path -LiteralPath $localConfigPath) {
    $localConfig = Get-Content -Raw -LiteralPath $localConfigPath | ConvertFrom-Json
}

$pythonValue = if ($Python) { $Python } else { Get-ConfigValue $localConfig "python" }
$fasterSourceValue = if ($FasterQwenSourcePath) {
    $FasterQwenSourcePath
} else {
    Get-ConfigValue $localConfig "faster_qwen_source_path"
}
$modelValue = if ($ModelPath) { $ModelPath } else { Get-ConfigValue $localConfig "model_path" }
$speakerValue = if ($Speaker) { $Speaker } else { Get-ConfigValue $localConfig "speaker" }
$languageValue = if ($Language) { $Language } else { Get-ConfigValue $localConfig "language" }
$instructionValue = if ($Instruction) { $Instruction } else { Get-ConfigValue $localConfig "instruction" }

if ([string]::IsNullOrWhiteSpace($pythonValue) -or
    [string]::IsNullOrWhiteSpace($fasterSourceValue) -or
    [string]::IsNullOrWhiteSpace($modelValue)) {
    throw @"
Playback runtime is not configured. Copy:
  $exampleConfigPath
to:
  $localConfigPath
and set python, faster_qwen_source_path, and model_path once. The local file is ignored by Git.
"@
}

$pythonPath = Resolve-RepoOrAbsolutePath $pythonValue
$fasterSourcePath = Resolve-RepoOrAbsolutePath $fasterSourceValue
$modelPath = Resolve-RepoOrAbsolutePath $modelValue
$profileFullPath = Resolve-RepoOrAbsolutePath $ProfilePath
$launcherPath = Join-Path $repoRoot "scripts\start-rtx4090-faster-customvoice.ps1"
$cliPath = Join-Path (Join-Path $repoRoot $BuildDirectory) "qwen_tts_play.exe"
$powerShellPath = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"

if (-not (Test-Path -LiteralPath $cliPath)) {
    throw "qwen_tts_play.exe was not found: $cliPath. Build target qwen_tts_play first."
}

$workerArguments = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", $launcherPath,
    "-ProfilePath", $profileFullPath,
    "-Python", $pythonPath,
    "-ModelPath", $modelPath,
    "-FasterQwenSourcePath", $fasterSourcePath
)

$cliArguments = @(
    "--worker", $powerShellPath,
    "--cwd", $repoRoot,
    "--startup-timeout-ms", [string]$StartupTimeoutMs
)
foreach ($argument in $workerArguments) {
    $cliArguments += @("--worker-arg", $argument)
}
if ($speakerValue) {
    $cliArguments += @("--speaker", $speakerValue)
}
if ($languageValue) {
    $cliArguments += @("--language", $languageValue)
}
if ($instructionValue) {
    $cliArguments += @("--instruction", $instructionValue)
}
if ($Text) {
    $cliArguments += @("--text", $Text)
}

if ($DryRun) {
    Write-Output ("CLI: " + $cliPath)
    Write-Output ("Arguments: " + ($cliArguments -join " | "))
    exit 0
}

& $cliPath @cliArguments
exit $LASTEXITCODE
