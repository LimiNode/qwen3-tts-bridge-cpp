# Native/source causal comparison: executed run002

2026-11-25 follow-up: the [retained findings and next-stage record](tts-research-findings-and-next-stage-20261125.md)
uses this exact evidence to prioritize controlled EOS experiments. The
original numerical results and historical decisions below remain unchanged.

## Current result and interpretation

Research only,2026-11-24. The newly authorized run002 completed four native
requests, four matched-history source controls,26 conditional-logit comparisons,
four exact-native-input forward controls and four bounded free source
trajectories. No speech/voice/listening or release acceptance follows from this
numerical result. R1 remains **NO-GO**.

The exact RU-stress merged checkpoint, retained native Q8, source packages,
full aligned ICL inputs and seeds are unchanged from the plans below. Source
runs CPU FP32 with eager attention verified on the actual nested Talker and
Predictor attention module configurations before and after execution. No
package, model or installed source was replaced. All frozen identities pass
postflight. Original prepared run001 remains preserved and unexecuted.

| Fixed case | Native retained frames | Free source frames / first EOS | Initial input relative L2 | Initial allowed-logit TV |
| --- | ---: | ---: | ---: | ---: |
| `Ладно.` /2027 |2, natural EOS |2 /2 |0.004787 |0.001639 |
| `All right.` /2029 |6, natural EOS |11 /11 |0.004786 |0.002225 |
| Long Russian /2027 |8, diagnostic cap |86 /86 |0.004816 |0.010993 |
| Long English /2027 |8, diagnostic cap |85 /85 |0.004814 |0.009446 |

Do not compare the capped8-frame native controls with full source lengths as
a quality or EOS-recovery score. Free source codes were not decoded/listened
to;11,85 or86 frames are not proof of correctly spoken words. Token IDs match
for all four prompts. Initial embedding cosine is0.9999884–0.9999885, but
elementwise equality does not hold. Initial raw-logit top1 agrees in all four
cases. TV is total variation after allowing audio IDs0..2047 plus EOS2150,
temperature1 and no penalties; it is **not** the sampler's final probability.

For `Ладно.`, the free source produces exactly the same two complete16-code
frames as native, then EOS. At initial and subsequent matched steps0/1/2,
native/source allowed-temperature1 EOS probabilities are approximately
95.349/95.187%,95.776/95.694% and96.523/95.799%. The initial minimum2 suppresses
EOS eligibility, not the underlying model preference. On this case,
native-only categorical selection or GGUF conversion is therefore not a
necessary condition for the two-frame failure. This does **not** establish a
universal checkpoint defect or isolate conditioning from training/source code.

All forced prefixes preserve the same **complete** native16-code histories:
2/6/7/7 frames. Across26 matched steps, maximum allowed-logit TV is
0.007232/0.030005/0.029082/0.034134 for the four cases. Feeding exact native
input embeddings to source does not remove the remaining drift: corresponding
maxima are0.007576/0.035240/0.028509/0.033210. Prompt reconstruction alone thus
does not account for every numerical difference. Source FP32 versus native Q8
still cannot distinguish quantization, conversion and forward implementation.

In the other three free trajectories, the earliest **discrete** mismatch is
already in the first frame's Predictor codes, even though initial sampled
Talker code0 agrees. Zero-based codebook/native/source values are:
shortEN book2:382/360; longRU book7:1886/1858; longEN book1:1329/1338.
Later free Talker histories consequently are not matched numerical controls.
This localizes the first observed code difference, not a demonstrated faulty
Predictor layer or sampler. The existing Philox helper does not make differing
FP32/Q8 distributions or execution paths trajectory-equivalent.

**Decision:** extend exact-artifact listening of the shorter-reference
[A/B/C candidates](native-reference-conditioning-20261124.md) beyond the now
confirmed short selection, retaining full ICL and the original speaker-vector
arm. The known short Russian failure also
exists in the exact source; do not add more seed search or integrate rollback
as an arithmetic fix. If the English native/source difference remains a
product blocker, the next numerical control is an equal-checkpoint native
higher-precision build and first-frame Predictor distributions under identical
inputs/history/random draws. High-precision native was **not run** within the
safe disk budget, so no quantization-versus-conversion attribution is made.

## Executed scope, evidence and budget

Payload: `.tmp/base-acceptance/native-source-causal-cmp50hx-20261124/run-002/`.
The local runner is `run_source_causal_v2.py`, SHA256
`2486eafbf3ec02b85570d03b7bcbd7b38f545a9618c0fad2a4035b8fcb61b362`;
10 model-free tests pass, including deadline refusal/owned-child termination,
frozen corpus/test identities and actual eager-attention alignment. The
[run002 plan](native-source-causal-run002-plan-20261124.md) preserves the
versioned runner/test and unchanged original plan. There was no retry or seed
selection after observing outcomes.

Source `source/results.json`:510626 bytes, SHA256
`64be7f64ffd37e0deef3d49c9c466eb0ee7a0925c3e1918db4d5d982e86a2808`.
Artifact inventory:498524 bytes, SHA256
`0f9823fb6cc2c78f296bba8a7d5fc6e4f39ba7a62a8def4ecb84faa9914c3b76`.
It identifies native tensor/code dumps, matched source hooks, direct-input
controls, all free codes/traces, attention identities, process logs and
before/after inputs. These ignored payloads are local-only, not Git backups.
The final read-only hash audit verifies all1724 inventory entries/121345471
payload bytes, plus all652 reference inventory entries/95655403 bytes and
both new canonical reference receipts' declared artifacts. Receipt validation
passes for42 indexed records; validator regressions pass17 with one optional
JSON-Schema skip. This checks evidence integrity, not semantic speech quality.

