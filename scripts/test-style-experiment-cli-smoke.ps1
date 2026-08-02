[CmdletBinding()]
param(
    [string]$Python = "",
    [string]$FasterQwenSourcePath = "",
    [string]$ModelPath = "",
    [string]$BuildDirectory = "build",
    [uint32]$StartupTimeoutMs = 300000,
    [uint32]$StartupSettleSeconds = 35,
    [uint32]$RequestDelaySeconds = 4,
    [string]$Output = "docs/benchmark-artifacts/rtx4090-2026-07-30/style-cli-smoke-v1.json"
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$localConfigPath = Join-Path $repoRoot "config\playback-runtime.local.json"
$profilePath = Join-Path $repoRoot "config\rtx4090-faster-customvoice-style-eager-experiment.json"
$launcherPath = Join-Path $repoRoot "scripts\start-rtx4090-faster-customvoice.ps1"
$cliPath = Join-Path (Join-Path $repoRoot $BuildDirectory) "qwen_tts_play.exe"
$powerShellPath = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"

function Get-ConfigValue([object]$config, [string]$name) {
    $property = $config.PSObject.Properties[$name]
    if ($null -eq $property -or $null -eq $property.Value) {
        return ""
    }
    return [string]$property.Value
}

function Resolve-PathValue([string]$value, [string]$name) {
    if ([string]::IsNullOrWhiteSpace($value)) {
        throw "$name is not configured"
    }
    $candidate = if ([IO.Path]::IsPathRooted($value)) {
        $value
    } else {
        Join-Path $repoRoot $value
    }
    if (-not (Test-Path -LiteralPath $candidate)) {
        throw "$name was not found: $candidate"
    }
    return (Resolve-Path -LiteralPath $candidate).Path
}

function ConvertTo-QuotedArgument([string]$value) {
    return '"' + $value.Replace('"', '\"') + '"'
}

if (-not (Test-Path -LiteralPath $localConfigPath)) {
    throw "Playback configuration was not found: $localConfigPath"
}
if (-not (Test-Path -LiteralPath $cliPath)) {
    throw "qwen_tts_play.exe was not found: $cliPath"
}

$config = Get-Content -Raw -LiteralPath $localConfigPath | ConvertFrom-Json
$pythonPath = Resolve-PathValue $(if ($Python) { $Python } else { Get-ConfigValue $config "python" }) "Python"
$fasterSourcePath = Resolve-PathValue $(
    if ($FasterQwenSourcePath) {
        $FasterQwenSourcePath
    } else {
        Get-ConfigValue $config "style_experiment_faster_qwen_source_path"
    }
) "StyleExperiment FasterQwen source"
$modelPath = Resolve-PathValue $(if ($ModelPath) { $ModelPath } else { Get-ConfigValue $config "model_path" }) "Model path"
$outputPath = if ([IO.Path]::IsPathRooted($Output)) { $Output } else { Join-Path $repoRoot $Output }

$workerArguments = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", $launcherPath,
    "-ProfilePath", $profilePath,
    "-Python", $pythonPath,
    "-ModelPath", $modelPath,
    "-FasterQwenSourcePath", $fasterSourcePath
)
$cliArguments = @("--worker", $powerShellPath, "--cwd", $repoRoot)
$cliArguments += @("--startup-timeout-ms", [string]$StartupTimeoutMs)
foreach ($argument in $workerArguments) {
    $cliArguments += @("--worker-arg", $argument)
}
$cliArguments += @("--speaker", "serena", "--language", "English")

$process = [Diagnostics.Process]::new()
$process.StartInfo.FileName = $cliPath
$process.StartInfo.WorkingDirectory = $repoRoot
$process.StartInfo.UseShellExecute = $false
$process.StartInfo.RedirectStandardInput = $true
$process.StartInfo.RedirectStandardOutput = $true
$process.StartInfo.RedirectStandardError = $true
$process.StartInfo.Arguments = ($cliArguments | ForEach-Object {
    ConvertTo-QuotedArgument ([string]$_)
}) -join " "

