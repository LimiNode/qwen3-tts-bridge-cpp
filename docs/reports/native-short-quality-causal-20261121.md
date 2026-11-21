# Short-answer quality: baseline and prefix controls

Date: 2026-11-21. Research only; no production defaults, engine pin, ABI,
model weights or release packages change.

This follows the [short-utterance listening findings](native-prefill-short-20261121.md).
Keep two findings separate: several baseline outputs already contain unwanted
vocalizations, while the baseline/prefix-MMQ `Hi!` seed64 pair has a directly
reported regression (files11/12: `Hi` versus `Hi` followed by laughter).
The measured prefix speedup remains an experimental candidate, not a quality
or early-EOS fix. Longer Base/Kraftwerk listening is a separate scope.

## Source audit

The audit compares the native engine with the retained Python source
`25cc5886` and speech.cpp comparator `fd747c11`. Source inspection does not
establish the cause of the heard cough or laughter.

- Native default Talker/predictor temperature0.9, top-k50, top-p1.0 and
  Talker repetition penalty1.05 match the retained CustomVoice checkpoint.
- Minimum-two-frame EOS suppression matches the reference. The additional
  adaptive native EOS guard is disabled by default and was not enabled by the
  retained probe. Do not attribute these baseline outcomes to that guard.
- Native prompt wrappers and full-text conditioning match the reference's
  `non_streaming_mode=True` branch. Python's public default is `False`;
  this is an untested conditioning-mode comparison, not a proven prompt bug.
- Native and speech.cpp use different random generators and categorical
  sampling implementations. Equal numeric seeds are not paired random draws.
- Slots, Talker history/cache position and codec state have explicit resets.
  This does not prove absence of state leakage; fresh-process controls are
  required before attributing a failure to persistent state.

Two control limitations matter for subsequent experiments. Native greedy
Talker selection bypasses repetition processing; therefore the intended
deterministic Talker control is `do_sample=true, top_k=1`, not greedy mode.
Request-specific predictor top-k/top-p are not forwarded to its existing
graph; the predictor control must use its implemented per-request greedy
switch instead. Neither limitation explains the unchanged stochastic defaults.
No production sampler repair is bundled into this study.

## Frozen causal repeat

Local payloads are under
`.tmp/base-acceptance/short-quality-causal-20261121/trace-001/`.
CMP50HX UUID `GPU-40361931-6cb5-ac58-a059-5ba3e70986fb`, driver581.94,
CustomVoice1.7B Q8_0 / `ryan` and matched F16 codec are unchanged from the
preceding study. Probe SHA-256 is
`7e9ff122761e48b435272609980ae23692ed84f9794d7caa7feddc7ac0558443`;
patched CUDA DLL is
`bd54280b060357d21d0345cd1ecbc3f58e220b169561cd44f4c3a42255661b30`.
All nine retained runtime files and both models match their before/after hashes.
This is the same statically linked internal probe, not a Bridge/native-worker
or packaged-DLL acceptance run.

The predeclared122 requests use20 fresh processes:

- Seven failing/control text-seed pairs, each repeated twice as the first and
  only request in independent processes (14 requests).
- The original full18-request Russian/English schedules, with no prefix and
  prefix-MMQ (72 requests).
- The full18-request English schedule with ordinary prefix, then forced MMQ
  without prefix (36 requests).

Every request retains float PCM, PCM16 mono24kHz WAV, seed, input identity,
terminal status and up to128 complete16-code frames. There are no tensor dumps.
All122 results and valid finite audio are retained; no evidence-collection or
integrity issue occurred. Four outcomes reach the256-frame limit: both fresh
`Hi!` seed72 repeats, its original English baseline schedule, and MMQ without
prefix. They remain failures and cause the runner's nonzero exit.

The exact executed runner is archived locally under
`executed-source/run_prefill_quality_causal.py`, SHA-256
`aa54cfa7e5c3fa57da83b54b2955fd5cf2602965baf848b3d78a785b321a0cd0`,
matching the run plan. A subsequent model-free exit-code fix wraps a possible
integrity-error list in `bool`; it does not change the executed GPU experiment.

