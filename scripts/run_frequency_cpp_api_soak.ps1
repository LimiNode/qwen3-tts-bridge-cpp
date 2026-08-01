param(
    [Parameter(Mandatory = $true)]
    [string]$BenchmarkExecutable,

    [Parameter(Mandatory = $true)]
    [string]$PythonExecutable,

    [Parameter(Mandatory = $true)]
    [string]$ModelPath,

    [Parameter(Mandatory = $true)]
    [string]$OutputDirectory,

    [Parameter(Mandatory = $true)]
    [string]$FasterSourceDirectory,

    [Parameter(Mandatory = $true)]
    [string]$ManifestPath
)

$ErrorActionPreference = "Stop"

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$launcher = Join-Path $repositoryRoot "scripts\start-rtx4090-faster-customvoice.ps1"
$profile = "config\rtx4090-faster-customvoice-frequency-exact-allowlist-r10-internal-opt-in.json"
$powerShell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$manifest = (Resolve-Path $ManifestPath).Path
$null = New-Item -ItemType Directory -Force -Path $OutputDirectory
$outputPath = Join-Path $OutputDirectory "cpp-api-soak-r250.json"

$arguments = @(
    "--worker=$powerShell",
    "--worker-arg=-NoProfile",
    "--worker-arg=-ExecutionPolicy",
    "--worker-arg=Bypass",
    "--worker-arg=-File",
    "--worker-arg=$launcher",
    "--worker-arg=-ProfilePath",
    "--worker-arg=$profile",
    "--worker-arg=-ModelPath",
    "--worker-arg=$ModelPath",
    "--worker-arg=-Python",
    "--worker-arg=$PythonExecutable",
    "--worker-arg=-FasterQwenSourcePath",
    "--worker-arg=$FasterSourceDirectory",
    "--request-manifest=$manifest",
    "--warmups=9",
    "--requests=250",
    "--cancel-every=10",
    "--seed=3",
    "--startup-timeout-ms=300000",
    "--request-timeout-ms=120000"
)

$benchmarkOutput = & $BenchmarkExecutable @arguments
$exitCode = $LASTEXITCODE
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
$outputText = if ($null -eq $benchmarkOutput) {
    ""
} else {
    [string]::Join([Environment]::NewLine, [string[]]$benchmarkOutput)
}
[System.IO.File]::WriteAllText(
    $outputPath,
    $outputText,
    $utf8NoBom
)
exit $exitCode
