# CMP 50HX FasterQwen realtime-profile experiment

> Historical diagnostic summary (August 2026). It records a bounded experiment and is not a current release gate. Raw machine artifacts are intentionally local-only and are not part of this curated documentation set.

Result: **FAIL for realtime (`RTF <= 1`).** The branch is `experiment/cmp50hx-realtime-profile`, created from `187d450eb6a9c76e9334b3488468d7949fc34f9f`; the Qwen submodule is `6db590f3614a2243239f8047066d190ae9125852`. Sealed R3 was not modified, and R4 was neither built nor published.

All workers used `CUDA_VISIBLE_DEVICES=GPU-40361931-6cb5-ac58-a059-5ba3e70986fb` and `--device cuda:0`. Torch therefore exposed one device, CMP 50HX (CC 7.5, 21,474,574,336 bytes). Each passing run has a worker-PID to CMP UUID/name mapping in its provenance JSON; the GTX 1060 was not visible to a worker.

## Fixed contract and method

The same private package wheel was used throughout: `faster-qwen3-tts==0.3.2`, wheel SHA-256 `60507afe2636a9d2d67e390a008e11e9790dd87334beef1f95e14499929fb6db`. The model was `Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice` at `85e237c12c027371202489a0ec509ded67b5e4b5`; the fixed medium Russian request, speaker `ryan`, seed `20260806`, 24 kHz mono S16 contract is recorded in `cmp50hx-customvoice-medium-ab-request.jsonl`.

Every trial started one fresh worker, excluded one warmup request, and measured five same-worker requests. The runner passed `--runtime-backend faster --prefill-backend eager --no-compile --no-cuda-graphs --collect-generation-trace`. It did not enable an allowlist, canary, a compile policy, any `8,8,12` frequency profile, or a playback-buffer change. FasterQwen owns internal CUDA-graph behavior: the worker reports `bridge_cuda_graph_control=not_applicable` and `runtime_internal_cuda_graphs_may_be_enabled=true`; this report does not claim that its internal graphs were disabled.

Exact client and worker argument vectors, timestamps, PID snapshots, and System Event ID 153 snapshots were recorded in local provenance JSON artifacts; those raw files are intentionally omitted here. The reproducible invocations were:

```powershell
& tmp\run-cmp50hx-faster-profile.ps1 -Profile baseline-bf16-eager-e8-w80 -Dtype bfloat16 -EmitEveryFrames 8 -DecodeWindowFrames 80
& tmp\run-cmp50hx-faster-profile.ps1 -Profile candidate-fp16-eager-e8-w80 -Dtype float16 -EmitEveryFrames 8 -DecodeWindowFrames 80
& tmp\run-cmp50hx-faster-profile.ps1 -Profile candidate-bf16-eager-e16-w80 -Dtype bfloat16 -EmitEveryFrames 16 -DecodeWindowFrames 80
& tmp\run-cmp50hx-faster-profile.ps1 -Profile candidate-bf16-e8-w160 -Dtype bfloat16 -EmitEveryFrames 8 -DecodeWindowFrames 160
```

## Results

| Profile | 5/5 EOS | Median / p95 TTFA | Median / p95 RTF | Median / p95 chunk cadence | Peak reserved VRAM | Errors |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| BF16 eager, E8/W80 baseline | yes | 1616 / 1620 ms | 2.211 / 2.215 | 1414 / 1428 ms | 3.005 GB | none; no new Event 153 |
| FP16 eager, E8/W80 | no | — | — | — | — | CUDA assertion, `failed to enqueue`, 3 new `nvlddmkm` Event ID 153 |
| BF16 eager, E16/W80 | yes | 2526 / 2533 ms | **1.863 / 1.865** | 2351 / 2371 ms | 2.999 GB | none; no new Event 153 |
| BF16 eager, E8/W160 | yes | 1603 / 1608 ms | 2.210 / 2.214 | 1414 / 1434 ms | 3.005 GB | none; no new Event 153 |

All successful requests reported `termination_reason=eos`, `hit_eos=true`, `hit_max_new_tokens=false`, and `hit_max_seq_len=false`, with positive PCM chunks/bytes and codec frame counts.

## Event 153 investigation

The BF16 baseline had no `failed-to-enqueue` text and no new Event ID 153 across the warmup plus five measured requests. This establishes only the sampled-run result, not a general stability claim.

The FP16-only A/B reproduced the historical failure before any request completed. CMP-bound worker PID `39144` emitted `TensorCompare.cu:109: Assertion input[0] != 0 failed`; the client then reported `failed to enqueue synthesis request`, and three new `nvlddmkm` Event ID 153 entries were recorded. FP16 is therefore rejected for this wheel/runtime on CMP 50HX.

`emit_every_frames=16` improved RTF by about 15.7%, but raised TTFA by about 56% and still remained slower than realtime. `decode_window_frames=160` did not materially change RTF. Compile/CUDA-graph experiments were intentionally not run because the eager candidates remain RTF > 1 and the objective does not justify adding those variables.

## Decision

Do **not** transfer a CMP-specific profile into R4 from this evidence. Keep CMP 50HX on eager fallback. The best observed safe-in-sample setting is BF16/eager/E16/W80, but it misses the realtime target and is not enough evidence for a release policy. Playback buffering was not changed; it cannot make an RTF>1 generator realtime.

The package marker remains present. Post-experiment package-tree and voice-assets verification passed, with declared package digest `c2a5133e843d5660b2fd0ca3c2b633f54154195c6fc1c76e7d0994542211ecfc` and unchanged manifest-document hashes.
