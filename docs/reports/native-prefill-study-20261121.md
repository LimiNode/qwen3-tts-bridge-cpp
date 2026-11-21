# Native prefill latency study

Status: bounded CMP research complete; scoped user listening recorded below.
Production qualification is not performed. No optimization is enabled by this report.
Date: 2026-11-21. No release/default promotion.

## Primary matrix: measured results

The complete primary matrix is 24 processes x 21 requests = 504 outcomes:
one first-use request, twelve same-input/seed warm repeats, and eight
shape/language/EOS controls in each process. Every process completed. All
504 outcomes have finite, size-consistent PCM and reported natural EOS;
none reached max tokens. This is not a text-coverage or quality PASS: the
known RU-stress seeds 2/14 still end after three frames.

The primary compiled research source is `116ca5e4`. Its retained probe SHA-256 and
runtime identities are in `matrix-001/plan.json`. The probe is statically
linked to qwen-core, not the Bridge worker or packaged DLL path. The Bridge
dependency remains `130cb99af9ae12d554962fd0920e08fb4268af01`.
Full-source prefix, valid speaker-only and graph-OFF repeats use explicitly
rebuilt C++ source `b88752d841b1833a6f52d7e7283bef5c5d0cf79c`. Subsequent
changes through engine HEAD `eb21b592fdce35d4803bc5dce0ebb2497d73a462`
are harness/docs/CI only; per-run plans retain their actual HEAD and dirty
script status. Retained binaries, not a moving build directory, identify
the measurements.

Warm p50 below is **prefill / first PCM in milliseconds**, with twelve
repeats of the same text and seed 64 per cell, not twelve independent texts.
The first group is retained separately. Nearest-rank p95 is the maximum of
this small warm sample; see raw results rather than interpreting it as a
population-tail estimate.
Observer OFF means `QWEN_PREFILL_PROFILE=0` in the opt-in research build,
not an independent GPU benchmark of a compile-time research-OFF release DLL.

| Variant | RU-stress ICL | Base ICL | CustomVoice |
| --- | ---: | ---: | ---: |
| Observer OFF | 153.57 / 179.83 | 153.38 / 179.61 | 34.53 / 58.80 |
| Baseline ON | 153.76 / 180.47 | 154.78 / 183.87 | 34.53 / 58.78 |
| Last-row norm/head | 152.96 / 179.32 | 153.15 / 178.92 | 34.46 / 58.85 |
| Talker KV F16 | 153.06 / 179.60 | 153.13 / 179.24 | 34.33 / 58.63 |
| Attention alignment 64 | 153.51 / 180.38 | 153.68 / 180.31 | 33.74 / 57.81 |
| Retained prefill graph | 152.16 / 178.42 | 152.15 / 178.11 | 33.16 / 57.30 |
| All four combined | 151.15 / 177.23 | 151.20 / 177.42 | 32.17 / 56.53 |
| Final baseline ON | 153.65 / 180.73 | 154.05 / 180.82 | 35.00 / 59.15 |

All seven non-baseline variants, including Observer OFF and the ending
baseline, preserve raw float PCM, PCM16 WAV, frame count and terminal
outcome on all 21 matched rows in each model. KV F16, window64 and retained
also preserve last prefill logits byte-for-byte. Last-only and combined
change logits slightly: maximum absolute delta across their respective
rows is 0.0013561 RU-stress, 0.0015268 Base and 0.0024652 CustomVoice; argmax
and the saved PCM remain unchanged. Full-code traces are a separate control,
not inferred from these untraced timing runs.

This is a small measured gain, not a large prefill breakthrough. Base's
starting observed block is noisier than OFF/end baselines: its 4.26 ms
ON/OFF first-PCM difference and 3.05 ms starting/ending drift are comparable
to the apparent optimization. Combined Base p95 is worse (218.29 versus
195.23 ms). Fixed block order and one warm text/seed limit causal attribution.

### Host-wall prefill decomposition

Unchanged observed RU-stress, warm p50 in ms:

| Span | ms |
| --- | ---: |
| Setup | 0.015 |
| Graph construction | 0.347 |
| Schedule / allocation | 1.106 |
| Upload | 0.329 |
| Compute / wait | 151.540 |
| Existing readback | 0.092 |
| Prefill reported by engine | 153.762 |

