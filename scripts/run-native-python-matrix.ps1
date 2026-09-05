[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string] $BenchmarkExecutable,
    [Parameter(Mandatory = $true)] [string] $PythonWorkerExecutable,
    [Parameter(Mandatory = $true)] [string[]] $PythonWorkerArgument,
    [Parameter(Mandatory = $true)] [string] $NativeWorkerExecutable,
    [Parameter(Mandatory = $true)] [string[]] $NativeWorkerArgument,
    [Parameter(Mandatory = $true)] [string] $Text,
    [string] $Language = "auto",
    [int] $Warmups = 5,
    [int] $Requests = 30,
    [string] $Output = "native-python-matrix.json"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Resolve-ExistingFile([string] $PathValue, [string] $Name) {
    $resolved = (Resolve-Path -LiteralPath $PathValue -ErrorAction Stop).Path
    if (-not (Test-Path -LiteralPath $resolved -PathType Leaf)) { throw "$Name is not a file: $resolved" }
    return $resolved
}

$benchmark = Resolve-ExistingFile $BenchmarkExecutable "BenchmarkExecutable"
$python = Resolve-ExistingFile $PythonWorkerExecutable "PythonWorkerExecutable"
$native = Resolve-ExistingFile $NativeWorkerExecutable "NativeWorkerExecutable"
$outputPath = [System.IO.Path]::GetFullPath($Output)
$outputDirectory = [System.IO.Path]::GetDirectoryName($outputPath)
if ($outputDirectory) { New-Item -ItemType Directory -Force -Path $outputDirectory | Out-Null }

$temporaryDirectory = Join-Path ([System.IO.Path]::GetTempPath()) ("qwen-native-python-matrix-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $temporaryDirectory | Out-Null
try {
    $pythonResult = Join-Path $temporaryDirectory "python.json"
    $nativeResult = Join-Path $temporaryDirectory "native.json"
    $common = @("--text", $Text, "--language", $Language, "--warmups", $Warmups.ToString(), "--requests", $Requests.ToString(), "--result-json")
    & $benchmark --worker $python @PythonWorkerArgument @common $pythonResult
    if ($LASTEXITCODE -ne 0) { throw "Python benchmark failed with exit code $LASTEXITCODE" }
    & $benchmark --worker $native @NativeWorkerArgument @common $nativeResult
    if ($LASTEXITCODE -ne 0) { throw "Native benchmark failed with exit code $LASTEXITCODE" }

    $gpu = @()
    try { $gpu = @(nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader,nounits 2>$null) } catch { $gpu = @() }
    [ordered]@{
        schema_version = 1
        host = [ordered]@{ computer = $env:COMPUTERNAME; gpu = $gpu }
        workload = [ordered]@{ text = $Text; language = $Language; warmups = $Warmups; requests = $Requests }
        python = Get-Content -Raw -LiteralPath $pythonResult | ConvertFrom-Json
        native = Get-Content -Raw -LiteralPath $nativeResult | ConvertFrom-Json
    } | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $outputPath -Encoding UTF8
}
finally {
    if (Test-Path -LiteralPath $temporaryDirectory) { Remove-Item -Recurse -Force -LiteralPath $temporaryDirectory }
}
