param(
    [Parameter(Mandatory = $true)]
    [string]$PythonExecutable,

    [Parameter(Mandatory = $true)]
    [string]$ModelPath,

    [Parameter(Mandatory = $true)]
    [string]$OutputDirectory,

    [Parameter(Mandatory = $true)]
    [string]$FasterSourceDirectory,

    [Parameter(Mandatory = $true)]
    [string]$FasterSourceBundleSha256,

    [string]$RunName = "python-operational-soak"
)

$ErrorActionPreference = "Stop"

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$schedule = Join-Path $OutputDirectory "operational-soak-schedule.jsonl"
$seedManifest = Join-Path $OutputDirectory "seed-manifest.json"
$warmupManifest = Join-Path $repositoryRoot (
    "docs\benchmark-artifacts\rtx4090-2026-08-01\" +
    "representative-v4-frequency-exact-allowlist-r9\candidate-manifest.json"
)
$report = Join-Path $OutputDirectory "$RunName-report.json"
$exitCodePath = Join-Path $OutputDirectory "$RunName.exit-code.txt"
$seedConfiguration = Get-Content -LiteralPath $seedManifest -Raw | ConvertFrom-Json
$semanticSeed = $seedConfiguration.cancellation_semantic_seed
if ($semanticSeed -isnot [int] -or $semanticSeed -lt 0) {
    throw "seed manifest must provide a non-negative cancellation_semantic_seed"
}

$env:PYTHONPATH = @(
    (Join-Path $repositoryRoot "worker\src")
    (Join-Path $repositoryRoot "scripts")
    (Join-Path $repositoryRoot "tests\python")
    $FasterSourceDirectory
) -join ";"

$arguments = @(
    "-B",
    (Join-Path $PSScriptRoot "qwen_release_soak.py"),
    $PythonExecutable,
    "--worker-arg=-B",
    "--worker-arg=-m",
    "--worker-arg=qwen_tts_bridge_worker",
    "--worker-arg=qwen",
    "--worker-arg=--model-path",
    "--worker-arg=$ModelPath",
    "--worker-arg=--runtime-backend",
    "--worker-arg=faster",
    "--worker-arg=--device",
    "--worker-arg=cuda",
    "--worker-arg=--dtype",
    "--worker-arg=bfloat16",
    "--worker-arg=--attn-implementation",
    "--worker-arg=sdpa",
    "--worker-arg=--max-audio-seconds-per-utterance",
    "--worker-arg=60",
    "--worker-arg=--emit-every-frames",
    "--worker-arg=8",
    "--worker-arg=--compiled-emit-chunk-schedule",
    "--worker-arg=8,8,12",
    "--worker-arg=--eager-emit-chunk-schedule",
    "--worker-arg=8",
    "--worker-arg=--decode-window-frames",
    "--worker-arg=80",
    "--worker-arg=--prefill-backend",
    "--worker-arg=compile_reduce_overhead",
    "--worker-arg=--prefill-compile-compat-mode",
    "--worker-arg=strict_bf16_sdpa_v1",
    "--worker-arg=--prefill-compile-lengths",
    "--worker-arg=18,19,20,26,27,29",
    "--worker-arg=--no-prefill-compile-on-miss",
    "--worker-arg=--prefill-unknown-shape-policy",
    "--worker-arg=eager",
    "--worker-arg=--prefill-compile-policy",
    "--worker-arg=exact_allowlist",
    "--worker-arg=--prefill-allowlist-warmup-manifest",
    "--worker-arg=$warmupManifest",
    "--worker-arg=--prefill-allowlist-warmup-repeats",
    "--worker-arg=3",
    "--worker-arg=--prefill-allowlist-max-entries",
    "--worker-arg=6",
    "--worker-arg=--prefill-allowlist-max-abs-threshold",
    "--worker-arg=0.0",
    "--worker-arg=--prefill-require-precompiled",
    "--worker-arg=--prefill-first-chunk-warmup",
    "--worker-arg=--prefill-first-chunk-warmup-length",
    "--worker-arg=18",
    "--worker-arg=--prefill-generation-prime",
    "--worker-arg=--collect-generation-trace",
    "--worker-arg=--warmup-speaker",
    "--worker-arg=ryan",
    "--worker-arg=--seed",
    "--worker-arg=20260801",
    "--worker-arg=--seed-mode",
    "--worker-arg=request_id",
    "--schedule=$schedule",
    "--seed-manifest=$seedManifest",
    "--required-label=compiled_18_ryan",
    "--required-label=compiled_19_serena",
    "--required-label=compiled_20_ryan",
    "--required-label=compiled_26_serena",
    "--required-label=compiled_27_ryan",
    "--required-label=compiled_29_serena",
    "--required-label=eager_17_ryan",
    "--required-label=eager_38_serena_mixed",
    "--required-label=eager_60_ryan",
    "--requests=504",
    "--cancellations-per-category=12",
    "--semantic-seed=$semanticSeed",
    "--operation-seed=20260801",
    "--progress-every=25",
    "--partial-output=$report",
    "--timeout-seconds=1200",
    "--cancel-timeout-seconds=120",
    "--max-rss-growth-mb=512",
    "--max-private-growth-mb=512",
    "--max-cuda-allocated-growth-mb=128",
    "--max-cuda-reserved-growth-mb=128",
    "--max-cuda-reserved-tail-slope-bytes-per-request=1048576",
    "--gpu-pid-telemetry-policy=allow_unsupported",
    "--expected-prefill-cache-entries=6",
    "--expected-faster-source-bundle-sha256=$FasterSourceBundleSha256"
)

& $PythonExecutable @arguments
$exitCode = $LASTEXITCODE
Set-Content -LiteralPath $exitCodePath -Value $exitCode -NoNewline
exit $exitCode
