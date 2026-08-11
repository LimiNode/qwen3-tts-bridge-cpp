# CMP 50HX: frozen C acceptance status

## Decision

Candidate C is **correctness-qualified and conditionally accepted as the frozen diagnostic baseline**. It is not promoted to R4/runtime: the previously observed sustained GPU-timeline stalls still lack a CUDA timeline captured during the event.

No model, precision-boundary, scheduler, E/W, compile/graph-policy, `down_proj`, or playback change is authorized by this status.

## Frozen boundary

- Layer-2 `gate_proj` and `up_proj`: FP16.
- Layer-2 product and `down_proj`: FP32.
- Residual carrier and RMSNorm: FP32.
- Normalized branch returned to attention/MLP GEMMs: FP16.
- Normal Faster internal CUDA graphs; no eager numerical trace or graph finite checker.

The wide A control remains disqualified. Its FP32 `down_proj` can exceed the finite FP16 range when returned to the branch (`66,078.6 > 65,504`), so it is not a numerically valid alternative to C.

## Correctness evidence

The paired multiseed study recorded **9/9 natural-EOS** C runs on normal Faster CUDA graphs. Provenance recorded `carrier_active=true`, `faster_internal_graphs_active=true`, `eager_numerical_trace=false`, and `graph_finite_checker_active=false`.

See [paired multiseed study](cmp50hx-faster-narrow-l2-paired-multiseed-2026-08-09.md) and [boundary diagnostic](cmp50hx-faster-boundary-and-stall-diagnostic-2026-08-09.md).

## Bounded real-time validation

On 2026-08-11, six fresh C workers ran the fixed medium request under the CUDA-only stall gate. All six completed naturally (EOS), emitted 29 PCM chunks, and met the gate's normal-path condition.

| Metric | Observed range |
| --- | --- |
| RTF | 0.965–0.975 |
| Maximum inter-chunk gap | 621.833–652.175 ms |
| Gaps above 2 s | 0 in every run |
| Sustained-stall captures | 0 |

The gate labels a run sustained only when `RTF >= 3.0` and at least three inter-chunk gaps exceed two seconds. No run met that condition, so it correctly did not create a new Nsight trace. These results are bounded real-time observations, not a general performance-promotion claim.

Raw gate decisions: [JSONL](cmp50hx-cudaonly-stall-gate-auto.jsonl).

## Sealed package verification

Both manifest verifiers were run foreground to a real exit code. The package tree and voice-assets verifiers returned `0` on 2026-08-11. The status artifact records the package marker and manifest digest.

Before the successful run, 49 generated Python `.pyc` cache files were removed from the sealed package tree. They are forbidden by the package-tree manifest and are not packaged source, model, or manifest content. No source, model, or manifest was changed.

Verifier status: [JSON](cmp50hx-customvoice-ab-post-manifest-status.json).

## Open incident and capture rule

`stalled-v2` remains valid evidence of a sustained GPU-timeline degradation (RTF 8.582; 27 of 28 inter-chunk gaps above two seconds). It is not explained by host/IPC residuals, but the current evidence cannot distinguish long work in this CUDA context from WDDM/context scheduling gaps.

The bounded `tmp/run-cmp50hx-cudaonly-stall-gate.ps1` is retained as the diagnostic trigger. During a future real TTS/session run, it will automatically launch a CUDA-only Nsight capture only after the sustained-stall condition is reproduced. If that trace shows GPU gaps, the next diagnostic is a separate short GPUView/ETW capture; do not repeat the failed full CUDA+WDDM Nsight capture.