These are independent phase medians, not additive measurements of one
synthetic request. `compute_wait` contains GPU execution, kernel launch and
waiting; it is not pure GPU time. Graph construction/allocation is only
about 1.5 ms here. Nsight Systems 2026.4.1 was attempted separately; its
SQLite diagnostic explicitly says `CUDA tracing is not supported on NVIDIA
Crypto Mining Processors (CMP)` (`ERR_NVCMPGPU`). The profiler exited with
0xC0000005 after all three bounded probe requests completed; 82 NVTX host
events but no CUDA events were exported. This is a profiling limitation,
not a model failure or a kernel-level timing result. The report and SQLite
diagnostic are retained in `nsight-ru-stress-001/`.

### Separate code-trace control

`causal-001` contains 105 outcomes (three models, seven observed variants,
five texts/seeds per variant). Every stored complete 16-code frame matches
the actual stderr trace; none reaches the 128-frame trace bound. All six
candidates per model preserve codes, raw PCM, frame count and terminal reason
on 5/5 pairs. Matched traced/untraced cases also preserve PCM/logits on 5/5
pairs in each of the 21 blocks. These trace runs are not latency evidence.

### Conditioning is a major confounder

Our native CustomVoice prompt has 33 rows for the original text, versus 236
for Kraftwerk ICL. The measured 59 versus 180 ms first PCM is not a pure
ICL-cost subtraction: checkpoint, speaker and codec also differ (CustomVoice
uses the matched F16 comparator codec, Base/RU the retained Q8 codec).
Same-checkpoint speaker-only controls are kept separately.

`speaker-only-002` now completes 84 outcomes, forty-two per Base checkpoint.
Every row explicitly reports `conditioning=base_speaker_only`; original text
has T33 instead of ICL T236. The same frozen speaker embedding, target
text/seed, checkpoint, Q8 codec and CUDA settings are used; only reference
text/codes are omitted (existing Base clone mode A).

| Same checkpoint | Speaker-only warm prefill / first PCM, ms | Ending repeat |
| --- | ---: | ---: |
| RU-stress | 34.88 / 59.40 | 34.48 / 59.13 |
| Base | 34.89 / 59.49 | 34.84 / 59.30 |

Both ending repeats preserve raw PCM/logits/frames on 21/21 pairs. Omitting
ICL removes approximately119 ms prefill and120 ms first-PCM time relative
to the ICL controls on these same checkpoints. It changes conditioning and
generated audio: it is **not** equivalent voice-cloning inference or an
automatic fidelity-preserving optimization. The user recognized normal speech
in the two retained speaker-only examples, but detailed voice identity,
prosody and broader text coverage remain unassessed. First-use latency also differs
because the ICL route initializes reference-codec state; only the warm
component is isolated in this subtraction.

Byte-level prompt-prefix discovery across the retained Russian texts finds
86 identical initial rows for Base/RU-stress ICL and 9 for CustomVoice.
Changing to English leaves only 5 in each family. These are observed
boundaries for this conditioning, not universal hardcoded cache lengths.
The prefix cache rejects a mismatching embedding byte sequence and remains
invalid until handle reload; matching a speaker name is not sufficient.

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

### Source and workload audit

Pinned speech source is `fd747c11e50543f59f2bbe233a9c7228dc479a71`,
GGML `79b50d239d0b88852814c873db0d85d43ed66d9b`. Native GGML is
`c044c6f03892f9d5e98213b05f8afea1f8b0d3c9`. Both converters use the same
checkpoint above: all 404 Talker/CodePredictor tensors match before and
after Q8 quantization. All 253 codec decoder tensors match after the explicit
axis/Snake representation mapping. This controls weights, not numerical
operation ordering. Conversion/parity receipts are in `competitor-setup/`.

Both CustomVoice prompts use full target text and eleven additional rows for
an explicit language/speaker; neither has a cheaper partial-text template
in this comparison. Both first callbacks deliver 1920 samples (80 ms at
24 kHz). Later schedules differ: speech 1/1/2/4 frames, native 1/2/4/8.
There is no cross-request prefix-KV reuse in speech: decoder `start()` resets
`n_past_` to zero, and prefill rebuilds its graph. Persistent decode and
CodePredictor-chain graphs must not be confused with a prefill cache.

Speech already selects the last hidden row before final norm/head, uses
Talker F16 KV and alignment 64. Native `combined` tests the same choices,
plus its own retained prefill graph. Both flash-attention paths request F32
accumulation, but their pinned GGML kernels and graph execution differ.
Sampling numerical defaults match; Philox versus MT19937-64 draws do not.
Equal seed 64 is therefore not a generated-output parity test across engines.

