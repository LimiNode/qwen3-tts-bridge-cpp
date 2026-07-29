[CmdletBinding()]
param(
    [string]$ProfilePath = "config/rtx4090-faster-customvoice-experimental.json",
    [string]$Python = ".venv-qwen-flash/Scripts/python.exe",
    [string]$ModelPath = "",
    [string[]]$AdditionalArguments = @()
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$profileFullPath = Join-Path $repoRoot $ProfilePath
$profile = Get-Content -Raw $profileFullPath | ConvertFrom-Json
$pythonPath = Join-Path $repoRoot $Python

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Python executable was not found: $pythonPath"
}

$selectedModelPath = if ($ModelPath) { $ModelPath } else { $profile.model_path }
$arguments = @(
    "-m", "qwen_tts_bridge_worker",
    "qwen",
    "--model-path", $selectedModelPath,
    "--runtime-backend", $profile.runtime_backend,
    "--device", $profile.device,
    "--dtype", $profile.dtype,
    "--attn-implementation", $profile.attn_implementation,
    "--emit-every-frames", $profile.emit_every_frames,
    "--decode-window-frames", $profile.decode_window_frames,
    "--prefill-backend", $profile.prefill_backend,
    "--prefill-compile-compat-mode", $profile.prefill_compile_compat_mode,
    "--prefill-compile-lengths", ($profile.prefill_compile_lengths -join ","),
    "--prefill-unknown-shape-policy", $profile.prefill_unknown_shape_policy,
    "--prefill-compile-policy", $profile.prefill_compile_policy,
    "--prefill-allowlist-warmup-manifest", $profile.prefill_allowlist_warmup_manifest,
    "--prefill-allowlist-warmup-repeats", $profile.prefill_allowlist_warmup_repeats,
    "--prefill-allowlist-max-entries", $profile.prefill_allowlist_max_entries,
    "--prefill-allowlist-max-abs-threshold", $profile.prefill_allowlist_max_abs_threshold
)

if (-not $profile.prefill_compile_on_miss) {
    $arguments += "--no-prefill-compile-on-miss"
}
if ($profile.prefill_require_precompiled) {
    $arguments += "--prefill-require-precompiled"
}
if ($profile.prefill_first_chunk_warmup) {
    $arguments += @(
        "--prefill-first-chunk-warmup",
        "--prefill-first-chunk-warmup-length", $profile.prefill_first_chunk_warmup_length
    )
}
if ($profile.collect_generation_trace) {
    $arguments += "--collect-generation-trace"
}
if ($profile.profile_prefill) {
    $arguments += "--profile-prefill"
}
if ($profile.emit_chunk_schedule -and $profile.emit_chunk_schedule.Count -gt 0) {
    $arguments += @(
        "--emit-chunk-schedule",
        ($profile.emit_chunk_schedule -join ",")
    )
}
if ($profile.compiled_emit_chunk_schedule -and $profile.compiled_emit_chunk_schedule.Count -gt 0) {
    $arguments += @(
        "--compiled-emit-chunk-schedule",
        ($profile.compiled_emit_chunk_schedule -join ",")
    )
}
if ($profile.eager_emit_chunk_schedule -and $profile.eager_emit_chunk_schedule.Count -gt 0) {
    $arguments += @(
        "--eager-emit-chunk-schedule",
        ($profile.eager_emit_chunk_schedule -join ",")
    )
}

& $pythonPath @arguments @AdditionalArguments
exit $LASTEXITCODE