if (-not $process.Start()) {
    throw "Could not start qwen_tts_play.exe"
}
$stdoutTask = $process.StandardOutput.ReadToEndAsync()
$stderrTask = $process.StandardError.ReadToEndAsync()
Start-Sleep -Seconds $StartupSettleSeconds

function Send-InteractiveLine([string]$line, [uint32]$delaySeconds = 0) {
    $process.StandardInput.WriteLine($line)
    $process.StandardInput.Flush()
    if ($delaySeconds -gt 0) {
        Start-Sleep -Seconds $delaySeconds
    }
}

$text = "The bridge is stable. Continue the mission."
Send-InteractiveLine "/seed 4242"
Send-InteractiveLine "/temperature 0.4"
Send-InteractiveLine "/sample on"
Send-InteractiveLine $text $RequestDelaySeconds
Send-InteractiveLine "/temperature abc"
Send-InteractiveLine "/top-k 999999"
Send-InteractiveLine $text $RequestDelaySeconds
Send-InteractiveLine "/top-k default"
Send-InteractiveLine "/temperature 0.9"
Send-InteractiveLine $text $RequestDelaySeconds
Send-InteractiveLine "/voice ryan"
Send-InteractiveLine $text $RequestDelaySeconds
Send-InteractiveLine "/voice serena"
Send-InteractiveLine $text $RequestDelaySeconds
Send-InteractiveLine "/quit"
$process.StandardInput.Close()
$process.WaitForExit()

$stdout = $stdoutTask.GetAwaiter().GetResult()
$stderr = $stderrTask.GetAwaiter().GetResult()
$combined = $stdout + "`n" + $stderr
$metrics = @(
    $combined -split "`r?`n" |
        Where-Object { $_.StartsWith("qtb_metric ") } |
        ForEach-Object {
            try {
                $_.Substring("qtb_metric ".Length) | ConvertFrom-Json
            } catch {
                $null
            }
        } |
        Where-Object { $null -ne $_ }
)
$effectiveSettings = @($metrics | Where-Object { $_.event -eq "request_effective_generation_settings" })
$ready = @($metrics | Where-Object { $_.event -eq "worker_ready_sent" } | Select-Object -Last 1)
$summary = [ordered]@{
    schema_version = 1
    experiment = "style_experiment_cpp_cli_stdio_smoke"
    exit_code = $process.ExitCode
    checks = [ordered]@{
        worker_advertised_sampling_capabilities = (
            $ready.Count -eq 1 -and $ready[0].sampling_overrides -and $ready[0].deterministic_seed
        )
        invalid_numeric_command_kept_cli_running = (
            $combined -match "command error:.*stod" -and $combined -match "speaker=serena"
        )
        oversized_top_k_rejected_by_worker = (
            $combined -match "sampling\.top_k must not exceed the loaded codec vocabulary size"
        )
        temperature_04_reached_worker = ($effectiveSettings.effective_temperature -contains 0.4)
        temperature_09_reached_worker = ($effectiveSettings.effective_temperature -contains 0.9)
        explicit_seed_reached_worker = ($effectiveSettings.effective_seed -contains 4242)
        speaker_switches_kept_cli_running = (
            $combined -match "speaker=ryan" -and $combined -match "speaker=serena"
        )
    }
    effective_settings = $effectiveSettings
    request_finished = @($metrics | Where-Object { $_.event -eq "request_finished" })
}
$summary.acceptance_pass = $summary.exit_code -eq 0 -and -not ($summary.checks.Values -contains $false)

[IO.Directory]::CreateDirectory((Split-Path -Parent $outputPath)) | Out-Null
$combined | Set-Content -LiteralPath ($outputPath + ".log") -Encoding utf8
$summary | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $outputPath -Encoding utf8
Write-Output ($summary | ConvertTo-Json -Depth 8)
if (-not $summary.acceptance_pass) {
    exit 1
}