The comparator is built with CUDA graphs OFF. Native ordinary graph-ON
results are kept separate from an explicit graph-OFF control. Speech's
published 32 ms median uses RTX 2080/Vulkan, Japanese and `ono_anna`, not
this CMP/CUDA/Russian/`ryan` setup. No single optimization can be credited
for an entire cross-engine difference.

### Matched-checkpoint CMP timings

The final committed direct probe was rebuilt into a fresh output directory;
`speech-ru-002` and `speech-en-002` each retain thirteen mechanically valid,
natural-EOS outcomes: first-use plus twelve warm repeats. Source and executable
copies are in `runtime-speech-final/`; linker warning LNK4098 (CRT default
library conflict) is retained, not suppressed. Initial `speech-*-001` results
used the earlier retained probe source and remain separate historical runs;
they are not silently attributed to the newer finite/bounds-checked source.

Same official CustomVoice checkpoint, `ryan`, original Russian text, seed64,
matched Q8 Talker/CodePredictor and matched F16/F32 codec storage:

| Direct engine / control | Warm prefill p50, ms | Warm first PCM p50, ms |
| --- | ---: | ---: |
| Native, CUDA graphs ON, observation OFF | 34.53 | 58.80 |
| Native, CUDA graphs OFF, observation OFF | 35.39 | 107.14 |
| speech.cpp, CUDA graphs compiled OFF | 34.00 | 102.39 |

The native OFF/ON control preserves raw PCM/frames/terminal on21/21 matched
cases. Its approximately48 ms first-PCM regression with only0.86 ms prefill
change is predominantly after prefill, not evidence for a faster competitor
prefill algorithm. Independent phase accounting attributes the speech first
frame roughly to34 ms prefill,40–46 ms CodePredictor and23 ms codec, plus
small prompt/host work. Phase sums are not additive quantile identities.
Different GGML/CUDA graphs, kernels, readback and composition paths remain
confounders; the approximately5 ms OFF/OFF difference is not isolated to
one implementation choice.

The English speech repeat gives prefill29.70 ms and firstPCM97.22 ms,
13/13 mechanically valid/natural EOS. It is a separate workload; native's
single English shape control is not a matched twelve-repeat English timing
distribution. The user subsequently recognized normal speech in the retained
Russian speech.cpp example, with wrong `процессОр` in speech.cpp file11 and
correct `процЕссор` in native file10. Detailed voice quality and the other
comparator WAVs remain unassessed.

Native's initial `customvoice-graphs-off-002` plan budget was300 s. Its
unobserved block completed21/21; the observed block retained20/21 before
timeout, and the ending block was not run. The twelve observed warm rows
are retained as partial-run diagnostics, not a completed21-case control.
A new independent `customvoice-graphs-off-ending-003` completes the ending
control without altering the old plan or discarding incomplete evidence.
It reports21/21 valid/natural EOS outcomes, warm prefill35.38 ms and
firstPCM106.78 ms, with raw PCM/logits exact21/21 against the graph-ON
baseline. The initial observed partial block's twenty outputs also match;
its unrun twenty-first control remains unrun.

Timing boundaries also differ slightly: native starts before request buffer/
parameter initialization and timestamps before callback validation; speech
timestamps after validation. Speech pre-tokenizes once to record prompt rows,
then tokenizes again inside synthesis. Neither timestamp is physical playback
or first audible speech. This is a matched-weight implementation comparison,
not identical RNG draws or a one-factor mathematical experiment.

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

### Measured prefix results

The split-source study contains 240 outcomes: three models, four processes
per model, twenty Russian-only requests per process. The full-source repeat
adds 180 outcomes: three models, three processes, twenty requests each. Each
process retains twelve same-original-text/seed64 warm repeats, short/long
shape changes, A/B/A returns and known seed2/14 failures. No English request
is silently admitted into an 86-/9-row Russian cache.

Warm p50 **prefill / first PCM**, ms:

| Model | Split control | Split prefix | Split prefix + four variants | Full-source control | Full-source prefix |
| --- | ---: | ---: | ---: | ---: | ---: |
| RU-stress | 152.36 / 177.97 | 106.94 / 133.22 | 104.63 / 131.15 | 152.58 / 178.43 | 106.73 / 132.51 |
| Base | 154.05 / 180.03 | 106.94 / 132.91 | 104.58 / 130.36 | 153.71 / 179.86 | 107.23 / 133.37 |
| CustomVoice | 34.77 / 59.51 | 25.17 / 49.69 | 22.62 / 47.14 | 34.67 / 58.85 | 25.43 / 49.58 |

