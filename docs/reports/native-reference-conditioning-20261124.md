# Reference conditioning: run002 completed, new speech listening pending

## Current result: new authorized run002

Research only,2026-11-24. R1 remains **NO-GO**. The new canonical receipts are
[RU-stress run002](native-reference-conditioning-rustress-cmp50hx-20261124-run002.json)
and [Base run002](native-reference-conditioning-base-cmp50hx-20261124-run002.json).
They supersede the separate preparation-only receipts without rewriting them.

All3 native reference extractions and96 new AR attempts completed:32 diagnostic
and64 observer-OFF streaming requests,48 per model. Original A was reused,
not rerun, after70 sealed artifact identity checks. Extraction regenerated
the original226-frame complete reference codes and2048-value speaker vector
**byte-identically**; short and medium references encoded56/116 frames.
Model/runtime/input identities stayed unchanged. All attempts used aligned
full ICL, including decoder reference context, and the same default stochastic
Talker/Predictor settings, seeds2027/2029 and minimum2 frames. No retry,
reseed, rollback or speaker-only fallback was applied.

The root supervisor started a new authorized1800s deadline immediately before
extraction. All GPU children for reference and native/source tracks completed
in approximately285.6s of that common window; its independent whole-batch
record belongs to the coordinating source report. This reference payload
does not seal or modify that other track's separately recorded CPU outputs. The
old run001 deadline/refusal remains unchanged historical evidence below.

### Generated trajectories, not a quality verdict

The fixed four-case order is `Ладно.`, `All right.`, the long Russian voice
control and the long English voice control from the [plan](native-reference-source-plan-20261124.md).
B keeps the original speaker vector; C extracts the speaker from its crop.
All displayed frame counts are diagnostic single attempts ending at natural
EOS, not word-coverage assessments.

| Model | Reference/speaker | Prompt rows | RU short | EN short | RU long | EN long |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| RU-stress | Original A, reused |236 |2 |6 |99 |78 |
| RU-stress | Short B, original speaker |66 |15 |11 |90 |88 |
| RU-stress | Short C, crop speaker |66 |11 |11 |80 |77 |
| RU-stress | Medium B, original speaker |126 |13 |14 |92 |86 |
| RU-stress | Medium C, crop speaker |126 |13 |13 |100 |76 |
| Base | Original A, reused |236 |11 |10 |92 |86 |
| Base | Short B, original speaker |66 |15 |10 |106 |83 |
| Base | Short C, crop speaker |66 |14 |12 |99 |100 |
| Base | Medium B, original speaker |126 |15 |15 |112 |80 |
| Base | Medium C, crop speaker |126 |15 |15 |96 |85 |

The retained RU-stress `Ладно.` A has2 frames/0.16s and near-silent PCM;
its prior exact-artifact failed listening remains in the geometry receipt.
None of the32 new diagnostic outcomes meets the frozen near-silence threshold
(RMS<0.0001 and peak<0.001). **This does not prove any new phrase was spoken.**
All64 timing attempts reproduce their matched diagnostic complete code
histories; repeated same-mode timing outputs reproduce full codes and PCM.
New text completeness, unwanted sounds and stable/reference-like voice remain
unassessed until listening. No old listening verdict transfers to B/C.

For the known RU-stress short failure, the first permitted EOS decision at
frame2 changes substantially. Retained A puts EOS at rank1 before the sampler,
then gives it0.9889846 normalized stochastic weight and samples it. With short
B/C the EOS ranks are419/288; with medium B/C291/280. It is outside the
unchanged top50, with zero saved post-chain weight at that decision. New
trajectories terminate at frames11–15 instead. This is a measured change of
conditioning and generated history, not evidence that an EOS guard repaired
anything or that the complete speech/voice is correct. Crop versus original
also changes phonetic content and decoder context, not reference length alone;
only B versus C isolates speaker-vector origin.

### Direct-engine latency with diagnostic observers disabled

Warm medians below use requests1..7 of the same two-cycle four-text order,
excluding the first process request. Original A uses the same first8 requests
from its retained timing run, not new randomized interleaved controls.
Values are milliseconds, RU-stress / Base.

| Reference/speaker | Warm prefill | Warm first PCM callback |
| --- | ---: | ---: |
| Original A, reused |152.68 /152.68 |178.58 /178.18 |
| Short B |60.29 /60.24 |83.16 /83.20 |
| Short C |60.06 /60.29 |82.96 /83.09 |
| Medium B |86.62 /86.50 |110.72 /110.34 |
| Medium C |86.15 /86.57 |109.99 /110.65 |

