[CmdletBinding()]
param(
    [string]$PackageRoot = "",
    [ValidateSet("CustomVoice", "Base")]
    [string]$ModelKind = "CustomVoice",
    [string]$ModelPath = "",
    [string]$VoiceId = "",
    [string]$Speaker = "",
    [string]$Language = "",
    [string]$Instruction = "",
    [string]$Text = "",
    [string]$UserConfigPath = "",
    [switch]$InitializeConfig,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$markerName = ".qtb-technical-beta-root"

function Resolve-ExistingPath([string]$PathValue, [string]$Name) {
    if ([string]::IsNullOrWhiteSpace($PathValue) -or -not (Test-Path -LiteralPath $PathValue)) {
        throw "$Name was not found: $PathValue"
    }
    return (Resolve-Path -LiteralPath $PathValue).Path
}

function Get-ConfigValue([object]$Config, [string]$Name) {
    if ($null -eq $Config) {
        return ""
    }
    $property = $Config.PSObject.Properties[$Name]
    if ($null -eq $property -or $null -eq $property.Value) {
        return ""
    }
    return [string]$property.Value
}

function Set-IsolatedWorkerEnvironment([string]$WorkerRoot) {
    $previous = @{}
    foreach ($name in @(
        "PYTHONHOME", "PYTHONPATH", "PYTHONNOUSERSITE", "PYTHONDONTWRITEBYTECODE",
        "HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"
    )) {
        $item = Get-Item -Path "Env:$name" -ErrorAction SilentlyContinue
        $previous[$name] = if ($null -eq $item) { $null } else { $item.Value }
    }
    $env:PYTHONHOME = (Join-Path $WorkerRoot "python")
    $env:PYTHONPATH = (Join-Path $WorkerRoot "python\Lib\site-packages")
    $env:PYTHONNOUSERSITE = "1"
    $env:PYTHONDONTWRITEBYTECODE = "1"
    $env:HF_HUB_OFFLINE = "1"
    $env:TRANSFORMERS_OFFLINE = "1"
    return $previous
}

function Restore-Environment([hashtable]$Previous) {
    foreach ($name in $Previous.Keys) {
        if ($null -eq $Previous[$name]) {
            Remove-Item -Path "Env:$name" -ErrorAction SilentlyContinue
        }
        else {
            Set-Item -Path "Env:$name" -Value $Previous[$name]
        }
    }
}

$scriptDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
if ([string]::IsNullOrWhiteSpace($PackageRoot)) {
    $PackageRoot = $scriptDirectory
}
$package = Resolve-ExistingPath $PackageRoot "Technical-beta package"
if (-not (Test-Path -LiteralPath (Join-Path $package $markerName))) {
    throw "PackageRoot is not a marked technical-beta package: $package"
}

if ([string]::IsNullOrWhiteSpace($UserConfigPath)) {
    $UserConfigPath = Join-Path $env:LOCALAPPDATA "QwenTTSBridge\runtime.local.json"
}
$userConfig = [IO.Path]::GetFullPath($UserConfigPath)
$template = Join-Path $package "config\runtime.local.example.json"
if ($InitializeConfig) {
    if (Test-Path -LiteralPath $userConfig) {
        throw "User config already exists: $userConfig"
    }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $userConfig) | Out-Null
    Copy-Item -LiteralPath $template -Destination $userConfig -Force
    Write-Host "Created user config: $userConfig"
    Write-Host "Set the external model paths, then run this launcher again."
    exit 0
}
if (-not (Test-Path -LiteralPath $userConfig)) {
    throw "User config was not found: $userConfig. Run with -InitializeConfig first."
}
$config = Get-Content -Raw -LiteralPath $userConfig | ConvertFrom-Json

$selectedModelPath = if ($ModelPath) {
    $ModelPath
} elseif ($ModelKind -eq "Base") {
    Get-ConfigValue $config "base_model_path"
} else {
    Get-ConfigValue $config "custom_voice_model_path"
}
$selectedModel = Resolve-ExistingPath $selectedModelPath "$ModelKind model"
$backend = Get-ConfigValue $config "runtime_backend"
if ([string]::IsNullOrWhiteSpace($backend)) {
    $backend = "faster"
}
if ($backend -notin @("faster", "upstream")) {
    throw "runtime_backend must be faster or upstream: $backend"
}
$dtype = Get-ConfigValue $config "dtype"
if ([string]::IsNullOrWhiteSpace($dtype)) {
    $dtype = "bfloat16"
}
$selectedLanguage = if ($Language) { $Language } else { Get-ConfigValue $config "language" }
if ([string]::IsNullOrWhiteSpace($selectedLanguage)) {
    $selectedLanguage = "auto"
}
$selectedSpeaker = if ($Speaker) { $Speaker } else { Get-ConfigValue $config "custom_voice_speaker" }
$selectedVoiceId = if ($VoiceId) { $VoiceId } else { Get-ConfigValue $config "base_voice_id" }
if ($ModelKind -eq "CustomVoice" -and [string]::IsNullOrWhiteSpace($selectedSpeaker)) {
    throw "CustomVoice needs a speaker. Set custom_voice_speaker or pass -Speaker."
}
if ($ModelKind -eq "Base" -and [string]::IsNullOrWhiteSpace($selectedVoiceId)) {
    throw "Base needs a registered voice ID. Set base_voice_id or pass -VoiceId."
}

$workerRoot = Resolve-ExistingPath (Join-Path $package "worker") "Packaged worker"
$python = Resolve-ExistingPath (Join-Path $workerRoot "python\python.exe") "Packaged Python"
$cli = Resolve-ExistingPath (Join-Path $package "bin\qwen_tts_play.exe") "Packaged playback CLI"
$registry = Resolve-ExistingPath (Join-Path $package "config\voice-profiles.json") "Packaged voice registry"
$workerArguments = @(
    "-B", "-P", "-s", "-m", "qwen_tts_bridge_worker",
    "qwen", "--model-path", $selectedModel,
    "--runtime-backend", $backend,
    "--device", "cuda",
    "--dtype", $dtype,
    "--attn-implementation", "sdpa",
    "--prefill-backend", "eager",
    "--no-compile"
)
if ($ModelKind -eq "Base") {
    $workerArguments += @("--voice-registry-path", $registry)
}
$cliArguments = @(
    "--worker", $python,
    "--cwd", $package,
    "--startup-timeout-ms", "60000",
    "--language", $selectedLanguage
)
foreach ($workerArgument in $workerArguments) {
    $cliArguments += @("--worker-arg", $workerArgument)
}
if ($ModelKind -eq "Base") {
    $cliArguments += @("--voice-id", $selectedVoiceId)
}
else {
    $cliArguments += @("--speaker", $selectedSpeaker)
}
if ($Instruction) {
    $cliArguments += @("--instruction", $Instruction)
}
if ($Text) {
    $cliArguments += @("--text", $Text)
}
if ($DryRun) {
    Write-Output ("CLI: " + $cli)
    Write-Output ("Arguments: " + ($cliArguments -join " | "))
    exit 0
}

$exitCode = 1
$previousEnvironment = Set-IsolatedWorkerEnvironment $workerRoot
try {
    & $cli @cliArguments
    $exitCode = $LASTEXITCODE
}
finally {
    Restore-Environment $previousEnvironment
}
exit $exitCode