All 420 outcomes have finite valid PCM and reported natural EOS, but **prefix
reuse fails numerical/output equivalence**:

- Split RU-stress/Base prefix variants preserve raw PCM on 0/20 pairs.
  With full-source snapshots, the first source request is exact, but all
  19/19 subsequent cache hits change logits, frames and raw PCM. Maximum
  full-source logit deltas are 0.151474 RU-stress and 0.168600 Base.
- Uncombined CustomVoice split and full-source preserve PCM/logits/frames on 19/20;
  the short `Да` counterexample changes from 9 to 37 frames in either
  prefix mode (combined split gives 8). Max logit delta is 0.317353.
  Combined split preserves PCM on 19/20, but changes logits on all20
  because it also includes last-row-only final norm/head.
  Original and longer tested CustomVoice texts remain exact. Split/full
  CustomVoice candidates themselves match on all 20 pairs.
- Every ending baseline preserves raw PCM/logits/frames on 20/20 pairs for
  its model. This repeatability rules out ordinary baseline nondeterminism
  as the explanation for these observed cache differences.

Full-source snapshots demonstrate that independently calculating the prefix
with a smaller shape is not the only source of drift: suffix execution from
the original full-pass KV still differs. Positions, causal mask, KV-head
strides and snapshot timing were inspected without finding an obvious
off-by-one. That is not proof that arithmetic order is the only cause.
In particular, CustomVoice `Да` changes matrix width from 14 to 5 rows;
the pinned GGML has an MMVQ dispatch boundary at eight rows. This is a concrete
kernel-family hypothesis, not a causally established root cause. Layer/KV
taps or a forced-kernel experiment would be needed to distinguish it.

Restoring the cached prefix costs about 0.2–0.3 ms. Roughly 46 ms first-PCM
improvement on Base/RU is therefore a real measured opportunity, but not an
equivalent replacement. Longer outputs or a changed early-EOS trajectory do
not prove complete speech. Subsequent scoped listening confirmed full text,
correct stress and no cough in the retained RU-stress/Base ICL examples,
with acceptable delivery differences, but found extraneous coughing
before the expected word in the short CustomVoice prefix output. Wider
quality tests are still required before considering a separately named perceptual-risk profile.
Nothing here promotes such a profile.

Language-rejection controls (`prefix-language-reject-ru-001` and
`prefix-language-reject-customvoice-001`) each preserve two bounded four-frame
requests, first a cache miss then a hit. The following English request fails
with the exact prefix-mismatch error, exit1 and no third PCM artifact. These
intentional max-token controls test refusal before incompatible synthesis,
not speech quality, natural EOS or recovery of an already poisoned handle.

## Historical evidence

The [previous native latency study](native-streaming-latency-research-20261120.md)
locates the bottleneck but did not demonstrate a new prefill acceleration.
The older [Python prefix experiment](../cmp50hx-prefix-reuse-research.md) has a
different runtime and numerical trade-off; it is not native acceptance.
EOS and listening observations remain in the existing
[corpus report](native-eos-corpus-and-decision-20261121.md).

The earlier work has already exercised these alternatives:

- [Python compiled prefill](../cmp50hx-base-first-pcm-research.md): about
  148 s warmup, then 404.9 ms prefill versus 353–359 ms eager; rejected as a
  latency regression, not an untried solution to the current native 153 ms.
- [Python prefix isolation](../cmp50hx-prefix-reuse-research.md): immutable
  86-row inputs did not produce equivalent split/full KV. Even exact full-KV
  seeded suffix changed hidden/logits/KV. A temporary reuse path reduced first
  PCM 614.279 to 527.394 ms but changed codes, length and PCM; the initial
  parity-qualified production path was rejected.
- [Later profile history](../cmp50hx-research/startup-and-prefill.md): prefix
  reuse was subsequently limited to an explicit perceptual-risk fastest
  profile after scoped listening, not declared numerically equivalent.
  Smaller static sequence capacity, selected-profile warmup, emission schedule,
  and reference-codec bootstrap were also investigated. They change different
  parts of latency and are not new native prefill findings.
- [AR breakdown](../cmp50hx-ar-breakdown-research.md): static output views had
  only noise-scale gain; tiny compiled decode reduced latency but changed
  generated tokens. Nested PyTorch graph replay failed its capability probe.

## Evidence failures and limits

`speaker-only-001` is invalid: its old probe silently ignored the newly added
manifest option and still reported `conditioning=base_icl`, T=236. Only a
repeat reporting `base_speaker_only` can isolate ICL cost. The collector now
checks the effective mode and retains/rejects a mismatch.