The observed short-reference first-PCM reduction is about95ms, but different
wall-clock runs, changed prompt/voice conditioning and unassessed new speech
prevent a production speedup claim. First process callbacks include reference
decoder startup: reused A1532–1552ms, short585–603ms, medium917–946ms. None of
these is a QTB/CLI/playback measurement or first audible speech onset. Both
shortened prompt sizes still use the256-position rounded KV window. No prefix-KV cache,
new kernel or inference-default change was introduced.

### Audited evidence and one first-listening folder

Payload root:
`.tmp/base-acceptance/reference-conditioning-cmp50hx-20261124/run-002/`.
Inventory:652 files/95655403 bytes, excluding the inventory itself; SHA256
`6a7e8b0797f72f9b2f1fc5a51d728d6d785eeede88fdc4440a0d4f32e584075e`.
All128 original/final/streaming raw-F32 to PCM16 WAV pairs were independently
checked sample-for-sample, with no normalization. Full16-codebook histories,
initial logits, corrected suppressed pre-chain logits, post-chain exp weights,
saved uniform draws, exact inputs and transitive tools are preserved. Saved
F32 categorical draws replay every observed sampled token; exp weights are
normalized once, never subjected to a second softmax. All18 CPU-only runner
and finalizer tests pass. Ignored payloads are not backed up by Git.

Use only `run-002/listening-reference-conditioning/` for the first pass:

- `00–02`: original, short and medium source reference inputs;
- `03`: reused RU-stress `Ладно.` A, the known near-silent negative control;
- `04–07`: the same short phrase, short B/C then medium B/C;
- `08`: reused Base long-English A;
- `09–12`: the same English text, short B/C then medium B/C.

These13 WAVs retain original levels and exact source bytes; none was removed
because of duration or energy. README lists the full expected texts. Selection
is limited to one short failure and one long voice control, not the full
matrix; other new RU/EN cases remain unlistened. Exact-WAV deduplication found
no duplicates in this selection. Judge full words, unwanted sounds, voice
stability/reference likeness and stress separately. Source-crop ASR evidence
is reused from run001 only because source/padding/text bytes match exactly;
the two ASR word-ending discrepancies and absent crop-specific listening
remain recorded. No new ASR or human verification is claimed.

The synthesis probe is the retained static `afa3df01` research executable,
SHA256 `6c86e4d69f0c0dbc26e35c360e0b6903dc976b0ad61aa3c34dbbaaa1bbe0f6fa`.
The existing `qwen-codec` helper build `4e47ed26`, SHA256
`0fd8434ef20bd4c921ce89ea473c1d43ec6d2f410d0e722563ddaf234b7a6170`,
was copied alone into an isolated helper directory. Both use the retained
`eos-corpus-decision-20261121/runtime-current` GGML DLLs, whose exact identities
match A. No model/DLL copy or new download was needed. The successful original
latent-regeneration gate precedes and validates the new crop extraction.

**Decision:** retain shorter full ICL as a promising conditioning/latency
candidate and obtain exact-artifact listening. Do not disable ICL, promote a
short reference, claim a universal EOS fix or infer an engine defect from
changed outputs. Native/source causal work and Engine51 qualification remain
separate. No production default, engine/model pin, ABI6, QTB, package, merge,
tag or release changed.

## Preserved run001 history: preparation and expired-lease refusal

The remaining sections describe only the sealed historical run001, not the
current run002 result. Its zero native attempts and original stopping boundary
are deliberately preserved.

- Date:2026-11-24. Research only; R1 remains **NO-GO**.
- Frozen [batch plan](native-reference-source-plan-20261124.md).
- Canonical model receipts: [RU-stress](native-reference-conditioning-rustress-cmp50hx-20261124.json)
  and [Base](native-reference-conditioning-base-cmp50hx-20261124.json).

## Outcome and exact stopping boundary

The reference A/B/C comparison is **not_run**, not a negative model result.
CPU preparation completed, but **zero native extractions, zero AR attempts
and zero synthesized WAVs** were produced. Original-latent regeneration,
short/medium candidate latents, EOS observations and latency measurements
therefore remain not_run.

The shared1800s batch began06:15:20UTC, with the frozen absolute monotonic
deadline3170194.937 /06:45:20UTC. When the supplied reference lease was used,
the runner rejected it before launching the extractor: the deadline had
already expired. Immediately afterwards the observed clock was06:47:55UTC,
monotonic3170349.859. The recorded error is
`explicit execution and existing finite shared<=1800s deadline required`.
The deadline was not reset and no GPU child was launched. This check does
not say that extraction or either checkpoint failed; neither was evaluated.
The exact refusal is preserved in `run-001/execution-refusal.json`.

## Prepared inputs and checks

