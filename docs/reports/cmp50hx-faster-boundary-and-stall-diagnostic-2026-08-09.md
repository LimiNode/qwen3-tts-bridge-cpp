# CMP 50HX: wide-A boundary failure and C stall diagnostic

## Verdict

Two bounded diagnostics refine the multiseed result.

1. Wide A's deterministic seed-20260806 failure is an FP32-to-FP16 return-boundary overflow, not a failure of the FP32 gate/up or down computation itself.
2. The rare large C synthesis-wall stalls are GPU-timeline stalls, not host-side dispatch or CPU/CUDA synchronization residuals. They are not explained by thermal downclock in the sampled run.

Neither result authorizes a performance claim or an R4/runtime change. C's narrow boundary remains frozen.

## A/20260806 finite-boundary reproduction

One normal Faster CUDA-graph run used wide A (FP32 L2 gate/up/product/down, FP32 carrier/RMSNorm, FP16 returned branch) with the graph finite checker. The checker adds a diagnostic-only safe-probability fallback so an invalid probability row cannot destroy the CUDA context before aggregates are written; this run is not performance evidence.

| Request | Result |
| --- | --- |
| Warmup | EOS, 240 predictor replays, all observed boundaries finite |
| Measured A/806 | EOS only because of diagnostic sampling repair; first anomaly at predictor replay 115 |

The first anomalous boundary is `layer2_output_fp16`. At that point:

```text
L2 gate_fp32 / up_fp32 / SiLU product / down_fp32    finite
down_fp32 maximum                                  66,078.6016
L2 output_fp16                                     +Inf
L2 FP32 residual, RMSNorm, normalized branch       non-finite afterwards
predictor logits and probabilities                 non-finite afterwards
```

The IEEE FP16 finite maximum is 65,504. The wide island returns `down_fp32` to the model's FP16 branch dtype, so this cast is the first observed overflow. Keeping a wider FP32 compute island therefore does not make the complete autoregressive boundary safer when its result is later returned to FP16. This explains the reproducible A-806 failure after 14 PCM chunks and strengthens the rationale for treating precision as a trajectory-dependent boundary, not a monotonic "more FP32 is safer" rule.

The proof records zero observations for `layer2_gate_fp16` and `layer2_up_fp16`, and 3,075 observations for their wide FP32 counterparts: the dtype coverage is explicit rather than inferred.

## C/20260806 stall telemetry

The unchanged narrow C path was run four times on fresh workers with opt-in telemetry only. It adds one CUDA event pair around each PCM-chunk generator advance and reads elapsed time only when the end event is already ready; it does not synchronize the host or alter graph replay. `stream_next_host_residual_ms` is host wall minus that GPU event interval.

| Run | RTF | Worker ms/frame | GPU event median / max per chunk | Host residual median / max |
| --- | ---: | ---: | ---: | ---: |
| v1 | 0.981 | 78.377 | 621.127 / 735.123 ms | 0.167 / 0.243 ms |
| v2 | 6.143 | 490.457 | 629.440 / 18,386.102 ms | 0.183 / 0.396 ms |
| v3 | 9.898 | 790.466 | 7,277.373 / 8,729.730 ms | 0.163 / 53.748 ms |
| v4 | 14.906 | 1,190.389 | 10,828.688 / 19,786.025 ms | 0.138 / 60.207 ms |

The event and host times track closely. For example, v2's 18.386-second chunk has less than 0.4 ms of host residual; v4's 19.786-second maximum has less than 61 ms. The stalls therefore occur on, or while waiting in, the GPU stream timeline, rather than in PCM conversion, Python dispatch, or a host synchronization boundary.

For v4, independent 1 Hz `nvidia-smi` samples show a 45–51°C GPU temperature and fixed 1,875 MHz graphics/SM clocks during the run. Power ranged approximately 88–137 W and sampled utilization varied, but there is no evidence of a simple thermal or clock-throttling explanation. The one-second samples cannot distinguish driver scheduling, foreign GPU work, or a lower-level GPU/runtime stall; deeper external GPU tracing would be needed for that distinction.

## Changes retained

- Graph finite checker now covers both narrow FP16 gate/up and wide FP32 gate/up, and records the first anomalous component/replay without per-replay host synchronization.
- The checker explicitly observes the L2 FP16 returned branch, which is the decisive A-806 boundary.
- The pair harness treats raw terminal `success=false` as a nonzero harness result.
- Stall telemetry and GPU sampling are opt-in diagnostics only.

## Next safe action

Do not change `down_proj`, scheduler/E-W, compile/graph policy, playback, or C's precision boundary. Do not resume a broad A/C performance study: wide A is now known to be numerically invalid on A-806.

Before optimizing C, use an external GPU profiler or equivalent driver-level tracing to separate GPU scheduling/contending work from model-kernel execution during the demonstrated GPU-timeline stalls. Only then choose an optimization target for the remaining few percent on stable C trajectories.