The first full-source prefix and graph-OFF controls (`*-001`) are invalid:
an incremental Ninja/MSVC build rebuilt the probe but retained a stale static
pipeline object after an internal observation-layout change. Shifted fields,
zero logits and 0xC0000409 exposed it. Ninja reported zero tracked header
dependencies for that object. Explicitly invalidating/recompiling the pipeline
and qwen objects repaired the observation. All failed attempts remain;
the repeated `*-002` directories are the usable controls. Primary matrix and
causal runs used the earlier coherent frozen runtime, retained separately in
`runtime-initial/`. Future reproduction should use a clean build, not trust
this machine's localized MSVC incremental header dependency scan.

Only the scoped listening verdict below is claimed. Prefix caching is single-slot/GPU-only,
with one device snapshot, exact prefix-byte validation and rejection until
reload after a mismatch. Cross-voice cache replacement, post-rejection
recovery, cancellation/reset, diagnostic-dump transitions and a full
worker/package route are not qualified. F16 KV also changes later decode
storage; its tested equivalence is not a general theorem for all seeds/models.

## Decisions from this study

1. Retained prefill graph is the clearest small follow-up: it removes about
   1.5 ms of repeated host graph/allocation work and preserves observed
   logits, complete traced codes and PCM. Broader lifecycle, shape/dump and
   model/seed controls are still required before a production change.
2. Last-row final norm/head avoids unnecessary work, but the gain is small
   and the changed matrix shape changes logits. It is not a bit-equivalent
   rewrite even though all tested sampled outputs agree.
3. F16 KV and alignment64 do not materially solve Base/RU prefill latency:
   both alignments pad T236 to256. F16's memory benefit and later-decode
   effects need a separate decision, not a latency-only promotion.
4. Prefix-KV is the larger opportunity, about46 ms here, and fails output
   equivalence even when copied from the original full pass. Before further
   caching machinery, isolate suffix/kernel numerical differences with
   layer/KV taps or forced-history/forced-kernel controls. A perceptual-risk
   profile would require its own named scope and broader listening, not a silent
   default change. The observed CustomVoice prefix cough is a quality failure,
   not merely a numerical mismatch. No such profile is enabled.
5. Further large prefill gains must address the compute/wait-dominated path,
   not introduce a host cache framework to recover tens of milliseconds
   from about1.5 ms of graph setup. A pinned GGML/kernel/backend comparison
   is a stronger next hypothesis than another unmeasured cache abstraction.

These findings do not correct or qualify early EOS. Known short RU-stress
failures survive the four small optimizations; longer prefix outputs are
different trajectories, not proof of recovered speech. R1 acceptance state,
the Bridge engine pin, ABI and sampler policy remain unchanged.

## Review artifacts and validation

