# TTS research: retained findings and next-stage decisions

- Date: 2026-11-25.
- Status: active research record and execution plan; not release acceptance.
- Owner: Bridge/native TTS research boundary.
- Completed comparison baseline: PR #334, `ce6b0f30`.
- Review trigger: new exact-artifact listening, completed A–E experiments,
  changed model/runtime, or a separate integration decision.

Current execution update: the first approved A/D window completed all 200
requests on CMP 50HX in 336.766 s. See
[EOS control and manual accent-policy results](native-eos-control-and-manual-accents-20261125.md)
and its separate model receipts. On 2026-11-26 the user reports normal speech
in12–15 and17, truncated final «процессор» in CF18, and unclear «МГУ» in RU20.
These are scoped observations, not general acceptance; D/B/C/E remain open.

This record preserves observations, competing explanations and recommendations.
Canonical JSON receipts still own acceptance statuses. A proposed test is not
an executed result. Earlier failures and sealed payloads must not be rewritten.
R1 remains **NO-GO**; stable voice and complete speech take priority over
reducing first PCM from approximately 180 ms to 83 ms.

## Evidence and conclusions to retain

### EOS can be preferred before any generated audio history

**Observed:** [matched native/source controls](native-source-causal-20261124.md)
reproduce two complete 16-code frames and then EOS for RU-stress `Ладно.`
with the original full ICL, seed 2027, in native Q8 and source CPU FP32.
At matched decisions 0/1/2, allowed-vocabulary temperature-1 EOS probabilities
are native 95.349/95.776/96.523% and source 95.187/95.694/95.799%.
These are not probabilities after the production sampler chain. Minimum two
frames masks EOS eligibility at decisions 0/1, not the underlying preference.

**Conclusion:** native-only sampling/conversion is not necessary for this
specific failure. The unfavorable preference already exists after prefill;
it need not originate solely in previously generated bad audio codes.
This does not prove universal native/source equivalence or a training defect.

**Recommendation:** prioritize controlled Talker EOS interventions on the
original full ICL. Keep numerical parity research separate when a particular
new discrepancy warrants it. Do not call more frames a rescue.

### Reference changes affect both latency and the generated distribution

The [reference study](native-reference-conditioning-20261124.md) retained
the original 17.6-second speaker vector in its B arms:

| Reference audio | Codes / prompt rows | Warm prefill, ms | Warm first PCM, ms |
| --- | --- | ---: | ---: |
| 4.00 s | 56 / 66 | 60.29 | 83.16 |
| 8.84 s | 116 / 126 | 86.62 | 110.72 |
| 17.60 s | 226 / 236 | 152.68 | 178.58 |

These RU-stress CMP 50HX medians initially compared separate runs, reusing
original A. Later balanced fresh-process ABBA short/original controls in the
[three-model study](native-stress-model-comparison-20261124.md) confirm the
latency difference. They are direct-engine warm first callbacks, not physical
playback or first intelligible speech. No kernel/prefix optimization occurred.
The selected shorter-reference recordings have positive listening evidence,
but the later RU-stress short-reference file 08 changes voice mid-phrase.

**Conclusion:** retaining the speaker vector alone does not guarantee voice
identity. Full ICL also includes audio codes, matching transcript and decoder
reference context. Shortening changes duration and phonetic content together;
the current crop comparison cannot isolate duration as the cause of drift.

**Hypotheses, not established causes:** content/coverage and reference length
may independently affect EOS, voice stability and prosody. An 8–12-second
reference may offer a better compromise; there is no accepted optimal length.

**Recommendation:** compare multiple natural fragments at comparable lengths,
holding the original speaker vector and sampler fixed. Assess beginning,
middle and end separately. Never silently substitute speaker-only cloning.

### Prefix reuse remains an optimization candidate, not an equivalent cache

[Prefill](native-prefill-study-20261121.md) and
[differential checks](native-prefill-differential-20261121.md) found changed
logits/codes/PCM under prefix reuse. MMQ controls removed the cough in one
short `Да` case, but broader [short-utterance listening](native-prefill-short-20261121.md)
retained failures and added laughter in one English comparison.

**Recommendation:** preserve the candidate and numerical evidence. Reusing an
independent prefix could avoid repeated reference work in principle, but this
implementation is not a transparent optimization. Do not promote it because
one short WAV sounds correct, or declare long-reference cost irreducible.

### Stress control is word/model dependent in the observed selection