The independent root supervisor journal is
`.tmp/base-acceptance/reference-source-resumed-20261124/run-001/`.
It starts2026-11-24T13:26:55Z, uses the single authorized absolute monotonic
deadline3196090.625, and preserves each exact command and stage result.
All GPU stages completed by3194576.218,285.593s after the start3194290.625;
the source-native child used8.375s. CPU source followed the completed timing
stage and used165.078s under its600s inner watchdog and unchanged shared
deadline. Complete execution including postflight finished by3194776.156,
485.531s after start. All five stages exited0, with no timeout/storage stop
and frozen scripts unchanged. Keep the old expired allocation distinct.

Aggregate `results.json` SHA256:
`44696e770a05f1f2ab8e51b6ca86d97c8b57f95125194167ba13277015fafd8f`.
No further GPU execution was scheduled. No production default/pin, ABI6, QTB,
frozen package, merge, tag or release changed. The subsequent user amendment
makes explicit stress/full-ICL a release requirement, with RU-stress primary
and Base a control; RU-stress remains HOLD, not automatically promoted.

## Preserved run001 history: verified preflight, no execution

- Status: preparation verified; native and source model execution **not run**.
- Date: 2026-11-24.
- [Frozen experiment plan](native-source-causal-plan-20261124.md).
- Branch: `research/native-source-causal`, based on Bridge `8ccdc515`.

## Confirmed local source and provenance

The exact merged source checkpoint is available locally. Its existing legacy
cache file `.models/ru-stress-20261006/merged3/model.safetensors` was read and
hashed, not copied or replaced. Its SHA-256 is
`9742ba7f6ca86732875c4a910f8f60988183c525c84e99dd724f02424ee88fe0`.
This matches [the conversion receipt](russian-stress-native-conversion.json)
and local merge receipt: official Base revision
`fd4b254389122332181a7c3db7f27e918eec64e3`, RU-stress LoRA revision
`e644ae00257fdd4db0e51b11057370dff6be8bc2`, rank16/alpha32/scale2;
196 modified LoRA pairs among480 source tensors. The existing checkpoint
remains a legacy input; no new `.models` content was added.

The installed source environment is Torch2.8.0+cpu, transformers4.57.3 and
safetensors0.8.0. CUDA is unavailable in that Torch installation. The installed
`modeling_qwen3_tts.py` has SHA-256
`9c5b54d9435604c6cbfda0fbbaeb77d4c959b0f95592b00f40c507f5364ede38`.
The repository upstream copy has a different hash and is **not** substituted
for the installed code or described as the code actually executed.

The pinned cossim helper hash is
`ac6c7de23cacab75c7c7a5317eda9994e3c19336832e56be3da9d0915852dca4`.
Only its historical upstream path literal is adapted in memory. An offline
CPU-only readiness check successfully loads its model/processor classes and
tokenizes all four frozen texts. Configuration confirms28 Talker layers,
hidden size2048, vocabulary3072 and16 codebooks. That check loads **no model
weights**, initializes no GPU and establishes no numerical or speech result.

The earlier source probe at
`.tmp/base-acceptance/streaming-eos-research-20261120/parity/probe.py` is
preserved unchanged. Its forced-history results concern another text/seeds,
not the four cases in the new plan. They do not establish why a bad native
history arose.

## Prepared implementation and checks

New local tools are under
`.tmp/pr-metadata/native-source-causal-20261124/`:
`run_source_causal.py`, `test_source_causal.py` and `check_helper.py`.
The runner uses the existing native dump/probe surface rather than changing
production code. It prepares exactly four capped native requests, compares
their complete code prefixes with corrected geometry run002, reconstructs
the source prompt, forces complete16-code histories, adds an exact-native-
embedding forward control, and separately retains bounded free trajectories.
Raw logits and the explicitly named allowed-vocabulary temperature1 probability
are not conflated with post-penalty/top-k sampler probabilities.

Four model-free runner tests pass: fixed case/seed selection, raw-distribution
semantics/finiteness, exact metrics/shape guards and explicit resource/scope
guards. The separate offline helper readiness check passes for all four texts.
These are preparation checks, not a passing matched-history experiment.

The frozen payload directory is
`.tmp/base-acceptance/native-source-causal-cmp50hx-20261124/run-001/`.
It currently contains plan, native manifest, pre-execution identity addendum
and CPU-helper readiness evidence. The machine plan records input/probe/
runtime/source hashes, including the complete source checkpoint identity.
Its frozen runner SHA-256 is
`ea13b66f43cbda5d531dda0e91e6355c080b1ae0cc00761b1cb269e241088a27`.
The native manifest SHA-256 is
`7adc621388aaba2a6a19727dfd13da436a9767c20fc946d376deb658df61520f`.
Do not overwrite the prepared files or earlier geometry payloads.

## Remaining execution and interpretation boundary

No native process was started: the shared batch deadline3170194.937
(2026-11-24T06:45:20Z) expired before an exclusive lease was available
for this child. The deadline was not reset. Consequently source model
execution, which requires the new exact native dumps, was not started either.
The native stage has a300s owned-process watchdog, source600s, a512MiB disk
reserve, and400/200MiB respective payload caps. These local watchdogs do not
extend or replace the coordinator's aggregate GPU deadline.

The earliest significant native/source divergence is **not checked** in the
new cases. Free source trajectory behavior and quantization sensitivity are
also **not checked**. An FP32 source/Q8 native difference alone could not
distinguish quantization from native arithmetic or conversion; an equal-
weight/high-precision native control remains separate work.

No new WAV listening assessment, acceptance gate or release qualification is
claimed. Existing canonical receipts retain their own exact scope. No engine
pin, sampler default, ABI, QTB, package, merge or publication changes. R1
remains **NO-GO**.
