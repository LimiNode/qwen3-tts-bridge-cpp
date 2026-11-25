# Native stress-model and full-ICL comparison

2026-11-25 continuation: [retained observations, hypotheses and recommendations](tts-research-findings-and-next-stage-20261125.md).
This comparison is complete at PR #334 / `ce6b0f30`; new work is separate.

- Date: 2026-11-24. Research only; R1 remains **NO-GO**.
- Bridge input: `512ff5ce23137a18671a7f3ef0cae8e97068190d`.
- Scope: current RU-stress, RU-Stress-CF and Base control at Q8_0,
  unchanged stochastic sampling, original versus short full ICL, and the
  original Kraftwerk speaker vector. No speaker-only fallback or EOS recovery.

## Preparation and provenance

The user-authorized cleanup removed redundant copies and compiler intermediates,
not unique listening evidence. Storage no longer prevents this experiment.
New weights are exclusively under the canonical ignored `models/ru-stress-cf/`.
Earlier storage refusals and source-only results remain historical evidence.

CPU-only merge, F32 conversion, Q8 quantization and tensor audit completed in
211.625 seconds. The unchanged trusted merger consumed the exact Base revision
`fd4b254389122332181a7c3db7f27e918eec64e3`, checkpoint SHA256
`38fc7fc51c5e776e840414b6fd443962e9411b9654888fd7913e4da643cb857c`,
and pinned CF adapter revision `c16b3af3db3095120efc1ebb73f6522442bcb3b1`,
adapter SHA256 `88a94c0fbe85800d309f94bb9c28d698bf9c86d9494617b6cf4dd996cc13648b`.

The converter is the unchanged `130cb99` source. The CPU-only quantizer binary
advertises `06a22e2`, SHA256
`a1724c2175ee1252d636049926b71f90cf4176ba831a2c42cad3e3d6d835ab6e`;
its current retained checkout is not relabelled as the binary build revision.
The converter writes 480 tensors with zero unhandled tensors. All 196 merged
BF16 targets match the prior CPU CF-source hashes; the other 284 tensors are
unchanged. All 284 non-target Q8 payloads match canonical Base byte-for-byte,
and all 196 target payloads differ. Independent review reproduced these checks
and verified all 38 frozen inputs and eight model outputs.

| Model | Talker SHA256 |
| --- | --- |
| RU-stress | `f4672741608d145fae169075cb0ec775a5382cbe9183eccb59c7ab9cc4797427` |
| RU-Stress-CF | `de5ab0b516de7f6f6d04e9375e3a59a7b4e4ff714c5a898f89269588d2223596` |
| Base control | `4b9a33a236908dd9435a42f7a396e38038329d053b704342a6413c08544c4fda` |

All use the unchanged common codec, SHA256
`1883beeed99348fc35e23dd225e9082f93f6f8c109330a33d935baa8acdbfd94`.
CF licensing/provenance caveats in the
[candidate assessment](native-stress-candidates-20261124.md) remain unresolved.
Preparation is not speech, stress, voice or release acceptance.

## Frozen execution design

The unchanged [UTF-8 corpus](native-stress-model-comparison-corpus-20261124.json)
defines 16 texts and 22 text/seed pairs. Three models and two reference inputs
give 132 primary attempts. Original/short references retain 226/56 complete
16-codebook frames, matching decoder context, their exact transcripts and
the same original 2048-value speaker vector. No clipping, normalization,
retry, seed search, Talker top-1, prefix reuse or EOS penalty is enabled.

The retained static research probe is build `afa3df01`, SHA256
`6c86e4d69f0c0dbc26e35c360e0b6903dc976b0ad61aa3c34dbbaaa1bbe0f6fa`.
It uses full aligned ICL, ordinary streaming with maximum chunk size eight
frames, the unchanged effective sampler and a 256-frame generation cap.
Decision/prefill observers are OFF; complete codes, raw PCM, chunks and WAVs
are preserved. Natural EOS and non-empty PCM are not semantic quality tests.

An additional 96 timing attempts use ABBA reference order per model:
original / short / short / original. Each fresh process runs four warm-up
requests and four measured requests; text order reverses in alternating
blocks. The probe fixes reference conditioning per process, so this is a
balanced **fresh-process warm comparison**, not same-session reference
switching. First PCM callback is not first audible/intelligible speech, and
these direct-engine measurements do not qualify Bridge/QTB/playback latency.

