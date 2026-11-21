# Native prefill latency study

Status: active research; measurements pending. Date: 2026-11-21.

## Scope and controls

The question is whether the approximately 153 ms warm Talker prefill on CMP
50HX can be reduced without silently changing text coverage, EOS, or audio.
This is not release qualification. The R1 package, Bridge engine pin, ABI,
sampler defaults, and normal build remain unchanged.

The isolated engine worktree is `research/prefill-latency`; the Bridge evidence
worktree is `research/native-prefill-latency`. Payloads are retained under
`.tmp/base-acceptance/prefill-latency-20261121/`. All hardware runs select CMP
UUID `GPU-40361931-6cb5-ac58-a059-5ba3e70986fb`; no RTX result is inferred.

Test the unchanged computation with observation disabled and enabled first.
Then vary only one factor: final-row norm/head, Talker F16 KV, attention
alignment 64 instead of 256, or one compatible retained prefill graph.
Test the combination separately. The final baseline repeat bounds drift.
Use identical case order, exact seeds and UTF-8 input/conditioning bytes.
Keep cold first-use separate from twelve warm same-input pairs per process.
The additional A/A, A/B/A, long/short, language, and known EOS-failure controls
are not interchangeable with the warm timing denominator.

Phase timings are host wall intervals: setup, graph construction, scheduling
and allocation, input upload, synchronous compute/wait, and existing readback.
The compute/wait interval is not pure GPU time. A separate Nsight attempt
will establish whether kernel/launch/wait decomposition is available on this
machine; instrumentation timings are not uninstrumented latency claims.

Retain final prefill logits, raw float PCM, PCM16 WAV, terminal reason and all
failed attempts. Separate causal full-code traces from latency runs. Numerical
equivalence, EOS/trajectory equivalence, subjective listening, and performance
are independent outcomes. No listening result transfers to a new artifact.

## Cross-engine comparison

Use pinned `nyosegawa/speech.cpp` source and its pinned GGML. Convert the same
retained official CustomVoice checkpoint revision
`0c0e3051f131929182e2c023b9537f8b1c68adfe` for both engines. Compare tensor
identity before quantization and record post-quantization inventories.
Match text, language, preset speaker, sampling settings, flash attention and
device where supported. Same integer seed is not matched random draws:
speech.cpp uses MT19937-64, while this native fork uses Philox.
Record codec precision and chunk-schedule differences explicitly.

The author's published RTX2080/Vulkan warmed benchmark is not a CMP50HX/CUDA
measurement. First PCM is not first audible speech. Neither engine is assumed
to implement cross-request prefix KV based on a published timing.

## Prefix-KV investigation

Discover the byte-identical leading prompt embeddings across distinct texts
before choosing a reusable prefix. Test preset CustomVoice separately from
Kraftwerk Base/RU-stress ICL. A shared speaker alone does not make all reference
context independent of target text: ICL aligns projected reference and target
text with codec rows. Split prefill is expected to change matrix shapes;
compare last logits and generation rather than assuming causal attention
implies bit identity. Measure prefix preparation, restore and suffix costs
separately. Keep cached state bounded to the research pipeline and invalidate
it on an incompatible prefix/shape/conditioning.

## Historical evidence

The [previous native latency study](native-streaming-latency-research-20261120.md)
locates the bottleneck but did not demonstrate a new prefill acceleration.
The older [Python prefix experiment](../cmp50hx-prefix-reuse-research.md) has a
different runtime and numerical trade-off; it is not native acceptance.
EOS and listening observations remain in the existing
[corpus report](native-eos-corpus-and-decision-20261121.md).
