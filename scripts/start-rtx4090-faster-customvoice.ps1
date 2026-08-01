[CmdletBinding()]
param(
    [string]$ProfilePath = "config/rtx4090-faster-customvoice-experimental.json",
    [string]$Python = ".venv-qwen-flash/Scripts/python.exe",
    [string]$ModelPath = "",
    [string]$FasterQwenSourcePath = "",
    [switch]$ValidateOnly,
    [string[]]$AdditionalArguments = @()
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$profileFullPath = if ([System.IO.Path]::IsPathRooted($ProfilePath)) {
    $ProfilePath
} else {
    Join-Path $repoRoot $ProfilePath
}
$profile = Get-Content -Raw $profileFullPath | ConvertFrom-Json

if ($profile.profile_status -eq "internal_opt_in_only" -and $AdditionalArguments.Count -gt 0) {
    throw "Internal runtime profiles do not accept AdditionalArguments."
}

$pythonPath = if ([System.IO.Path]::IsPathRooted($Python)) {
    $Python
} else {
    Join-Path $repoRoot $Python
}
$selectedModelPath = if ($ModelPath) { $ModelPath } else { $profile.model_path }

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Python executable was not found: $pythonPath"
}

$pythonPaths = @()
if ($FasterQwenSourcePath) {
    $pythonPaths += (Resolve-Path $FasterQwenSourcePath).Path
}
$pythonPaths += (Join-Path $repoRoot "worker\src")
if ($env:PYTHONPATH) {
    $pythonPaths += $env:PYTHONPATH
}
$env:PYTHONPATH = [string]::Join(";", $pythonPaths)

$maxSeqLen = if ($null -ne $profile.max_seq_len) { $profile.max_seq_len } else { 2048 }
$arguments = @(
    "-m", "qwen_tts_bridge_worker",
    "qwen",
    "--model-path", $selectedModelPath,
    "--runtime-backend", $profile.runtime_backend,
    "--device", $profile.device,
    "--dtype", $profile.dtype,
    "--attn-implementation", $profile.attn_implementation,
    "--max-seq-len", $maxSeqLen,
    "--emit-every-frames", $profile.emit_every_frames,
    "--decode-window-frames", $profile.decode_window_frames,
    "--prefill-backend", $profile.prefill_backend,
    "--prefill-compile-compat-mode", $profile.prefill_compile_compat_mode,
    "--prefill-unknown-shape-policy", $profile.prefill_unknown_shape_policy,
    "--prefill-compile-policy", $profile.prefill_compile_policy,
    "--prefill-allowlist-warmup-repeats", $profile.prefill_allowlist_warmup_repeats,
    "--prefill-allowlist-max-entries", $profile.prefill_allowlist_max_entries,
    "--prefill-allowlist-max-abs-threshold", $profile.prefill_allowlist_max_abs_threshold
)

if ($profile.prefill_compile_lengths -and $profile.prefill_compile_lengths.Count -gt 0) {
    $arguments += @(
        "--prefill-compile-lengths",
        ($profile.prefill_compile_lengths -join ",")
    )
}
if (-not [string]::IsNullOrWhiteSpace($profile.prefill_allowlist_warmup_manifest)) {
    $arguments += @(
        "--prefill-allowlist-warmup-manifest",
        $profile.prefill_allowlist_warmup_manifest
    )
}

if ($null -ne $profile.max_audio_seconds_per_utterance) {
    $arguments += @(
        "--max-audio-seconds-per-utterance",
        $profile.max_audio_seconds_per_utterance
    )
}

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
if ($profile.prefill_generation_prime) {
    $arguments += "--prefill-generation-prime"
}
if ($profile.allow_request_sampling_overrides) {
    $arguments += "--allow-request-sampling-overrides"
}
if ($null -ne $profile.temperature) {
    $arguments += @("--temperature", $profile.temperature)
}
if ($null -ne $profile.top_k) {
    $arguments += @("--top-k", $profile.top_k)
}
if ($null -ne $profile.top_p) {
    $arguments += @("--top-p", $profile.top_p)
}
if ($null -ne $profile.repetition_penalty) {
    $arguments += @("--repetition-penalty", $profile.repetition_penalty)
}
if ($null -ne $profile.do_sample -and -not $profile.do_sample) {
    $arguments += "--no-sample"
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

if ($profile.profile_status -eq "internal_opt_in_only") {
    $preflight = Join-Path $repoRoot "scripts/validate_internal_runtime_profile.py"
    $preflightArguments = @("--profile", $profileFullPath, "--model-path", $selectedModelPath)
    foreach ($argument in $arguments) {
        $preflightArguments += "--worker-argument=$argument"
    }
    $preflightOutput = & $pythonPath $preflight @preflightArguments
    $preflightExitCode = $LASTEXITCODE
    if ($preflightOutput) {
        [Console]::Error.WriteLine(($preflightOutput -join [Environment]::NewLine))
    }
    if ($preflightExitCode -ne 0) {
        throw "Internal runtime profile preflight failed."
    }
}

if ($ValidateOnly) {
    exit 0
}

& $pythonPath @arguments @AdditionalArguments
exit $LASTEXITCODE