In [the 20-file paired selection](native-stress-model-comparison-20261124.md),
RU-stress and CF follow `за́мок/замо́к`, `му́ка/мука́` and
`проце́ссор/процессо́р` on the declared seeds. Only CF16 has clearly heard
`до́кументы`; RU14 remains not clearly confirmed, not a proven wrong-vowel
failure. RU06 loses final К; RU17 engineer sounds like `инжинЁр` despite
correct processor stress. Normative `инжене́р` also stresses the last syllable:
the latter is a vowel/pronunciation observation, not necessarily shifted stress.
Base's earlier `доикументы` distortion remains a separate failed observation.

**Hypotheses:** rare or inconsistent training annotation may weaken control
of unusual stresses; CF may follow markers more reliably than RU-stress;
selective marking may be more natural than marking every available word.
None is proven: no training-frequency audit exists, one word/seed does not
rank models generally, and the frontend policies have not been compared.
CF16 shows that this exact target word is not universally impossible.

**Recommendation and user requirement clarification:** evaluate ordinary
unmarked pronunciation, normative disambiguation, and deliberately nonstandard
stress separately. Normative control and full ICL are required. Failure to
produce an intentionally wrong stress alone is not a release blocker; phoneme
distortion, missing words and voice drift still are. Preserve failed research
receipts rather than relabeling them accepted after this criterion clarification.

### Natural EOS, sample integrity and shaped tails prove different things

Paired RU06 ends at natural EOS after 22 frames / 1.76 s, below the 256-frame
cap. Exact F32-to-WAV/copy checks preserve all native samples; the lost К's
generation/codec cause remains unresolved. Earlier first-pass03 omits a word,
while CF12 has an abrupt ending without a missing-word claim.

**Recommendation:** use existing terminal fade/pause only as presentation
shaping. It cannot reconstruct a missing consonant/word or fix voice drift.
Duration/energy, natural EOS and complete files are not text-coverage evidence.
Rollback mechanics worked in limited listening controls, but naive short-EOS
thresholds intervened in legitimate short requests and did not establish a
detector. Keep [rollback](native-eos-corpus-checkpoint-20261123.md) as a comparator,
not a newly integrated production policy.

## Next-stage work packages

All tasks have independent results. A model/environment blocker must not stop
unrelated model-free preparation. PR #334 stays the completed comparison
stage; continuation is a separate stacked branch/PR, not a merge or pin update.

### A — Talker EOS control, primary priority

Implement only in a separately compiled native research build, not public ABI
or Bridge defaults. Compare unchanged baseline, constant raw-logit penalties
2/4/6, and one alternative continuation after an early sampled EOS without
new prefill. Preserve baseline selection, effective selection, original seed,
Philox draw/subsequence, intervention step/count and exact policy per attempt.
Define the early window before execution; it is a diagnostic intervention
window, not a qualified premature-EOS detector. Do not raise minimum frames.

Define placement exactly: reserved/minimum masks and existing guard, research
EOS subtraction, repetition penalty, temperature, top-k, top-p, exponential
weights, categorical draw. An alternative restores the same suppressed raw
logits, masks EOS for that one selection, reruns the chain using the same draw,
then restores ordinary EOS eligibility for later decisions. Record its changed
distribution; this is an intervention, not unchanged replay or random retry.
Reject nonbaseline runs combined with guard, forced histories, reseeding,
prefix reuse or changed Predictor policy. Keep state per request.

Use the original full aligned ICL and known failed RU-stress/CF cases plus
correct short controls; save all failures. Separate traced causal runs from
observer-OFF timings. Listen for complete words, extra speech, breathing,
laughter, repetition and final tails. Measure prefill, first PCM, independently
assessed usable-speech onset, total time/RTF, intervention cost, termination
delay, missing text and false interventions. Energy onset is not usable speech.
Only after positive listening consider adaptive decay and a frozen held-out
corpus; no tuning on that corpus. Do not integrate expensive rollback here.

### B — Reference stability, unchanged sampler

Reuse exact 4/8.84/17.6-second references. Add natural alternate fragments at
comparable durations, with separately checked matching transcripts. Keep the
original speaker vector for the main comparison; crop-vector arms are separate.
Reproduce first-pass RU-stress08 (not paired CF08) in fresh processes and a
persistent session with fixed request order and seeds. Compare long RU/EN
beginning/middle/end voice, complete text, prefill/first PCM/RTF and repeat
identity. Add another voice only when an authorized reference and transcript
are available; do not invent a voice or silently download an unrelated sample.
Segment speaker-similarity metrics are supplementary, never listening verdicts.

### C — Alternative models, isolated stock Python first

Prioritize ESpeech RL-V2 and MOSS Local v1.5; Pocket RU is secondary with a
noncommercial license boundary. No new production C++ backend or service.
Pin official instructions/code/weights, dependencies, vocoder/codec and license
identities; audit custom code before execution. Use repository-local isolated
environments and caches; no changes to the worker's installed environment.
Freeze a common corpus of short RU/EN, long RU/EN, normative homographs,
nonstandard stress, technical terms and Kraftwerk cloning. Unsupported English
is an explicit outcome, not an assumed capability. Test ESpeech's native `+`
marker and MOSS's documented Russian IPA path, preserving exact inputs.

