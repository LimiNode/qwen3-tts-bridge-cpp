[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string]$InstallPrefix,
    [string]$BuildDirectory = (Join-Path $env:TEMP 'qwen-tts-bridge-install-consumer')
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
if (Test-Path -LiteralPath $BuildDirectory) {
    Remove-Item -LiteralPath $BuildDirectory -Recurse -Force
}
cmake -S (Join-Path $repo 'tests/install_consumer') -B $BuildDirectory `
    "-DCMAKE_PREFIX_PATH=$InstallPrefix"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
cmake --build $BuildDirectory --config Release
exit $LASTEXITCODE