The user authorized one new non-renewable 1800-second CMP 50HX allocation.
Its coordinator starts at `2026-11-24T19:09:05.575582+00:00`, machine-monotonic
`3214819.968`, with shared deadline `3216619.968`. Preparation above did not
use that allocation. All children inherit the remaining time; the coordinator
owns process-tree termination. New payload root:
`.tmp/base-acceptance/stress-model-comparison-cmp50hx-20261124/`.
The frozen plan SHA256 is
`2062033636dd7cc039456283602dad818666288e0ad27542d8a36708fc3ef66f`.
Eleven model-free runner tests and independent checks of all 18 manifests /
228 text-seed-language bindings passed before GPU use.

## Completed execution and mechanical observations

All 18 jobs completed: 132 frozen primary attempts and 96 timing controls,
228 total. GPU-stage wall time was 351.422 seconds, including coordination,
not a CUDA-kernel sum. The coordinator finished in 402.328 seconds, exit 0,
without deadline or process-tree termination. All frozen identities remain
unchanged. All 228 outputs have complete 16-codebook histories, finite PCM,
natural EOS and conserved chunk/sample counts. These are mechanical checks,
not evidence that all 228 requests contain the intended speech.

| Model / full-ICL reference | Attempts | Near-silent diagnostic | At most three generated frames |
| --- | ---: | ---: | ---: |
| RU-stress / original | 22 | 6 | 10 |
| RU-stress / short | 22 | 0 | 0 |
| CF / original | 22 | 6 | 9 |
| CF / short | 22 | 0 | 0 |
| Base / original | 22 | 0 | 0 |
| Base / short | 22 | 0 | 0 |

Near-silent means normalized raw PCM RMS below 0.0001 **and** absolute peak
below 0.001, recomputed independently. The three-frame column is a descriptive
flag, not a universal minimum speech duration or an automatic recovery gate.
The CF adapter does not remove the original-reference early-EOS/near-silence
cases in this corpus. Short full ICL eliminates these numerical flags in
both stress-model cells, without removing ICL cloning. This is a promising
conditioning candidate, not a general EOS fix: reference length, phonetic
content, transcript and decoder context change together. Subsequent scoped
listening below includes a short-reference voice-continuity failure, despite
the absence of numerical silence/short-duration flags.

## Balanced warm latency observations

Each cell below contains eight measured warm requests: four frozen texts in
each of two fresh-process blocks. Medians pool those eight callbacks; the
full results also retain each text separately with two observations each.
The first four requests of every timing process are warm-up only. No
diagnostic observers or tensor dumps contaminate these timing controls.

| Model / full-ICL reference | First PCM median, ms | Prefill median, ms | Long-text RTF range |
| --- | ---: | ---: | ---: |
| RU-stress / original | 179.000 | 153.306 | 0.294–0.305 |
| RU-stress / short | 82.730 | 60.290 | 0.279–0.281 |
| CF / original | 179.277 | 153.743 | 0.296–0.299 |
| CF / short | 82.719 | 60.189 | 0.278–0.282 |
| Base / original | 179.088 | 153.319 | 0.295–0.298 |
| Base / short | 83.329 | 60.581 | 0.278–0.280 |

Thus the earlier approximately 178→83 ms observation is reproduced without
reusing historical original-reference timings. This is lower latency from
changed conditioning, not an equivalent kernel/prefix-cache optimization.
First PCM includes prefill and engine request admission, not model load in
these warm requests; it does not establish first **usable speech**. RTF is
engine total request time divided by generated audio duration. The long-text
figures exclude failed tiny outputs, which are not evidence of fast speech.
Sample sizes remain small and do not establish robust deployment percentiles.

## Integrity, listening and remaining gates

Independent postflight verified every one of the 863 inventory entries,
121,997,405 bytes; every raw F32→PCM16 WAV conversion is exact. All 96
matrix/timing/within-process repeat comparisons reproduce complete codes
and PCM byte-for-byte. This includes 16 same-process repeat pairs per model;
it is not ordinary Bridge/worker restart qualification. Inventory SHA256:
`57081d75454d4eb1635f804a0c8b6f2754fe3d336b93c0db62da5532e100b32d`.

One first-pass selection contains 25 exact WAV copies, numbered 00–24,
under `run-001/listening-stress-comparison/`. 00 is the original voice
reference. Each four-file block contains `Ладно.`, `All right.`,
`Он произнёс слово «до́кументы».`, and the long Russian voice control:

| File numbers | Model / reference |
| --- | --- |
| 01–04 | RU-stress / original |
| 05–08 | RU-stress / short |
| 09–12 | CF / original |
| 13–16 | CF / short |
| 17–20 | Base / original |
| 21–24 | Base / short |

At initial handoff, all new generated WAVs were not listened to. The sealed
README and raw run preserve that historical state; current listening is in
the canonical receipts and the following section, not rewritten raw payloads.
Exact expected text and numerical flags are in README.txt; failed controls
are deliberately retained.
The full 132-case matrix, including homograph/processor stress pairs and
English voice stability controls, remains available separately. The small
selection does not qualify unselected cases or replace whole-matrix review.

Three separate schema-v2 canonical receipts retain model-specific identities:
[RU-stress](native-stress-comparison-rustress-cmp50hx-20261124.json),
[CF](native-stress-comparison-cf-cmp50hx-20261124.json), and
[Base](native-stress-comparison-base-cmp50hx-20261124.json).
Whole-matrix semantic completeness, prescribed-stress accuracy, continuous
voice identity, worker lifecycle, package relocation and RTX 4090 are not
qualified. Scoped observations below do not promote conditioning or an
EOS-penalty policy.
No production defaults, model/engine pins, Bridge gitlinks, ABI, QTB, frozen
package, merge, tag or release are changed; R1 remains **NO-GO**.

## User listening follow-up, 2026-11-24

The user assessed generated files 01-24, without a new statement about reference 00.
Each file's original byte count and SHA256 remain in its separate model receipt;
no original WAV, complete code, sealed inventory or mechanical result changed.

| Files | Model / reference | Initial user observation (refined below) |
| --- | --- | --- |
| 01 | RU-stress / original | No voice |
| 02 | RU-stress / original | Strange sound |
| 03 | RU-stress / original | Only «Он произнёс слово», then sharp cutoff; requested word missing |
| 04 | RU-stress / original | Normal |
| 05–07 | RU-stress / short | Normal |
| 08 | RU-stress / short | Voice changes after the middle |
| 09–10 | CF / original | Empty |
| 11 | CF / original | Normal |
| 12 | CF / original | Normal speech, but voice ends abruptly |
| 13–16 | CF / short | Normal |
| 17–24 | Base / both | Normal |

RU-stress and CF retain failed scoped listening because their selected
original-reference failures are not erased by positive short-reference cases.
RU-stress 08 additionally fails voice continuity. Base initially had scoped
`partial_pass`; the stress-specific clarification below changes it to `fail`
for a localized pronunciation artifact. Short CF 13-16
is the positive stress-model candidate in this selection, not a proven
full-ICL stress/voice solution. Do not attribute 08 to session state, model,
quantization or reference length without a distinguishing repeat.

### Prescribed-stress clarification, 2026-11-24

Files 03/07/11/15/19/23 deliberately request **до́кументы**, not the normative
**докуме́нты**, to test counter-dictionary U+0301 control. After the initial
general pronunciation caveat, the user supplied exact same-artifact feedback:

| File | Model / full-ICL reference | Refined user observation |
| --- | --- | --- |
| 07 | RU-stress / short | Initially reported ordinary stress; 2026-11-25 re-listening makes stress uncertain, possibly О (not_assessed) |
| 11 | CF / original | Stress on О: matches the requested word stress |
| 15 | CF / short | Stress on О: matches the requested word stress |
| 19 | Base / original | Sounds like «доикументы», with «доик» instead of «док»; stress on И is tentative |
| 23 | Base / short | Same reported «доик» distortion; stress on И is tentative |

These five files share the exact text, seed 64 and group 17; the model and
full-ICL reference arm differ. Their original WAV hashes remain in the
respective receipts. CF has a local positive prescribed-stress result with
both references, not a success rate or acceptance of the whole stress corpus.
The combined voice/instruction criterion remains unassessed for CF because
reference-voice fidelity and broader instructions were not separately assessed.
RU-stress 07's initially reported stress failure was withdrawn after the user's
2026-11-25 re-listening: stress is difficult to determine and may be on О.
Its earlier normal-speech observation remains, but prescribed-stress compliance
is now `not_assessed`, not pass or fail. The confirmed voice drift in 08 is
independent and unchanged.

Base 19/23 now fail the scoped pronunciation-artifact criterion. This changes
its aggregate listening/case results to `fail`, preserving the earlier
`partial_pass` as historical general feedback and the positive observations
for 17/18/20/21/22/24. The user did not claim that the whole sentence is
unintelligible or missing, nor that these two cases end early. Exact stress
on И remains uncertain; no phonetic cause is assigned. For 03 the requested
word is absent, independently of the unusual target stress. Remaining stress
pairs, seeds and voice/lifecycle/release gates are still unassessed.