Measure cold/warm latency, first PCM, first usable speech, RTF, peak VRAM and
actual streaming granularity. Whole-sentence inference followed by slicing is
not within-sentence incremental generation. Document SM75 versus RTX4090
requirements separately; no access to RTX4090 is currently assumed.
Prepare a compact exact-artifact listening folder, not a duplicate of old WAVs.
Before any large download, account for weights, codec/vocoder, isolated Torch
runtime, package/build caches, temporary copies, results and retained reserve.

### D — Frontend accent policy

Compare no accents, selective accents in ambiguous/rare/problematic words,
and all available accents on RU-stress and CF with unchanged sampler and ICL.
Freeze seeds 64/2027/2029 and neutral carrier contexts before execution.
Include `докуме́нты/до́кументы`; distinguish normative control from extra
counterfactual capability. Preserve raw/effective UTF-8 and actual frontend
version/settings. Manually enumerated text variants must not be presented as
an end-to-end `tts-front-cpp` execution. Judge stress, naturalness, phoneme
distortion, omitted text and voice separately, without editing input mid-run.

### E — Engine #51 integration decision, independent of EOS research

Reuse [independent review](native-engine51-independent-review-20261124.md),
successful exact-head CPU/shared CI and the
[isolated GPU smoke](native-engine51-gpu-smoke-20261124.md); do not repeat
unchanged N=1 checks. Exact head is `541f1f702e725dc002e0e9ebf6f1460dca8c3100`.
Existing CUDA graph tests cover N=1/2/3, mixed stochastic/greedy modes, forced
zero, -1 sentinel and predictor rows. They do not qualify whole-model N=2/3
admission/compaction/retirement with real model/codec state.

The current evidence supports a narrow merge recommendation for the sampler
correction, not a claim of full batched synthesis acceptance. If that broader
qualification is required before integration, the remaining test is an isolated
real-DLL N=2/3 whole-model comparison (solo controls, heterogeneous modes,
distinct requests/seeds, uneven completion and surviving-lane continuity),
not another repetition of graph/N=1 smoke. Present its outcome separately.
Merge authorization and the later reviewed Bridge pin update are distinct;
neither is performed by this plan. Do not absorb other research engine patches.

## Resource gates and result ownership

Preflight on 2026-11-25 sees CMP 50HX 20,480 MiB (11 MiB used) and approximately
11.32 GiB free on E:. GTX1060 is out of scope. The user approved the first A/D allocation:
at most 30 minutes, one model process, 18 GiB peak VRAM, 1 GiB new payload and
2 GiB free reserve. **That window is completed and closed, not awaiting approval.**
Execution rechecked 6.52 GiB free and an idle CMP. One monotonic deadline covered
all 200 requests; actual elapsed 336.766 s, sampled device peak 3544 MiB, final
indexed payload approximately 100.2 MiB and minimum free 6.43 GiB. Exact journals
and bounds are in the linked A/D report; no extension or additional GPU run.
Alternative-model downloads/environments need a separate sized disk decision.

Each task report must state executed/not-run/blocked scope, exact revisions,
inputs/seeds, resource budget, failures and independent listening status.
New model/hardware outcomes require indexed canonical receipts. Existing
receipts are not overwritten to make a larger experiment look accepted.
No production default, ABI, QTB, model/engine pin, frozen package, merge or
release changes are authorized by this research record.

## Preparation completed in this continuation (historical pre-run state)

