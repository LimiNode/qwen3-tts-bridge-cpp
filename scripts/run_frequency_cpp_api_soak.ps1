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
    [string]$FasterSourceDirectory
)

$ErrorActionPreference = "Stop"

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$manifest = Join-Path $OutputDirectory "cpp-api-soak-manifest.jsonl"
$warmupManifest = Join-Path $repositoryRoot (
    "docs\benchmark-artifacts\rtx4090-2026-08-01\" +
    "representative-v4-frequency-exact-allowlist-r9\candidate-manifest.json"
)
$outputPath = Join-Path $OutputDirectory "cpp-api-soak-r250.json"

$env:PYTHONPATH = @(
    (Join-Path $repositoryRoot "worker\src")
    (Join-Path $repositoryRoot "scripts")
    (Join-Path $repositoryRoot "tests\python")
    $FasterSourceDirectory
) -join ";"

$arguments = @(
    "--worker=$PythonExecutable",
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
    "--request-manifest=$manifest",
    "--warmups=9",
    "--requests=250",
    "--cancel-every=10",
    "--seed=3",
    "--startup-timeout-ms=300000",
    "--request-timeout-ms=120000"
)

& $BenchmarkExecutable @arguments | Set-Content -LiteralPath $outputPath -Encoding utf8
exit $LASTEXITCODE