The actual original Kraftwerk reference remains17.6s PCM16 mono24kHz,
422400samples; SHA256
`90e5f7576991ea5b9f0a85e9109f7bd31ff667c4a12d58783a06c650796c3ca1`.
Its complete transcript was previously confirmed by the user. No original
or historical WAV, model, sealed inventory or latent file was modified.

| Fragment | Exact source samples, end-exclusive | Duration | Transcript | Expected reference frames |
| --- | --- | ---: | --- | ---: |
| Short |0..96000 |4.00s | `Я твой слуга, я твой работник.` |56 |
| Medium |96960..309120 |8.84s | `Жёлтый луч мягко лёг на шестерёнки; внизу щёлкнуло реле, сверху загудел вентилятор.` |116 |

Each PCM payload is an exact continuous slice, without resampling,
normalization, trimming inside the slice, or synthesized replacement.
Nonzero cut boundaries have at least100ms measured silence on each side,
using existing FFmpeg `silencedetect=noise=-35dB:d=0.10`. The original native
ICL preparation appends12000zero samples before extraction; the same padding
was prepared for all three references. The table's56/116 counts, and226 for
the original, are **derived expected counts**, not newly encoded codes.

Offline cached faster-whisper-small, CPU/int8,8threads, beam5, Russian,
word timestamps ON and VAD OFF, was run on all three source WAVs. It supports
the complete short phrase and natural sentence boundaries. Both medium and
full ASR return `шестерёнке`/`загудил` instead of the user-confirmed registry's
`шестерёнки`/`загудел`. The raw recognition/timestamps, local model hashes and
that discrepancy are retained. ASR does not supersede the user's transcript
confirmation or establish forced alignment/new crop-specific human listening.

Twelve model-free runner tests pass: fixed text/seed matrix, sample boundaries
and silence margins, rejection of word cuts/invalid sizes, exact integer PCM,
exclusive writes, native11-bit RVQ unpacking/codebook order, original-latent
equality gate, original-versus-crop speaker split and storage bounds. The
prepared candidate RVQ inputs have not been encoded by those tests.

## Preserved experimental design

Use aligned full ICL and unchanged stochastic Talker/Predictor defaults.
For RU-stress and Base compare original A, each crop with original speaker B,
and each crop with crop-derived speaker C. Keep the four frozen text/seed
pairs from the batch plan; do not select new seeds after outcomes.

The runner first requires exact original-reference speaker and complete-code
regeneration before any crop synthesis. It preserves both failed equality
checks rather than proceeding with a changed extraction baseline. This gate
has **not run**. The existing extractor and retained corrected static probe
are reused in place; no model, DLL or release-package copy was created.

The prospective probe is the retained `afa3df01` build, SHA256
`6c86e4d69f0c0dbc26e35c360e0b6903dc976b0ad61aa3c34dbbaaa1bbe0f6fa`.
No execution of that probe occurred in this stage. Prior aligned A outputs
were rechecked against70sealed identities and their pinned inventory; they
remain previous results, not newly performed controls or B/C evidence.

The fixed plan contains32new diagnostic attempts and64observer-OFF streaming
attempts across eight conditioning cells. Diagnostic prefill/logits times
must stay separate from first-PCM timings; first PCM is not first audible
speech. All96new attempts remain not_run. No reference-related quality,
prefill or TTFA improvement was measured.

## Evidence and listening selection

Payload root:
`.tmp/base-acceptance/reference-conditioning-cmp50hx-20261124/run-001/`.
The sealed inventory covers40files/4721270bytes, excluding itself; SHA256
`13b5d577307da2fc4066a271bfb4be1a01e98bf63edac9dfb4b3d0dd4e5a6825`.
It retains exact crops/padding/transcripts, prospective jobs, CPU ASR,
silence log,12-test result, refusal, preserved transitive runners and audit.
Ignored payloads are not transferred or backed up by Git.

`listening-reference-inputs/` contains only three unmodified reference inputs:
00original,01short and02medium, plus README and exact-copy manifest. These
are **not generated comparison outputs**; no new model/listening success is
claimed. There are no duplicate synthesized candidates to hand off.

A separately authorized new bounded batch can reuse this preparation, first
execute the original-extraction gate and then run the unchanged B/C matrix.
The current batch cannot be continued by resetting its deadline. Base and
RU-stress retain separate receipts; earlier positive/failed listening remains
attached to its exact artifacts. Root-cause attribution, shorter-reference
benefit, voice fidelity and numerical parity remain unresolved.

No production default, model/engine pin, Bridge gitlink, ABI6, QTB, frozen
R1package, merge, tag or release changed. Full-text layout remains the
completed negative experiment; rollback development remains frozen.