- A: a separate engine worktree/branch `research/eos-logit-control` implements
  the OFF-by-default `QWEN_RESEARCH_EOS_CONTROL` compile option and strict
  baseline/2/4/6/one-shot policies. GCC15.2 and MSVC19.44 each pass51 focused
  model-free checks; the existing sampler contract also passes. A static MSVC
  probe build and its model-free observer/sampler self-test succeeded. This
  is not an isolated Engine51 build, CTest campaign or GPU/speech result.
  Draft [Engine #53](https://github.com/LimiNode/qwentts.cpp/pull/53), exact
  head `3a896743ada11cba6bfa7e6fd69c06ec39a10283`, is stacked on the prior
  research branch, not the production engine. Feature-OFF pipeline syntax
  also passes MSVC. The inherited unrelated C4244 in research restore remains;
  this is not a warning-free full engine build.
- B: existing references and precise voice-drift reproducer are identified;
  new reference extraction and synthesis are not run. A second voice remains
  unavailable until an authorized matching audio/transcript is supplied.
- C: [official metadata/environment preflight](alternative-tts-preflight-20261125.md)
  records pinned weights, requirements, two isolated interpreter scaffolds
  and the concrete disk shortfall for combined setups. No model inference.
- D: [frozen discovery corpus](tts-research-corpus-20261125.json) contains
  predetermined A cases/policies and manual three-mode documents variants
  for seeds64/2027/2029. It is not an end-to-end frontend result or held-out set.
  Exact corpus SHA-256:
  `782a85496c55c547988b4527c21a0ae473483bf8c7e89df404f071f4852a3948`.
- E: [separate integration decision](native-engine51-integration-decision-20261125.md)
  reuses prior checks and identifies the exact N=2/3 whole-model evidence gap.
  No merge, pin update or duplicate smoke was performed.

No model output or listening gate was claimed from these preparation checks.
The later 200-output run is documented separately above; it does not turn
preparation or output integrity into semantic acceptance.

Local reproduction tools are
`.tmp/pr-metadata/eos-control-20261125/build-probe.ps1` (SHA-256
`b284fbd5e6893ef1cbed404f39188146ba4ff2368712b59a5d05fd45a6ef9e65`)
and its `build-clean-3a896743.log`. The final static probe is
`.build/eos-control-engine/eos-research-probe.exe`, SHA-256
`bc6da9a2b11a58f9ed26c138e61545e98c03662b06e7420231da5961dea7a434`,
advertising `3a89674 (2026-11-25)`. Existing exact GGML dependencies are reused,
not recopied or rebuilt. The ignored tools/log/binary are machine-local, not
transferred by Git; tracked engine source/tests and the policy document own
the portable implementation. No model was loaded by `--self-test`.

Focused GCC reproduction from the engine worktree:

```powershell
g++ -std=c++17 -O2 -Wall -Wextra -Werror -Wno-unused-function -pedantic -I src tests/research-eos-control.cpp -o E:/_repoz/qwen3-tts-bridge-cpp/.build/eos-control-contract/research-eos-control.exe
E:/_repoz/qwen3-tts-bridge-cpp/.build/eos-control-contract/research-eos-control.exe
```

Preparation handoff: all47 indexed canonical receipts validate; receipt
regressions pass17 with one optional JSON-Schema dependency skip. Frozen corpus
dimensions, distinct A IDs and U+0301 mode boundaries pass model-free checks.
No prior receipt/status was promoted, no new speech verdict was created, and
all tracked local diffs pass whitespace checks. Published-head CI is a separate
external check, not assumed from this preparation.

The final comparison will contain quality/voice/stress/EOS, cold/warm and
first-usable-speech latency, RTF, VRAM/disk and streaming granularity. Missing
measurements remain explicitly not run; no synthetic cross-model ranking.

## Findings added by the first A/D execution

**Confirmed mechanics, not confirmed speech recovery:** raw penalties 2/4/6
produce exactly the intended EOS subtraction at the first eligible decision
in 60 checks; 18 exact historical controls and 40 observer/repeat comparisons
retain full codes and PCM. One-shot intervention is per request, uses the
same draw/subsequence and fires at most once.

**Observed limitation:** «Ладно.» seed 2027 finishes after 2/2/4/4/3 frames in
baseline/penalty 2/4/6/one-shot for both models. In RU-stress its frame 2 final
sampler EOS probability falls from 98.90% to 10.25% under penalty 6, but EOS
returns at frame 4. Therefore a one-time alternative or this constant grid
does not universally remove repeated EOS preference.

**New listening candidates:** the MGU sentence at seed 75 changes from 2 frames
to 86–90 in both models; RU-stress seed 72 changes from 6 to 113 under penalty 6.
Listening update2026-11-26:12–15 (RU-stress seed75, penalties2/4/6 and one-shot)
and17 (CF seed75, penalty2) pronounce normally. CF18 one-shot stops at «проце»
instead of completing «процессор»; RU20 penalty6 seed72 has unclear «МГУ» with
the remainder normal. Detailed voice, other cases and usable-speech onset
remain unassessed. D also retains two-frame failures in both models; no
input-policy winner or training-frequency explanation is established.

**Recommendation:** preserve the limited positive semantic evidence without
promoting CF one-shot or dismissing its missing word ending. Penalty2 is a
next-comparison candidate, not an accepted threshold: seed75 is positive in
both models, whereas short controls still fail or are unqualified. Assess
broader coverage/final words and correct short controls before adaptive tuning,
false-intervention claims or later frozen held-out scoring. Manual accent
contrasts remain unheard. Preserve failures and unchanged full ICL; no blanket
EOS ban, raised minimum or production promotion. No new GPU run is implied.
