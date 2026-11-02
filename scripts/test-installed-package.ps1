[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string]$InstallPrefix,
    [string]$BuildDirectory = (Join-Path $env:TEMP 'qwen-tts-bridge-install-consumer'),
    [switch]$RequireWinmmPlayback,
    [switch]$RequireTtsFront
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
if ($RequireTtsFront) {
    $configureArgs += '-DQWEN_TTS_BRIDGE_INSTALL_CONSUMER_USE_TTS_FRONT=ON'
}
cmake -S (Join-Path $repo 'tests/install_consumer') -B $BuildDirectory @configureArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
cmake --build $BuildDirectory --config Release
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$headerRoot = Join-Path $InstallPrefix 'include\qwen_tts_bridge'
foreach ($privateHeader in @(
        (Join-Path $headerRoot 'native.hpp'),
        (Join-Path $headerRoot 'native\native_qwen_backend.hpp'),
        (Join-Path $headerRoot 'protocol\control\control_codec_internal.hpp'),
        (Join-Path $headerRoot 'playback\playback_interruption_diagnostics.hpp'),
        (Join-Path $headerRoot 'integration\speech_animation\speech_animation_adapter.hpp'),
        (Join-Path $headerRoot 'integration\speech_animation\playback_animation_runtime.hpp'))) {
    if (Test-Path -LiteralPath $privateHeader) {
        throw "Private or build-tree-only header leaked into install: $privateHeader"
    }
}

$textHeader = Join-Path $headerRoot 'text.hpp'
$textLeafHeader = Join-Path $headerRoot 'text\tts_front_text_preparer.hpp'
$textTarget = Join-Path $InstallPrefix 'lib\cmake\QwenTTSBridge\QwenTTSBridgeTargets.cmake'
if ($RequireTtsFront) {
    if (-not (Test-Path -LiteralPath $textHeader)) {
        throw 'Text frontend was requested but text.hpp is absent from the install'
    }
    if (-not (Test-Path -LiteralPath $textLeafHeader)) {
        throw 'Installed text.hpp has no matching text adapter headers'
    }
    if (-not (Select-String -LiteralPath $textTarget -Pattern 'qwen_tts_bridge_tts_front' -Quiet)) {
        throw 'Installed text headers have no exported text frontend target'
    }
} else {
    if ((Test-Path -LiteralPath $textHeader) -or
        (Test-Path -LiteralPath $textLeafHeader)) {
        throw 'Text frontend headers leaked into a text-disabled install'
    }
    if ((Test-Path -LiteralPath $textTarget) -and
        (Select-String -LiteralPath $textTarget -Pattern 'qwen_tts_bridge_tts_front' -Quiet)) {
        throw 'Text frontend target leaked into a text-disabled install'
    }
}
exit 0