- [Engine Draft PR #50](https://github.com/LimiNode/qwentts.cpp/pull/50),
  stacked on research PR#49; exact HEAD
  `eb21b592fdce35d4803bc5dce0ebb2497d73a462`. Both Windows/Linux CPU
  CI jobs passed in [run44865077787](https://github.com/LimiNode/qwentts.cpp/actions/runs/44865077787),
  exercising ordinary research-OFF and opt-in ON seams. They are not GPU CI.
- Local clean MSVC research-OFF build:13/13 CTest and the standalone C ABI
  negative-path probe passed. Research-ON/CUDA build:14/14 CTest and the
  same ABI probe passed. Settings tests compile with `/W4 /WX`. The expected
  `Cannot open irrelevant.gguf` diagnostic belongs to the passing ABI negative
  probe; an initial PowerShell wrapper treated stderr as an exception, so
  the probe was repeated with explicit native redirection. The original log
  and subsequent successful validation logs are all preserved.
- Python prefill evidence tests:13; comparator evidence tests:8, plus existing
  sampler/EOS tests through CTest. Bridge canonical receipt validator:7
  receipts validated at measurement publication; the listening follow-up adds
  four indexed scoped receipts, and all11 now validate. Separate artifact
  validation checks all13 listened WAVs through those four receipts. This
  research summary is intentionally not a new R1
  acceptance gate.
- [Machine-readable study summary](native-prefill-study-20261121.json)
  retains denominators, warm p50/p95, comparisons, runtime/model identities,
  hashed raw-result/plan anchors, incomplete/invalid controls and limitations.
  Complete payloads remain in
  `.tmp/base-acceptance/prefill-latency-20261121/`; initial, rebuilt native
  and final speech executables are preserved in separate `runtime-*` directories.
- One listening directory contains13 numbered unchanged WAV copies:
  `listening-prefill-ab/`, with exact text, seed, source and SHA-256 in
  `manifest.json`. Files01–03 are RU-stress ICL baseline/split/full-prefix;
  04–06 are Base equivalents;07–09 are CustomVoice `Да` baseline/split/full;
  10/11 compare native/speech original CustomVoice;12/13 are RU-stress/Base
  speaker-only, to compare against01/04 for the cost/fidelity trade-off.
  The later observations below apply only to these exact files; historical
  measurement rows retain their original unassessed listening status.

## Scoped listening follow-up

The user listened to all 13 numbered files in `listening-prefill-ab/` on
2026-11-21. Their manifest is 9,959 bytes, SHA-256
`4f7c00b5da71f3a97d19284110e68a0a8dc0e8cc498fff24c97120f4f7b3de90`.
All 13 byte counts and SHA-256 values were independently rechecked against
the unchanged manifest and original source copies. There are 12 distinct
WAV hashes: files08/09 are byte-identical and are not independent failures.
No audio was regenerated, edited, or normalized for this follow-up.

| Files / exact scope | User observation |
| --- | --- |
| 01-03 RU-stress ICL original, baseline/split/full-prefix | Full text, correct stress, no cough; acceptable delivery differences:02 slightly higher,03 breathier with stretched word endings |
| 04-06 Base ICL original, baseline/split/full-prefix | Full text, correct stress, no cough; acceptable delivery differences:04 calm/thoughtful,05 slower than01,06 calm |
| 07 CustomVoice baseline short text | Simply says `Да` |
| 08/09 CustomVoice split/full-source prefix short text | Coughing/throat-clearing **before** recognizable `Да`; fails no-extraneous-sound criterion |
| 10 native CustomVoice original | Normal speech, correct `процЕссор` |
| 11 speech.cpp CustomVoice original | Normal speech, wrong `процессОр` (stress on the second `О`) |
| 12 RU-stress speaker-only original | Normal speech, wrong `процессОр` |
| 13 Base speaker-only original | Normal speech, correct `процЕссор` for this word |

Files01-06 and10-13 use the original phrase, "МГУ находится в Москве.
Инженер проверил USB-порт, GPS и новый процессор." Files07-09 use `Да!`.
The full-text/stress/no-cough verdict applies to files01-06 only, not every
generated artifact. Normal/recognizable speech in the other named files is
scoped positive evidence, not a blanket fidelity PASS. Detailed voice matching,
instruction adherence, final tail, sequential isolation and broader corpus
coverage remain unassessed. The user's later clarification resolves the
10/11 stress attribution explicitly; no ambiguity remains between the backends.

Separate canonical receipts prevent transfer between model families/backends:

- [RU-stress](native-prefill-ru-stress-listening-cmp50hx-20261121.json): partial scoped listening; file12 pronunciation defect recorded.
- [Base](native-prefill-base-listening-cmp50hx-20261121.json): partial scoped listening; file13 word stress recorded.
- [Native CustomVoice](native-prefill-customvoice-listening-cmp50hx-20261121.json): failed artifact criterion for prefix files08/09 despite recognizable text.
- [speech.cpp CustomVoice](speech-prefill-customvoice-listening-cmp50hx-20261121.json): partial scoped listening; file11 wrong `процессОр` recorded.

All four release dispositions remain `blocked`. The positive RU-stress/Base
examples neither establish broader quality nor repair known early EOS cases.

No PR is merged by this study, no package is rebuilt/promoted, and RTX4090
is not tested. Numerical equality on the stated cases, human quality and
release support remain separate questions.

## Layer/KV and kernel follow-up

The [differential follow-up](native-prefill-differential-20261121.md) records
208 bounded outcomes,104 exact OFF/ON pairs and240 byte-exact KV restores.
The first valid drift is Q projection, before attention. CUDA route logs and
prefix5/6 controls isolate a substantial MMQ/MMVQ-switch contribution for
CustomVoice short text. Forced MMQ preserves full seed64 `Да!` PCM in a
separate12-request natural-EOS run, but residual logits differ. The user now
confirms `Да` without coughing in the new baseline/MMQ files01/03, while
ordinary-prefix file02 coughs before `Да`. This is one exact text/seed64
observation, not broad qualification. No production profile is promoted. Base/RU intra-MMQ shape
drift remains. See the linked record for excluded view taps and provenance gaps.
