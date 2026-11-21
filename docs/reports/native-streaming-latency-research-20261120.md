# Native streaming latency: source comparison and retained baseline

Date: 2026-11-20. Status: **research, not an optimization or acceptance PASS**.
No engine, runtime, dependency pin, sampler, or frozen package was changed.
No new GPU measurement is claimed here. R1 remains **NO-GO**; producing PCM
faster does not establish complete or correct speech.

## Identities and independent source inspection

The retained measurement used bridge
`aa2770ec8aeb45d59f42c96c3a1f4f2dc52390d8`, qwentts
`130cb99af9ae12d554962fd0920e08fb4268af01` (ABI 6), RU-stress Base 1.7B
Q8_0, and the registered Kraftwerk ICL reference on CMP 50HX, UUID
`GPU-40361931-6cb5-ac58-a059-5ba3e70986fb`. It used the same complete
22-token abbreviation text as the seeded early-EOS investigation in
[PR #330](https://github.com/LimiNode/qwen3-tts-bridge-cpp/pull/330).

External source, not just README claims, was inspected at immutable revisions:

- [speech.cpp `8d18924cd238b87c0297df112f7ff40783a6414f`](https://github.com/nyosegawa/speech.cpp/tree/8d18924cd238b87c0297df112f7ff40783a6414f),
  committed 2026-11-15: Qwen synthesizer, Talker, graph sampler, codec,
  shared Qwen decoder, prompt builder, timing executable, and model/chunk ADR.
- [C CUDA study `ef339be58a778b062e1c14382347964552eae007`](https://github.com/gabriele-mastrapasqua/qwen3-tts/tree/ef339be58a778b062e1c14382347964552eae007),
  committed 2026-09-25: CUDA performance document, Talker/Code Predictor,
  resident decoder, CUDA seam, and Makefile.

Downloaded sources are local-only under
`.tmp/streaming-eos-research/latency/`. Selected SHA-256 fingerprints:

| Pinned external file | SHA-256 |
| --- | --- |
| speech `src/families/qwen3-tts/synthesizer.cpp` | `3ff1f67b06d42f9764a5789c616fe7cf1cfe07b7413b376f1a7452b4a34dd6c9` |
| speech `src/families/qwen3-tts/talker.cpp` | `6b4e030499735487d734f48d975dc4fd708e1310edb1119150e1e237e2ab3e1a` |
| speech `src/families/qwen3-tts/codec.cpp` | `f3c425873c4c01df8f975b549b35fbd4fd451897f6acec88223d70b7dcbf04b1` |
| speech `measure/qwen3-tts-timing.cpp` | `45fe5807968de3c6ccc559fa0b1fc087e80ff0b21f365af5f964d59b17c48348` |
| C study `docs/cuda-performance.md` | `b93a3eb191fd707e0faebd862a629c4229211aa9a7319cbe136aaa3187b2612c` |
| C study `qwen_tts_cuda_talker.cu` | `431b3473a78b3b03828b6ddc8bb6f57390617d370e2f8f4cd254862187d73b12` |
| C study `Makefile` | `f30190de704699fdff2be13ad9da2b73a695e6baa92513fb116c01de4ef3123f` |

## What is applicable

| Mechanism | Source findings and existing native owner | Classification / next action |
| --- | --- | --- |
| Persistent Talker KV and graphs | speech `Qwen3Decoder` owns KV/allocation and kept chains. Native `talker-forward.h:631` already owns static decode graphs, backend KV, and a backend hidden bridge. | Already implemented; do not add a parallel cache/graph layer. |
| One GPU graph for the 15 Code Predictor steps | speech `Talker::Frame` chains device sampling and reads the chosen codes once. Native `code-predictor-forward.h:377` already builds the unrolled graph and `:454` uploads sampler state and reads one code accumulator. | Already implemented; measure replay/capture effectiveness, not a feature port. |
| Host transfers | speech Talker reads logits and hidden back (`qwen3-decoder.cpp:440`); native normally keeps the hidden bridge on-device, reads Talker logits for sampling, and reads the predictor's final codes once. Native dump mode adds substantial readbacks. | Partially different; source does not show a missing 15-sync optimization. Trace/dump timing is not a clean performance baseline. |
| Persistent codec state | speech `CodecDecoder` owns backend convolution/KV state. Native `pipeline-codec.cpp` already owns backend stream state, static stream graphs, and ICL codec-state snapshot/restore. | Already implemented, including reference priming. No full-prefix codec re-decode port is needed. |
| First/later codec chunks | speech `chunk_frames()` returns `1,1,2,4,4,...`; native `pipeline-tts.cpp:1939` doubles `1,2,4,8,8,...`, capped by an existing option. | Missing alternative schedule; controlled experiment warranted, not a default change. Both start with one frame, so this alone cannot remove the first prefill. |
| Flash Attention | Both use GGML flash attention where selected; native load log says `fa=on`. speech probes backend op support before selection. | Present, but log selection is not proof of every CUDA kernel used on sm_75. Profile actual GPU execution before a kernel change. |
| Prompt/reference work | speech builds a short named-speaker CustomVoice prompt. Native ICL builds a 236-row context in this run and performs Talker prefill for every request (`pipeline-tts.cpp:1273`). Native already caches registered reference extraction and codec state. | Different workloads; measured prefill is the main TTFA candidate. Safe reusable Talker-prefix KV would require proof of identical prefix, positions, and conditioning, not reuse of all previous request KV. |
| Fused/resident CUDA C engine | The C study has captured Talker/CP steps and a resident decoder, but also explicit host copies and sync points. Native already has resident GGML weights/state and captured/static graphs. | Partly implemented conceptually; not an ABI-compatible replacement or evidence of an unimplemented whole GPU pipeline. |
| Mixed quantization / dp4a | The C study's q4×q8 activation kernel and mixed weights alter arithmetic and can change trajectories. Its document explicitly acknowledges trajectory changes. Native Q8_0 is the frozen control. | Separate quality/parity research, not a free speed fix. No quantization change in this batch. |
| C study deployment | Its Makefile defaults to sm_80/86/89/120 plus compute_120 PTX. The bf16 WMMA path is guarded for sm_80+. Neither includes the CMP's sm_75 target. | Incompatible as a drop-in CMP binary; a specific Turing port and full correctness qualification would be necessary. |
| Multi-request batching | The C study emphasizes batch throughput and explicitly separates its unqualified CUDA server. Native already supports batched slots; this baseline is batch 1. | Not a justified interactive single-stream latency change. Keep one inference stream while measuring. |

The [speech model page](https://github.com/nyosegawa/speech.cpp/blob/8d18924cd238b87c0297df112f7ff40783a6414f/docs/models/qwen3-tts.md)
explicitly excludes Base voice cloning and VoiceDesign. Its 32 ms p50 / 46 ms
p90 first-chunk result and 4.2x realtime use CustomVoice Q8_0, Japanese texts,
`ono_anna`, and RTX 2080 Vulkan. They are author-reported measurements, not
our reproduced result or a directly comparable RU-stress/ICL performance target.

The [chunk ADR](https://github.com/nyosegawa/speech.cpp/blob/8d18924cd238b87c0297df112f7ff40783a6414f/docs/adr/synthesis-passes-audio-in-chunks-fixed-for-qwen3-tts-and-sized-by-speed-for-irodori-tts.md)
chooses `1,1,2,4` to avoid early underruns and bound cancellation chunks. It
also records grouping-dependent floating-point PCM differences. Therefore
schedule changes require same-seed code comparison, repeated-run determinism,
sample/continuity analysis, actual player underruns, and scoped listening.

The [C CUDA report](https://github.com/gabriele-mastrapasqua/qwen3-tts/blob/ef339be58a778b062e1c14382347964552eae007/docs/cuda-performance.md)
warns that bandwidth scaling does not predict single-stream latency reliably:
its A100 measurement did not reach the extrapolated RTF. The RTX 4090 table
entry is an estimate, not a measured 4090 acceptance result. Do not promote
its "ear-validated" arithmetic changes into our stress/voice quality claim.

## Retained CMP latency decomposition

Input dataset, unchanged:
`.tmp/base-acceptance/native-r1-aa2770ec-20261120/diagnosis/short-eos-seed-sweep-001/scan-000-031/benchmark.json`.
Size 91,897 bytes; SHA-256
`31739bca62a0ed629c26bad726dc65c45fbdb181a59e39a6f2b609b2b070250a`.

This was a seed-discovery run with full-AR text tracing, no explicit warmup,
max 256 tokens, and seeds 0..31, not a fresh production benchmark. Request 1
(seed 0) contains first-use initialization and is excluded from warm results.
The five <=12-frame early-EOS candidates remain in the failure evidence, not
silently counted as fast successful speech. The main table uses the remaining
26 warm, non-short requests. "Non-short" does **not** establish spoken coverage.
Median averages the middle pair; p95 is nearest-rank `ceil(0.95*n)`.

| Boundary / phase | p50, ms | p95, ms |
| --- | ---: | ---: |
| Client request to first PCM | 179.224 | 179.789 |
| Native prompt construction | 5.745 | 6.403 |
| Talker prefill | 153.069 | 153.196 |
| Native entry to first complete codec-frame codes | 170.553 | 171.101 |
| Native entry to first PCM callback | 178.719 | 179.278 |
| Callback minus first codes, paired residual | 8.122 | 8.229 |
| Client first PCM minus native callback, paired residual | 0.512 | 0.594 |
| Entire request to terminal | 2128.019 | 2276.996 |

Warm-all (31 requests, including early failures) client TTFA is p50 179.231 /
p95 180.870 ms. The excluded first-use request has TTFA 1401.685 ms and total
4019.806 ms; startup to ready is separately 8278.472 ms. It is not a cold disk
or OS-cache benchmark. The non-short warm RTF is p50 0.2955 / p95 0.2990.

The per-request prefill/client-TTFA ratio has median **85.41%**. This locates
the largest measured first-PCM span in this workload; it does not establish
which prefill kernel, attention operation, allocation, or synchronization
accounts for it. All registered-reference extraction/decode fields are zero
because preload occurred before ready, not because reference preparation was
free in the process lifetime. Native context is 236 rows despite 22 target
text tokens; named-speaker CustomVoice is not a prefill-equivalent control.

Whole-request phase medians are Talker 540.777 ms, predictor 961.411 ms, codec
455.394 ms; per generated frame they are 5.995, 10.656, and 5.087 ms. These
are accumulated wall-clock spans, not first-frame breakdowns or a sum of
independently measured GPU kernel time. Phase quantiles must not be added
into a synthetic request waterfall. Predictor throughput remains interesting,
but is not the dominant measured delay before the first codes in this run.

## Next controlled experiments and missing measurements

1. Preserve immediate streaming, original sampler, and the existing chunk
   schedule as controls. Rerun a prespecified corpus/seed matrix without full
   dumps or verbose per-frame tracing for performance. Separate first request,
   fresh worker, and warm persistent-worker distributions; retain all failures.
2. Instrument the first prefill, first predictor graph, first codec graph,
   callback/enqueue/flush, and client arrival with same-request spans. Use
   GPU timing/profiling separately: wall time and CUDA execution time are not
   interchangeable. The ABI currently exports only accumulated predictor and
   codec spans, not those first-frame subspans.
3. Investigate prefill on the actual 236-row ICL context first: execution
   backend, graph allocation/capture, shape, transfers, and any safely
   reusable reference prefix. Check numerical/forced-history parity before
   changing precision, caching, or kernels.
4. Compare `1,2,4,8` with fixed `1,1,2,4` only on a distinct experimental engine
   build; the existing cap option does not express a repeated initial `1`.
   Measure second-chunk gap and physical starvation, not merely callback TTFA.
5. Evaluate startup gates against the actual frame/chunk timing and terminal
   order. Waiting until three frames have arrived is not the same as observing
   the next step's EOS; no irreversible PCM release may precede that decision
   if the aim is to hide a three-frame failure. Retries must not reuse a fresh
   deadline or replay previously committed PCM.

Not measured here: frontend time, individual first predictor/codec execution,
stdout writer/transport subspans, first non-silent sample, physical first
audible sound, prospective gate overhead, peak memory/VRAM, optimized runtime,
or independent RTX 4090 results. The ~0.5 ms callback/client residual is a
paired wall-clock difference, not a direct measurement of IPC alone. A
separate physical playback/listening receipt remains required. This source
audit and reanalysis do not close any R1 release or listening gate.

The companion [early-EOS detector replay](native-early-eos-detector-replay-20261120.md)
quantifies fixed startup-horizon costs and shows that simple 1/2/3-code risk
prefixes do not generalize reliably even to the held-out seeds of this same text.
