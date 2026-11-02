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
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$headerRoot = Join-Path $InstallPrefix 'include\qwen_tts_bridge'
foreach ($privateHeader in @(
        (Join-Path $headerRoot 'native.hpp'),
        (Join-Path $headerRoot 'protocol\control\control_codec_internal.hpp'))) {
    if (Test-Path -LiteralPath $privateHeader) {
        throw "Private or build-tree-only header leaked into install: $privateHeader"
    }
}

$textHeader = Join-Path $headerRoot 'text.hpp'
$textTarget = Join-Path $InstallPrefix 'lib\cmake\QwenTTSBridge\QwenTTSBridgeTargets.cmake'
if (Test-Path -LiteralPath $textHeader) {
    if (-not (Test-Path -LiteralPath (Join-Path $headerRoot 'text\TtsFrontTextPreparer.hpp'))) {
        throw 'Installed text.hpp has no matching text adapter headers'
    }
    if (-not (Select-String -LiteralPath $textTarget -Pattern 'qwen_tts_bridge_tts_front' -Quiet)) {
        throw 'Installed text headers have no exported text frontend target'
    }
}
exit 0
