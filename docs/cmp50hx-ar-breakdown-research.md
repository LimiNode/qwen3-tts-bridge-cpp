# CMP 50HX AR first-E8 breakdown

Date: 2026-09-02  
Profile: registered 1.7B Base voice, E8, W48 right-padded codec decode,
manual codec CUDA Graph, reference-context bootstrap, playback prebuffer 1.

This research branch adds optional per-frame telemetry. Production defaults and
sampling policy are unchanged.

## Per-frame timing

In one fixed-seed run, the first eight AR frames were measured without adding a
synchronization boundary. GPU events were resolved at the existing first-chunk
flush synchronization; host wall time covers the corresponding frame loop.

| Measure | Sum (8 frames) | Median/frame | Range/frame |
| --- | ---: | ---: | ---: |
| AR GPU elapsed | 504.6 ms | 63.0 ms | 62.6–63.8 ms |
| AR host wall | 508.8 ms | 63.5 ms | 63.1–64.4 ms |
| PredictorGraph | 220.8 ms | 27.6 ms | 27.3–27.9 ms |
| TalkerGraph | 260.5 ms | 32.6 ms | 32.5–32.6 ms |

The remaining GPU phases are small: codebook embedding gather, logits
preparation, sampling, and state update together account for roughly 23 ms.
The host/GPU gap is about 4 ms over the first E8, so this run is primarily
GPU-math-bound. TalkerGraph is the largest individual component, but neither
graph alone explains a large launch-bound loss.

## Predictor output A/B

`PredictorGraph.run()` now has an opt-in diagnostic mode that returns its static
output buffer instead of cloning it. The caller consumes the tensor on the same
CUDA stream before the next replay, so the view is safe for this sequential
path; chunk storage still copies the values.

| Mode | First PCM | AR decode | Starvation proxy | PCM/token result |
| --- | ---: | ---: | ---: | --- |
| clone (control) | 1040.9 ms | 504.6 ms | 0 | reference |
| static output view | 1037.0 ms | 504.3 ms | 0 | byte-identical PCM and identical codec hash |

The observed ~4 ms first-PCM difference is within normal run-to-run variance;
the GPU phase totals are effectively equal. Keep the optimization diagnostic
only until a larger A/B sample demonstrates a repeatable benefit. The default
remains the cloning behavior.

## Next research priorities

The measurements support the following order:

1. Profile/optimize TalkerGraph and its input preparation, because it is the
   largest AR component.
2. Prototype a fixed `FirstE8Graph237` only after proving that graph capture can
   preserve EOS, sampling, static-cache state, and cancellation semantics.
3. Test compile only inside the existing tiny decode graphs, never across the
   whole generation loop.
4. Treat AR/codec overlap as a steady-state optimization; it cannot remove the
   first codec decode from E8 first PCM.

W33, compiled prefill, and production cadence were not changed by this branch.
Raw run directories remain under `tmp/` and are intentionally unversioned.

## FirstE8Graph capability probe

Before attempting a `BaseFirstChunkGraph237E8` implementation, a minimal CUDA
probe tested whether PyTorch permits replaying an already-captured graph while
an outer `torch.cuda.graph(...)` capture is active. On the packaged runtime
(PyTorch `2.10.0+cu128`, NVIDIA CMP 50HX), the probe failed with:

```text
RuntimeError: Cannot prepare for replay during capturing stage.
```

This rules out composing the existing `PredictorGraph` and `TalkerGraph` by
simply wrapping their `replay()` calls in a new outer graph. A true FirstE8
prototype would have to duplicate/unroll both graph bodies, sampling, cache
updates, EOS handling, and cancellation inside one capture. That is a separate
high-risk implementation, not a scheduling-only change, and was deliberately
not attempted in this research pass.

The current evidence therefore favors optimizing the existing TalkerGraph and
its input preparation, or compiling only the tiny decode backbones before graph
capture. Both should remain opt-in experiments with the same codec-token,
natural-EOS, PCM-parity, and starvation gates.
