# CMP 50HX E4 throughput research

Date: 2026-09-04
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
| Triton FP32 SiLU-times-up elementwise kernel (opt-in) | ~60.2 ms/frame; median ~380 ms for accepted Base/W48 decode | natural EOS, but codec hash changed (`73ebf63c...` vs control); starvation remained (8 later empty-queue observations) | rejected: parity failure and less than 1% gain |
| Async codec-stream prefetch (corrected Base probe) | W33 median ~341.7 ms; codec wrapper residual approximately zero | matching successful run preserved the control codec hash, but a repeat produced a CUDA gather assertion after eight chunks | rejected: intermittent same-GPU graph concurrency failure |
| Talker `max_seq_len=1024` | mean ~322.5 ms; range 315.9–331.6 ms | codec hash matched and the short request happened not to empty the playback queue | rejected: average cadence remains slower than real time |
| Talker `max_seq_len=768` | median 309.2–310.4 ms across three attempts; maximum 313.3 ms | starvation proxy 0; natural EOS; warm-control codec and PCM parity | accepted research candidate |

## Bounded Talker graph capacity

The decisive optimization was reducing the Talker static-cache and attention
capacity from the generic `2048` default to `768`. The tested request used a
Talker prefill length of `237` and terminated naturally after `54` generated
codec frames, so the 2048-position graph was doing unnecessary work on every
AR frame. This change does not alter model weights, dtypes, sampling, codec
window W33, or PCM assembly.

An identical selected-profile-warmup parity pair produced:

| Setting | First PCM | Median inter-arrival | Starvation | Codec / PCM result |
| --- | ---: | ---: | ---: | --- |
| `max_seq_len=2048` | 729.6 ms | 358.5 ms | 11 | control |
| `max_seq_len=768` | 677.6 ms | 311.4 ms | 0 | identical |

Both arms reached natural EOS at 54 codec frames with codec SHA-256
`8b2ef3e7...`. Their captured PCM was byte-identical at 207360 bytes with
SHA-256 `8d011cea...`. A separate three-attempt W768 playback soak reported
zero starvation observations in every attempt; median inter-arrival was
309.2–310.4 ms and the worst observed interval was 313.3 ms.

Persistent-worker validation then completed three different texts in one
process with first PCM between 674.9 and 682.9 ms. The medium request emitted
29 E4 chunks (9.28 seconds of audio), demonstrating useful capacity beyond the
short parity phrase. A separate lifecycle probe completed one request,
cancelled the next after its first PCM chunk, and completed a third request on
the same worker. Cancellation reached its terminal event 1.54 ms after first
PCM and the post-cancellation request completed normally.

`max_seq_len=768` is therefore the first E4/W33 candidate in this investigation
to clear throughput, parity, natural-EOS, cancellation/reset, and persistent
reuse gates. It remains a bounded-utterance profile: callers must split text
before the available sequence budget is exhausted, and a wider multilingual
and long-text soak is still required before release promotion.

For comparison, `384` produced 292.7–299.9 ms inter-arrival and byte-identical
PCM, but gives away unnecessary sequence capacity. `1024` passed one short
playback run only because early chunks accumulated a small reserve; its mean
322.5 ms cadence is not sustainable for longer speech.

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

The research FasterQwen branch contains several opt-in controls:

- `QTB_FASTER_COMPILE_TALKER_ONLY=1` (bridge runner:
  `-CompileTalkerOnly`) isolates Talker compilation from Predictor changes;
- `QTB_FASTER_DROP_PREFILL_HIDDEN_STATES=1` (runner:
  `-DropPrefillHiddenStates`) omits retained per-layer prefill hidden states.
- `QTB_FASTER_FORCE_SDPA_EFFICIENT=1` (runner:
  `-ForceSdpaEfficient`) forces PyTorch's efficient SDPA backend during graph
  capture when the sealed runtime provides a compatible kernel.
- `QTB_FASTER_MLP_TRITON_SILU_MUL=1` (runner: `-TritonMlpSiluMul`) compiles an
  optional Triton kernel before CUDA-graph capture. It removes the two
  FP16-to-FP32 staging copies and fuses the FP32
  `sigmoid(gate) * gate * up` elementwise sequence for predictor layer 2. The
  isolated CMP microbenchmark improved from roughly `0.265` to `0.060 ms`, but
  Triton sigmoid rounding changed the autoregressive codec trajectory and did
  not approach the 13% end-to-end target. Keep this switch diagnostic-only.
- `QTB_FASTER_ASYNC_CODEC_DECODE=1` (runner: `-AsyncCodecDecode`) runs the AR
  iterator in a bounded producer thread and submits right-padded codec work on
  a separate CUDA stream. The first Base measurements did not exercise this
  branch. After connecting the Base reference-context path, W33 cadence fell to
  about 341.7 ms and codec residual was hidden, but a repeat hit an intermittent
  out-of-bounds CUDA gather assertion after eight chunks. Keep this switch
  rejected and disabled.
- Runner `-MaxSeqLen 768` passes the existing worker `--max-seq-len` control to
  FasterQwen. It bounds Talker static-cache/attention capacity and is the
  accepted research candidate for short assistant/avatar utterances. The
  runner default remains `2048` so unrelated profiles do not change silently.

Nsight Systems 2026.4.1 generated reports under WDDM but recorded no CUDA
kernel or GPU-trace rows, including a direct sealed-Python run with injection
shared memory enabled. Phase-event timings were therefore retained as the
profiling evidence. A GTX 1060 codec-offload probe was also blocked: the sealed
PyTorch 2.10/CUDA 12.8 runtime supports `sm_70` and newer, while that GPU is
`sm_61` and was not exposed as a usable CUDA device.

The implementation is split across FasterQwen commits `040e999` and
`fbd751b`, with the later sampling optimization in the follow-up branch;
these are research-branch commits and are not a production
submodule promotion.

None of the rejected controls is enabled by a release profile. The runner also
keeps `max_seq_len=2048` as its default. The accepted E8 + W33 path continues
to use the numerically accepted eager/SDPA decode graphs.

## Next work

The 13% throughput target is met for bounded utterances by the W768 Talker
graph without changing sampling or increasing prebuffer. The next step is to
promote it as an explicit low-latency profile only after defining text-splitting
and sequence-budget behavior, then run multilingual and longer playback soaks.
The generic `2048` default and the accepted E8/W33 release profile remain
unchanged until that promotion decision is made.
