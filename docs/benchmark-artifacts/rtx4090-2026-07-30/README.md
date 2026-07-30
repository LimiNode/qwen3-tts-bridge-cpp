# RTX 4090 Synthetic Proxy Evidence

This directory is a reproducible synthetic-proxy evidence bundle for the
experimental `strict_bf16_sdpa_v1` FasterQwen CustomVoice profile. It is not
production traffic, does not authorize a rollout, and does not authorize
padded buckets or the deferred `5 -> 8 -> 12` scheduler experiment.

## Pinned Runtime

- GPU: NVIDIA GeForce RTX 4090.
- Model: `Qwen3-TTS-12Hz-0.6B-CustomVoice`.
- Backend: FasterQwen `0.3.2`, BF16, SDPA, strict exact allowlist.
- Exact compiled prefill lengths: `29, 30, 32, 33, 34, 35`.
- Compiled scheduler: `8, 8, 12`; unknown shapes: eager `8`.
- Runtime and allowlist identities are pinned by the two JSON manifests under
  `canary-manifests/`.

## Evidence Files

- `synthetic-proxy-workload-v1.jsonl` and its audit are the frozen 500-request
  proxy corpus used by run A.
- `synthetic-proxy-workload-v1-repeat-serena.jsonl` is the deterministic run C
  derivative: shuffled with seed `20260731`, speaker `serena`, request seed
  `20260731`, and source-corpus SHA-256 embedded in every record.
- `*-canary.jsonl`, `*-export-summary.json`, and `*-summary.json` are the
  privacy-safe records and strict validation results.
- Raw benchmark JSON and stderr captures were kept locally for analysis but are
  deliberately not versioned because they are large and may contain synthetic
  request text or third-party diagnostics.

## Results

| Run | Outcome | Routes | Compiled first audio median / p95 | Eager first audio median / p95 |
| --- | --- | --- | --- | --- |
| A: 500, `ryan` | 500 completed | 75 compiled / 425 eager | 243.509 / 247.766 ms | 369.636 / 375.334 ms |
| B: operational 100, `ryan` | 60 completed, 15 cancel-before, 15 cancel-after, 10 failed | 11 compiled / 64 eager / 25 undecided | 246.495 / 250.518 ms | 374.405 / 379.708 ms |
| C: 500, shuffled `serena` | 500 completed | 75 compiled / 425 eager | 244.545 / 249.789 ms | 368.826 / 374.500 ms |

For both 500-request runs the strict exporter recorded zero open, orphan,
duplicate, or ignored request metrics and matching worker provenance. The
route split is stable across the changed speaker, order, and seed. Both runs
end in `collect_more_anonymous_coverage`: only 15 percent of this deliberately
broad proxy corpus hits the exact compiled allowlist, and its evidence source
is `synthetic_proxy`.

## Operational Accounting

The operational run validates terminal accounting in one persistent worker.
The ten controlled invalid synthesis requests are terminal `failed` records,
not missing telemetry. This confirms the exporter denominator after the worker
emits `request_finished` for rejected synthesis requests.

## Reproduction

Generate the proxy corpus with
`generate_synthetic_streamer_corpus.py`, create manifests with
`create_route_aware_canary_manifests.py`, and run the worker with both manifest
arguments. Run the C++ latency benchmark with its JSONL request manifest, then
pass the worker capture through `extract_qtb_metrics.py` only when PowerShell
created a UTF-16/wrapped stderr file. Finally use the exporter and summarizer
commands documented in `docs/route-aware-canary-telemetry.md`.