## What the repeat establishes

| Controlled comparison | Observation | Scope |
| --- | --- | --- |
| Fresh versus prior primed baseline |14/14 exact raw PCM/frame/terminal matches|The selected failures do not require preceding requests or persistent-state contamination.|
| Two independent cold repeats |7/7 exact pairs|Selected outcomes are deterministic in the retained environment.|
| Full trace ON versus original trace OFF |90/90 exact PCM/frame/terminal matches|The bounded observer did not create the selected regression or alter this repeated schedule.|
| Forced MMQ without prefix versus baseline |18/18 exact English matches|Forced dispatch alone does not produce this prefix regression.|
| Prefix-MMQ versus baseline, `Hi!` seed64 |First different code: frame1, codebook1,437→407|The first changed sampled code is acoustic `c1`, not Talker `c0`.|
| Ordinary prefix versus baseline, same case |First different code: frame1, codebook5,223→205|A separate prefix trajectory; not evidence that MMQ and ordinary prefix fail identically.|

Frame indices are zero-based. The full first16-code frame is identical in the
`Hi!` baseline/MMQ pair; the first two Talker codes also remain1995,415.
Prefix-MMQ's prefill logits already differ (max absolute difference0.362664,
same argmax). The predictor consumes Talker hidden state as well as `c0`, so
equal primary codes do not imply equal acoustic sampling inputs. Its changed
`c1` enters subsequent audio and Talker history. The earlier heard laughter
belongs to a changed generated trajectory, not WAV copying or decoder output
truncation. This does not yet identify the first differing hidden operation
or prove that frame1 itself encodes laughter.

The fresh-process results rule out a required preceding-request effect for
these exact failures. They do not distinguish intrinsic checkpoint behavior,
quantization/numerical effects, short-prompt conditioning and sampling policy.
No general cache-isolation or model-quality proof follows from these controls.

## Independent sampler controls

`sampler-001/` adds54 requests in six language-isolated processes. Each starts
and ends with an unchanged longer primer, and repeats each selected short
text/seed twice. Prefix reuse stays OFF throughout. The only independent
changes are Talker `do_sample=true, top_k=1` or predictor sampling disabled;
the two controls are not combined. Effective temperatures, top-k/top-p,
repetition policy, minimum-two-frame suppression and EOS-guard settings are
echoed and validated, not inferred from manifest fields.

The modified diagnostic probe SHA-256 is
`91368b96d53972332a82d4ce98afa10db3116e373fe0ac121b6f866fa59f6cba`.
Its sole changed C++ source is `tests/eos_research_probe.cpp`, SHA-256
`ceabfb298584ec546834693505e22d77dbd42859fedd46910fc620865a47a3ec`;
the linked qwen-core archive stayed byte-identical before/after compilation
(`bce8022a28b275edbe84a61a549f19dadac539e2603a0fa67091e5605bb62dc7`).
The engine's `src/` has no changes relative to the retained53ac793c build.
The new executable lives in an isolated directory with no DLL overrides;
the original frozen runtime supplies dependencies. Both models, all original
runtime files and the new executable pass after-run identity checks.
The exact executed sampler runner is retained under `executed-source/`,
SHA-256 `f43e2a0c397f22b33fe9e7b7707e36e5b6b534fb79f2ccdf031257bd905554ce`.

All54 finite PCM outcomes are retained. The18 unchanged default-control
outputs match the earlier same-text/seed reference exactly. Every one of the
21 selected same-control/seed repeat pairs also matches. Default `Hi!` seed72
again hits the256-frame limit in both repeats; no run is relabeled successful
because the collector completed. Both alternative controls reach natural EOS
in all14 selected short outcomes each. Their four primer outcomes per control
also finish naturally. This is not a test of unseen texts or unseen seeds.

| Text / seed | Baseline duration, s | Talker top-1, s | Predictor greedy, s |
| --- | --- | --- | --- |
| `Нет.` /64 |1.68|0.80|10.56|
| `Нет.` /75 |15.76|0.56|0.96|
| `Спасибо.` /65 |6.16|1.12|2.56|
| `Готово.` /64 |3.28|1.44|2.24|
| `No.` /64 |2.72|0.72|1.60|
| `Hi!` /64 |1.12|0.64|7.12|
| `Hi!` /72 |20.48, token limit|0.56|0.56|