### Paired listening selection and re-listening correction, 2026-11-25

The user's re-listening correction for old selection 07 is recorded above:
its prescribed stress is uncertain, possibly О, so the previous definite
failure is withdrawn without turning uncertainty into a pass. Other confirmed
RU-stress speech/voice failures and the independent CF/Base observations remain.

To make stress placement easier to compare, a separate selection uses all ten
stress text/seed cases from each existing short-full-ICL RU-stress and CF cell:
20 generated WAVs plus reference 00. The pairs are за́мок/замо́к (seeds 64 and
2027), му́ка/мука́, докуме́нты/до́кументы and проце́ссор/процессо́р (seed 64).
Adjacent odd/even files are a matched pair within one model and seed; the
following pair uses the other model on the same text/seed. No outcome or
duration filtering is used.

Payload folder:
`.tmp/base-acceptance/stress-pairs-listening-20261125/listening-stress-pairs/`.
README.txt supplies exact expected text, target stress and pair numbering;
the parent selection-manifest.json binds each copy to its original WAV, model, seed, full-ICL
conditioning, UTF-8 request and source-row identity. The copies are not
normalized, spliced, faded or regenerated. This adds examples for listening,
not new inference or new seeds beyond the frozen matrix. No new GPU allocation,
engine/model setting, sampler policy or acceptance claim is involved.

Preparation and independent source review verify exact WAV/F32/code identities
and sample conservation. All 863 sealed source artifacts are unchanged before
and after selection. The new selection manifest SHA256 is
`8deead5d031dd2bf52dd212a4e732c0c364ef65b255432ec7e4c48bb4000ded1`;
its inventory SHA256 is
`f4dafdd0c53b7165f83bf4a6fb407ed6c5b8a6c8b5e994d3421210886b8ab694`.
Separate selection-only receipts for
[RU-stress](native-stress-pairs-rustress-cmp50hx-20261125.json) and
[CF](native-stress-pairs-cf-cmp50hx-20261125.json) bind their ten exact WAV copies
and shared reference/README/script/manifest/inventory identities. At preparation,
only old RU-stress07/new14 and old CF15/new16 had prior scoped listening.
That initial state remains in the sealed README/manifest; current observations
are owned by the tracked receipts. Neither selection receipt supersedes the
failed source comparison or claims new inference. Mechanical checks alone do
not assess stress.

### User assessment of all 20 paired outputs, 2026-11-25

The following numbers refer only to `listening-stress-pairs`, not the earlier
24-file first-pass selection. All use short full aligned ICL (56 reference
frames), the original speaker vector and unchanged stochastic sampling.

| Paired files | Model / seed | Requested contrast | User observation |
| --- | --- | --- | --- |
| 01/02 | RU-stress / 64 | за́мок / замо́к | Alternates as requested |
| 03/04 | CF / 64 | за́мок / замо́к | Alternates as requested |
| 05/06 | RU-stress / 2027 | за́мок / замо́к | Stress alternates; 06 sharply truncates final К, heard as «он произнес слово замо», with К barely starting |
| 07/08 | CF / 2027 | за́мок / замо́к | Alternates as requested |
| 09/10 | RU-stress / 64 | му́ка / мука́ | Alternates without surprises |
| 11/12 | CF / 64 | му́ка / мука́ | Alternates without surprises |
| 13/14 | RU-stress / 64 | докуме́нты / до́кументы | Clear О stress not confirmed in 14; exact heard vowel in 13/14 not specified |
| 15/16 | CF / 64 | докуме́нты / до́кументы | Clear О stress only in 16 among 13–16; no exact vowel verdict supplied for ordinary-stress 15 |
| 17/18 | RU-stress / 64 | проце́ссор / процессо́р | Both requested stresses heard; 17 engineer sounds like «инжинЁр», 18 has no engineer surprise |
| 19/20 | CF / 64 | проце́ссор / процессо́р | Both requested stresses heard |

The engineer observation in paired17 is a vowel/pronunciation distortion,
not necessarily a stress-position error: normative «инжене́р» also stresses
the final syllable. Paired06's incomplete final consonant and paired17's
pronunciation artifact make the RU-stress selection human/case/listening
`fail`, independently of its positive target-word stress results. CF retains
scoped `partial_pass` and aggregate `not_assessed`: the stress observations
do not separately qualify full voice fidelity, every artifact or final tail.
Reference00 has no new verdict. Both release dispositions remain blocked.

