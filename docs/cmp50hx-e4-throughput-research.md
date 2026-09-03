# CMP 50HX E4 throughput research

Date: 2026-09-03  
Target: make `E4 + W33` sustain 320 ms PCM chunks in real time.

## Gate

The E4/W33 control produces a 320 ms chunk in roughly 363–366 ms. Buffering
cannot repair that deficit: it only moves the first queue-empty event later.
The producer therefore needs at least a 13% end-to-end throughput improvement,
and every candidate must retain fixed-seed codec-token parity, natural EOS,
PCM quality, cancellation/reset, and persistent-worker reuse.

## Candidates tested

| Candidate | AR timing / inter-arrival | Parity and playback result | Decision |
| --- | ---: | --- | --- |
| E4 + W33 control | ~62.3 ms/frame; 363–366 ms | reference codec stream; starvation proxy non-zero | control |
| Drop prefill hidden-state history (opt-in) | unchanged at ~62.3 ms/frame; 364–366 ms | no sustained-rate gain observed | rejected |
| Keep TalkerGraph output as a static view (safe path) | no repeatable improvement isolated | same generation semantics; no 13% gain | retained as a small allocation optimization |
| `torch.compile` TalkerGraph only (opt-in) | 58.45 ms/frame; 345–348 ms | natural EOS, but codec stream differed (64 steps vs control's 66) | rejected |
| CMP matmul precision `high` (one run) | ~62.0 ms/frame; 362–365 ms | no throughput or parity advantage | rejected |

The Talker-only compile probe reduced AR time by about 5.8%, but the resulting
codec-token stream was not parity-equivalent and the producer was still about
8% slower than real time. It is therefore diagnostic-only. Compiling both
PredictorGraph and TalkerGraph remains rejected for the same parity reason
recorded in [the AR breakdown](cmp50hx-ar-breakdown-research.md).

## Implementation notes

The research FasterQwen branch contains two opt-in controls:

- `QTB_FASTER_COMPILE_TALKER_ONLY=1` (bridge runner:
  `-CompileTalkerOnly`) isolates Talker compilation from Predictor changes;
- `QTB_FASTER_DROP_PREFILL_HIDDEN_STATES=1` (runner:
  `-DropPrefillHiddenStates`) omits retained per-layer prefill hidden states.

Neither control is enabled by a release profile. The default E8 + W33 path
continues to use the numerically accepted eager/SDPA decode graphs.

## Next work

The remaining credible path to the 13% target is a numerically controlled
kernel-level optimization of the Talker and Predictor decode graphs (or a new
single-capture graph), followed by the full parity and playback gate. Changes
to sampling, cadence, or prebuffer are not throughput fixes.