Durations are artifact descriptions, not text-coverage scores. In particular,
shorter Talker top-1 output must not be called clean speech before listening.
Predictor greedy lengthens two cases despite finishing naturally, so it is
not an automatic fix either. The trace confirms independent interventions:
Talker top-1 first changes `c0`; predictor greedy first changes an acoustic
code. No new latency benchmark is claimed.

## One new listening directory

`.tmp/base-acceptance/short-quality-causal-20261121/listening-quality-controls/`
contains21 numbered unchanged WAV copies and `README.txt` with expected text.
Consecutive triples are baseline / Talker top-1 / predictor greedy. Cases are
ordered as in the table above:01-03,04-06,07-09,10-12,13-15,16-18,19-21.
The full matrix includes both repeats; the listening selection uses the first
repeat, including the20.48s baseline failure, without trimming or normalization.
The user subsequently listened to all21 named files; the exact observations
are recorded below. The immutable generated manifest/analysis retain their
historical `not_run` fields. Current listening status is owned by the tracked
receipts, not by relabeling the original generated payloads. Earlier listening
observations remain attached to their original files.

The offline `analyze.py`, its hash and per-file source/copy hashes are retained
with `analysis.json`. The tracked [canonical receipt](native-short-quality-causal-cmp50hx-20261121.json)
records failed mixed-control natural-EOS mechanics, failed mixed-control
listening and release blocked separately. Candidate-specific receipts below
separate the partial positive Talker result from failed baseline/predictor
controls. No failed historical receipt is superseded. A concrete prefix-MMQ
quality regression remains open regardless of these no-prefix sampler results.

## Twenty-one-file user listening

Observer: user,2026-11-21. Only the named first-repeat WAVs are directly
assessed. Source/copy identity is rechecked against the immutable manifest;
no synthesis, waveform editing, trimming or normalization accompanies this
feedback update. Do not transfer a listening verdict to the second repeat,
primers, held-out cases, Base/Kraftwerk, RTX4090 or production packages.

Independent read-only checking confirms all21 listening files match the
manifest, source WAV, float PCM and exact PCM16 mono24kHz conversion. Seeds,
effective controls, text identities and first-repeat mapping agree; all21
payloads are distinct. The immutable manifest is48,899 bytes, SHA-256
`6fa7de4a5ed69b7af274d19f6586e84cbdbbbfe673eb9de7d42354c4b28fe74a`.

| File | Control | User observation |
| --- | --- | --- |
|01|Baseline|Laughter, then `Нет`.|
|02|Talker top-1|Sad-sounding `Нет`.|
|03|Predictor greedy|`Пшшшш`-like noise; requested `Нет` not confirmed.|
|04|Baseline|`ммм`, then `Нет`, then extensive meaningless extra speech.|
|05|Talker top-1|Ordinary `Нет`.|
|06|Predictor greedy|Sad-sounding `Нет`.|
|07|Baseline|Laughter, then `Спасибо`.|
|08|Talker top-1|`Спасибо`.|
|09|Predictor greedy|Laughter, then `Спасибо`.|
|10|Baseline|`Га га то ва`: distorted/repeated syllables, not labeled laughter.|
|11|Talker top-1|`Гатова`, explicitly clarified as `Готово`, slightly syllabic.|
|12|Predictor greedy|`Готово`, slightly stretched.|
|13|Baseline|Laughter, then `No`.|
|14|Talker top-1|`No`.|
|15|Predictor greedy|`No`.|
|16|Baseline|`Hi!`.|
|17|Talker top-1|`Hi!` sounding like `Хау`; pronunciation concern.|
|18|Predictor greedy|`Хау`-like `Hi!` twice, followed by unidentified English speech.|
|19|Baseline|Intermittent excited breathing, `Hi!`, more breathing, then `с... с... сс`-like sounds.|
|20|Talker top-1|`Hi!`.|
|21|Predictor greedy|`Hi!`.|