Paired14 is the unchanged first-pass RU07. The earlier definite stress-failure
verdict stays withdrawn: the latest user hears clear О only in CF16, but
does not specify a definite alternative stressed vowel in RU14. Paired16 is
unchanged first-pass CF15 and confirms its earlier local О-stress observation.
Each model now has 17 unique heard primary source outputs (eight first-pass
plus nine additional outputs); 27 primary outputs per model and all timing
outputs remain unassessed. Base's receipt and all earlier failures remain
unchanged. No whole-corpus success rate or universal stress support is inferred.

The user's hypothesis that unusual stresses are underrepresented or missing
from training annotation is plausible but unverified: no training-corpus
frequency or annotation statistics were inspected. The observations establish
word/model-dependent controllability, not its training cause. CF16 succeeds
on the same target word/seed that is not clearly confirmed in RU14, so neither
an impossible word nor universally ignored stress marks are established.
A distinguishing follow-up would hold conditioning/sampler fixed and compare
`докуме́нты/до́кументы` across predefined seeds and neutral carrier contexts,
with exact input bytes and separate stress/completeness/artifact judgements.
No new inference or GPU window was used or started while recording feedback.

For paired06, retained source group13 (RU-stress short ICL, seed2027) ends
naturally after 22 frames / 1.76 s, not the 256-frame cap. The earlier exact
F32-to-WAV/copy audit conserves all native samples. This excludes sample loss
in conversion/copying, not a generation/codec end-state defect; the cause of
the missing К is unresolved. Fade or silence cannot reconstruct that consonant.

### Abrupt-ending diagnosis and existing terminal shaping

A read-only follow-up inspected files 03/04/08/12/16/20/24. Every WAV contains
all native samples and matches the exact F32-to-PCM16 conversion and selected
copy identity. All seven ended at natural EOS, not the generation-frame cap.
For 03 (18 frames, 1.44 s) and 12 (89 frames, 7.12 s), the last PCM16 sample is
zero; the final 50 ms RMS is respectively -109.34/-108.80 dBFS. The last 100 ms
RMS is -31.92/-32.22 dBFS. Thus neither lost samples during saving/copying nor a
nonzero final-sample discontinuity explains these two observations. This
does not establish why the generated speech ends abruptly earlier in the
tail; the user's failures remain unchanged. In particular, no missing-word
claim is inferred for 12, whereas the requested word is absent in 03.

The exact report and script are separately hashed artifacts in each model
receipt under `listening-followup-001/`, outside sealed `run-001`. Only 03/04/08
apply to RU-stress, 12/16 to CF, and 20/24 to Base. Numeric endpoint analysis
does not infer listening quality or transfer a verdict across models.

Bridge already has
[`TerminalFadePostProcessor`](../../src/qwen_tts_bridge/audio/terminal_fade_post_processor.hpp):
defaults are 15 ms fade and 85 ms completion silence (0 ms cancellation silence;
error audio is released unchanged). The user-facing player enables it by
default; `qwen_tts_save_wav` requires `--tail`. These direct-probe research
WAVs bypass that post-processor. A 15 ms terminal fade would act on an already
almost-silent interval in 03/12; a pause may change perceived completion but
requires a separate unchanged-versus-shaped A/B. No processed copies were
generated. Fade/padding cannot restore 03's omitted word or repair 08's
mid-track voice change and is not an early-EOS fix.

No GPU inference, new generation, listening transfer, production-default change
or audio modification occurred while recording this feedback.

Handoff validation: all 47 indexed canonical receipts pass the project
validator; the three comparison and two selection receipts also pass actual local artifact byte/hash
verification, including CF preparation and the root-owned GPU-window journals.
The 18-test receipt regression suite has 17 passes and one optional
`jsonschema`-dependency skip; no dependency was installed. Eleven new runner
tests passed before execution and were independently repeated. `git diff
--check` passes. Product C++/worker code was not changed or rebuilt.

Quality review: reuse of the existing native probe and PCM/code helpers avoids
another inference or recovery implementation. Separate model receipts are
required to prevent transferring verdicts across CF/RU-stress/Base; shared
raw payloads remain ignored rather than duplicated in Git. New code is limited
to preserved local experiment supervision/collection, not a new SDK surface.
