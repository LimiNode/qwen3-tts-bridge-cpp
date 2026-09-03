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
| Hybrid `E4 → E8` (one run) | first PCM ~727 ms; transition ~612 ms | one starvation event at the 320→640 ms chunk boundary | rejected as a prebuffer=1 fix |
| Forced efficient SDPA kernel (opt-in) | ~62.4 ms/frame; 361–367 ms | no measurable gain; starvation remained | rejected |
| GPU-only repetition-penalty mask | ~60.8 ms/frame; 354–356 ms in one E4 run | codec hash matched control; still slower than 320 ms real-time | retained, but insufficient alone |
| Disable CMP precision-diagnostic hooks (opt-in) | ~59.7 ms/frame; 351–354 ms | codec hash changed (`3938b445…` vs control); parity failed | rejected |
| Fused gate/up FP16 GEMM with FP32 tail (opt-in) | ~61.6 ms/frame; 354–357 ms | codec hash matched control (`c2e1c66d…`), natural EOS | rejected: no speed gain |

The precision-hook A/B was also captured as raw PCM on the same fixed-seed
request. The control produced `4160 ms` of audio and the hook-disabled arm
produced `4000 ms`; their common-prefix SNR was only about `4.0 dB` (maximum
sample delta `11186`). This is an audible trajectory change, not harmless
round-off, and confirms why the hash gate is strict.

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
- `QTB_FASTER_FORCE_SDPA_EFFICIENT=1` (runner:
  `-ForceSdpaEfficient`) forces PyTorch's efficient SDPA backend during graph
  capture when the sealed runtime provides a compatible kernel.

The implementation is split across FasterQwen commits `040e999` and
`fbd751b`, with the later sampling optimization in the follow-up branch;
these are research-branch commits and are not a production
submodule promotion.

Neither control is enabled by a release profile. The default E8 + W33 path
continues to use the numerically accepted eager/SDPA decode graphs.

## Next work

The remaining credible path to the 13% target is a numerically controlled
kernel-level optimization of the Talker and Predictor decode graphs (or a new
single-capture graph), followed by the full parity and playback gate. Changes
to sampling, cadence, or prebuffer are not throughput fixes. The hybrid cadence
confirms the boundary: an E4 first chunk can be heard sooner, but the following
E8 chunk arrives after that 320 ms reserve is exhausted.
