param(
    [string]$Python = "C:\_repoz\qwen3-tts-bridge-cpp\.venv-faster-qwen\Scripts\python.exe",
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$RunnerArgs
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Runner = Join-Path $PSScriptRoot "run-voice-clone-bootstrap-candidates.py"
if (-not (Test-Path -LiteralPath $Python)) {
    throw "Python executable was not found: $Python"
}

$PreviousPythonPath = $env:PYTHONPATH
$PreviousPythonHome = $env:PYTHONHOME
$PreviousPythonNoUserSite = $env:PYTHONNOUSERSITE

try {
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    Remove-Item Env:PYTHONHOME -ErrorAction SilentlyContinue
    $env:PYTHONNOUSERSITE = "1"
    Set-Location $RepoRoot
    & $Python -I $Runner @RunnerArgs
    exit $LASTEXITCODE
}
finally {
    $env:PYTHONPATH = $PreviousPythonPath
    $env:PYTHONHOME = $PreviousPythonHome
    $env:PYTHONNOUSERSITE = $PreviousPythonNoUserSite
}
