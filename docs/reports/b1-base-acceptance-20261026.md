# B1 Base 1.7B acceptance — bounded CMP 50HX run

Status: **B1-A PASS; B1-B protocol/recovery and restart PASS; active-GPU cancellation evidence is not yet verified; B1-C and B2 remain pending**.

This report uses the frozen inputs from merged B2-4 preflight (`main`
`3ad3527aa063298159e40bc6362d060548688369`). Model weights, the deployment
voice registry, WAV assets, and raw receipts remain outside Git.

## Frozen runtime and corpus

```text
GPU: NVIDIA CMP 50HX, capability 7.5, driver 581.94, CUDA 12.8
model: Qwen3-TTS-12Hz-1.7B-Base
model manifest: d47209b486d4e6929a554e09f5be87803309be68387ac075c0b1f7e62a1f7d66
voice_id: kraftwerk_robot_ru_bootstrap_fidelity
portable worker: E:\stage-a-relocated\QwenTTSBridge\worker-python
voice registry: E:\stage-a-base-evidence\voice-registry\voice-profiles.local.json
runtime backend: faster / CUDA / bfloat16 / SDPA / eager prefill
compile: disabled; CUDA graphs: disabled
max_seq_len: 768; emit_every_frames: 8; decode_window_frames: 80
seed: not set; seed mode: request_id
per-request timeout: 900 s
```

The five-request UTF-8 corpus is versioned beside this report at
`b1-base-acceptance-20261026-corpus.jsonl`. Its SHA-256 is:

```text
708bafd3c9299e24d2ec924e8b3bf9dfb9828e845cc2270606cfae5550dfcdbf
```

It covers the successful short phrase, punctuation and pauses, Russian numbers
and abbreviations, a multi-sentence paragraph, and a repeated short phrase.

## B1-A — persistent multi-request synthesis

One worker process handled request IDs 1 through 5 sequentially using the
registered voice. The separate EOS oracle inspected every `completed` payload;
all five rows satisfied `execution_outcome=completed`, `termination_reason=eos`,
`hit_eos=true`, `hit_max_new_tokens=false`, `hit_max_seq_len=false`, and equal
positive `generated_steps`, `emitted_steps`, and `terminal_step_index`.

| ID | Corpus case | PCM bytes | chunks | codec frames | first audio ms | completion ms |
| ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | short_success | 162,976 | 6 | 43 | 17,545.814 | 28,469.681 |
| 2 | punctuation | 303,876 | 11 | 81 | 6,073.199 | 27,516.252 |
| 3 | numbers_dates_abbreviations | 746,780 | 25 | 200 | 6,084.074 | 47,688.294 |
| 4 | paragraph | 842,604 | 29 | 226 | 6,102.457 | 52,958.745 |
| 5 | repeat_short_success | 137,100 | 5 | 36 | 6,079.825 | 19,357.482 |

Worker exit code was `0`. Per-request PCM SHA-256 values and text hashes are
in the external oracle receipt:
`E:\stage-a-base-evidence\b1-persistent-eos-oracle.json`.
The benchmark receipt with first-audio and real-time metrics is:
`E:\stage-a-base-evidence\b1-persistent-benchmark.json`.

External receipt SHA-256 values are recorded in the machine-readable summary;
the raw files are intentionally not committed.

This run demonstrates persistent sequential use and natural EOS for this small
corpus. It does not claim speech quality or production performance; startup
loading and warm request generation were not independently separated in this
receipt, and resource telemetry was not collected.

## B1-B — cancellation, recovery, and restart

The cancellation harness admitted request 1, waited for its `started` event,
sent `cancel`, and observed exactly one logical terminal message: `cancelled`
(ack latency 2.526 ms). In this worker, `started` is emitted before
`engine.synthesize_stream()` is called. Therefore this run proves protocol
cancellation/recovery, but does **not** prove that GPU generation had begun,
does not measure physical engine unwind, and does not establish when admission
capacity was released. Those three measurements remain **NOT YET VERIFIED**.
A subsequent request 2 in the same worker produced 155,296 PCM bytes and
passed the full natural-EOS oracle. The worker exited cleanly with code `0`.
Receipt: `E:\stage-a-base-evidence\b1-cancel-recovery.json`.

Two fresh worker processes then synthesized the same registered-voice subset.
Both produced 140,940 PCM bytes, reached natural EOS without safety-limit hits,
and exited with code `0`. Receipt:
`E:\stage-a-base-evidence\b1-restart.json`.

These checks cover functional restart and protocol-level cancellation/recovery.
They do not yet include proof of cancellation during confirmed GPU execution,
physical unwind timing, admission-release timing, physical playback, or a
long-horizon resource soak.

## Acceptance matrix

| Gate | Result | Evidence |
| --- | --- | --- |
| B1-A persistent five-request corpus | **PASS** | per-request EOS oracle, PCM hashes, IDs 1–5 |
| B1-B protocol cancellation and recovery | **PASS** | exactly one logical `cancelled`, next request natural EOS |
| B1-B active GPU cancellation / physical unwind | **NOT YET VERIFIED** | `started` precedes engine call; no PCM-before-cancel or unwind timestamp captured |
| B1-B admission release timing | **NOT YET VERIFIED** | deterministic barrier remains the semantic oracle |
| B1-B worker restart subset | **PASS** | two fresh processes, natural EOS, clean exits |
| B1-C C++ physical playback | **NOT RUN** | requires playback receipt and underrun evidence |
| B1-C targeted listening | **NOT RUN** | explicit human review still required |
| B2 clean-portable multi-request/restart/cancel | **NOT RUN** | separate acceptance gate |
| RTX 4090 independent validation | **NOT RUN** | post-freeze gate |

The selected profile remains an experimental synthetic character voice, not a
verified identity claim. No claim of deterministic audio or listening quality
is made by this report.