Sad affect in02/06 is an observation, not a failure against an unspecified
style instruction. In11 the observer explicitly recognizes `Готово`;
slightly syllabic delivery is not silently equated with baseline10's repeated
syllables. The spelling `Гатова` alone does not establish an incorrect Russian
word or stress pattern. For17, retain both recognition of `Hi!` and the
`Хау`-like pronunciation concern; do not invent a phonetic transcription,
declare it correct, or claim an unrelated word was definitely substituted.
No transcript is invented for the extra speech in04/18.

The separate indexed listening receipts are:

- [Baseline,7 files](native-short-quality-default-listening-cmp50hx-20261121.json):
  `fail`. One clean reported `Hi!` does not cancel laughter, distorted syllables
  and extra speech in the other selected controls.
- [Talker top-1,7 files](native-short-quality-talker-top1-listening-cmp50hx-20261121.json):
  scoped `partial_pass`, aggregate listening `not_assessed`. No laughter,
  cough or extra speech is reported in these seven files, but17 has a
  pronunciation concern and broader voice/identity criteria are not assessed.
- [Predictor greedy,7 files](native-short-quality-predictor-greedy-listening-cmp50hx-20261121.json):
  `fail`. Noise in03, laughter in09 and repetition/extra speech in18 disqualify
  a general repair even though06/12/15/21 contain recognizable target words.

Talker top-1 removes the reported large extra-vocalization failures in the
selected baseline pairs01/02,04/05,07/08,13/14 and19/20. Baseline10's distorted
syllables become recognizable, slightly syllabic `Готово` in11. This is useful
selected-case evidence, not a7/7 clean-speech score or an estimated success
rate on unseen texts. Natural EOS with predictor greedy did not guarantee
requested speech quality. These are late/extraneous-generation observations,
not proof of a general repair for the earlier Base/RU-stress early-EOS problem.

The next bounded investigation should prioritize Talker top-1 with unchanged
predictor sampling on held-out short/longer texts and seeds, retaining all
failures and confirming17's pronunciation separately. Prefix is OFF in all
these sampler controls; no prefix-plus-top-1 interaction or new latency result
has been checked. Keep the measured prefix acceleration as an independent
experimental candidate. No default, engine pin, EOS policy or release status
changes because of this listening feedback.

### Reproduction

The published harness and model-free checks are engine commit
[`7195258219ff41873805310da19a16e4474c1c26`](https://github.com/LimiNode/qwentts.cpp/commit/7195258219ff41873805310da19a16e4474c1c26)
in Draft PR50. Local prefill Python discovery ran62 tests:61 passed, one
optional dependency test skipped. Probe self-tests and the native sampling
and EOS-guard contract executables passed without loading models. Exact-HEAD
engine GitHub CI completed2/2 successfully. This does not qualify CUDA audio.

From that engine research checkout, with retained root-local payloads present:

```powershell
python tests/run_prefill_quality_causal.py --repo <bridge-root> --output <bridge-root>/.tmp/base-acceptance/<NEW-trace-run> --seconds 1200
python tests/run_prefill_quality_causal.py --repo <bridge-root> --output <bridge-root>/.tmp/base-acceptance/<NEW-sampler-run> --sampler-probe <isolated-probe-directory>/eos-research-probe.exe --seconds 900
python -m unittest discover -s tests -p 'test*prefill*.py'
```

The harness pins probe/model/runtime identities, rejects an existing output
directory and leaves time-limited requests marked `not_run` or failed. Scripts
do not download models, select RTX4090, alter production defaults or promote
the Bridge engine pin. Actual GPU experiments finished within the agreed
30-minute CMP budget (approximately19:01-19:10 UTC); the GPU is idle afterward.

## Evidence boundary

Existing exact-file listening remains in its original failed canonical
receipts. New audio requires a new observation; duration, natural EOS and
recognizable target words do not establish absence of extra sounds. Diagnostic
trace runs are not latency measurements. A result that reaches its token limit
is retained as a failed outcome, not silently excluded or counted as natural EOS.
