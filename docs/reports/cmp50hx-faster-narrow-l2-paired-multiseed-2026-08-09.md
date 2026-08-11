# CMP 50HX: paired A/C multiseed performance study

## Verdict

**No promotion decision.** Candidate C remains the correct external diagnostic boundary, but this study does not establish a stable realtime or cross-seed performance advantage.

All nine C runs reached natural EOS with normal Faster CUDA graphs and the frozen narrow boundary. The wide-island A control did not: all three seed-20260806 A runs terminated unsuccessfully after 14 PCM chunks with a CUDA `TensorCompare.cu` device assertion. A also had large synthesis-wall outliers for seed 20260807 A3 and seed 20260808 A2. Those outcomes make a clean three-seed A/C performance estimate impossible; they must not be discarded or silently retried.

No R4/runtime change, `down_proj` change, scheduler/E/W change, compile/graph-policy change, or playback change was made.

## Method

- Seeds: 20260806, 20260807, 20260808.
- Three fresh-worker A and C runs per seed; one identical warmup per worker.
- Interleaved order: 806 `A C C A A C`; 807 `C A A C C A`; 808 `A C C A A C`.
- A: graph-compatible FP32 carrier with wide L2 FP32 gate/up island.
- C: the same carrier with L2 FP16 gate/up and FP32 product/down/residual/RMSNorm tail.
- Normal Faster CUDA graphs only; eager trace and finite checker disabled.
- Primary metric: worker synthesis wall divided by codec frames. RTF, frame count, audio duration, and TTFA are secondary observations.

The harness now turns a benchmark-reported unsuccessful terminal request into a nonzero harness exit for future runs. The first three A-806 artifacts predate that safeguard, so their worker process exit is `0` even though their raw request result is `success=false`; they are correctly excluded from valid performance samples.

## Individual results

| Seed | Run | Terminal | Frames | Audio ms | Worker ms/frame | RTF |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| 806 | A1 | failed after 14 chunks | — | 8,936.875 | — | 2.766 |
| 806 | C1 | EOS | 199 | 15,896.875 | 98.013 | 1.227 |
| 806 | C2 | EOS | 199 | 15,896.875 | 79.490 | 0.995 |
| 806 | A2 | failed after 14 chunks | — | 8,936.875 | — | 5.404 |
| 806 | A3 | failed after 14 chunks | — | 8,936.875 | — | 3.148 |
| 806 | C3 | EOS | 199 | 15,896.875 | 79.272 | 0.993 |
| 807 | C1 | EOS | 193 | 15,416.875 | 82.530 | 1.033 |
| 807 | A1 | EOS | 193 | 15,416.875 | 103.824 | 1.300 |
| 807 | A2 | EOS | 193 | 15,416.875 | 82.641 | 1.035 |
| 807 | C2 | EOS | 193 | 15,416.875 | 83.296 | 1.043 |
| 807 | C3 | EOS | 193 | 15,416.875 | 83.006 | 1.039 |
| 807 | A3 | EOS | 193 | 15,416.875 | 678.160 | 8.490 |
| 808 | A1 | EOS | 190 | 15,176.875 | 82.347 | 1.031 |
| 808 | C1 | EOS | 211 | 16,856.875 | 82.049 | 1.027 |
| 808 | C2 | EOS | 211 | 16,856.875 | 82.096 | 1.028 |
| 808 | A2 | EOS | 190 | 15,176.875 | 341.241 | 4.272 |
| 808 | A3 | EOS | 190 | 15,176.875 | 82.367 | 1.031 |
| 808 | C3 | EOS | 211 | 16,856.875 | 82.224 | 1.029 |

## Interpretation

For seed 806, there is no valid A-side comparison: the repeated A failure is itself an important result, while C is 3/3 EOS. For seeds 807 and 808, C is internally tight but not below RTF 1: 807 C is 1.033–1.043 and 808 C is 1.027–1.029. The 808 C worker ms/frame is stable at 82.049–82.224, so its RTF above one is consistent with the seed's different 211-frame/audio trajectory rather than a per-frame C slowdown.

The A outliers cannot be removed as noise. In particular, A3/807 and A2/808 retain natural EOS but have much larger synthesis wall, while the nearby A or C runs do not. Consequently, an aggregate A median would be dominated by the unstable control and would overstate C's benefit. The earlier fixed-seed 4.43% latency reduction / 4.63% throughput-equivalent speedup remains a local observation, not a multiseed claim.

Across all valid C runs, 9/9 reached EOS. Their observed RTF range is 0.993–1.227 and their median is 1.029; only 2/9 are below RTF 1. This fails the desired stable-realtime promotion criterion even though C remains numerically robust.

## Artifacts

Each run has a `paired-ms-s<seed>-<variant><ordinal>` raw JSON and provenance JSON under `docs/reports/`. The provenance confirms `carrier_active=true`, `faster_internal_graphs_active=true`, `eager_numerical_trace=false`, and `graph_finite_checker_active=false`; C has `layer2_mlp_variant=narrow_gate_up_fp16`, while A has `wide_gate_up_fp32`.

## Next safe action

Freeze the C boundary and treat the wide A seed-806 failure as an investigation result, not as an opportunity to alter C or `down_proj`. Do not promote C to R4/runtime on this study. A future performance experiment requires a demonstrably stable, EOS-complete control and a controlled explanation for the large synthesis-wall interruptions before drawing a general realtime conclusion.

The follow-up localizes the A failure to the wide FP32-down-to-FP16 return cast and shows that the C wall outliers are GPU-timeline stalls. See [the boundary and stall diagnostic](cmp50hx-faster-boundary-and-stall-diagnostic-2026-08-09.md).
