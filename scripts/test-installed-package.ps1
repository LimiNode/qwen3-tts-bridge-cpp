[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string]$InstallPrefix,
    [string]$BuildDirectory = (Join-Path $env:TEMP 'qwen-tts-bridge-install-consumer'),
    [switch]$RequireWinmmPlayback
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
if (Test-Path -LiteralPath $BuildDirectory) {
    Remove-Item -LiteralPath $BuildDirectory -Recurse -Force
}
$configureArgs = @(
    "-DCMAKE_PREFIX_PATH=$InstallPrefix"
)
if ($RequireWinmmPlayback) {
    $configureArgs += '-DQWEN_TTS_BRIDGE_INSTALL_CONSUMER_USE_WINMM=ON'
}
cmake -S (Join-Path $repo 'tests/install_consumer') -B $BuildDirectory @configureArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
cmake --build $BuildDirectory --config Release
exit $LASTEXITCODE
