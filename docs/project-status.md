# Project status and verified architecture

This document is the short, evidence-backed status summary for
`qwen3-tts-bridge-cpp`. It records what has actually been built and exercised,
while keeping experimental paths separate from the production baseline.

## R1 backend direction

R1 evaluates two local backend routes behind the same bridge contract:

```text
QwenTtsClient -> QTB stdin/stdout -> selected persistent worker -> PCM
```

The Python/Faster worker and the native qwentts.cpp/GGUF worker both keep the
model loaded between requests, expose the async C++ API, stream PCM, and use
the same request lifecycle. Native Base Q8_0 is the priority R1 candidate for
local inference; Python/Faster remains a maintained alternative and the route
for model families not yet covered by native. Backend selection is conditional
on the dual-GPU, clean-package, quality and listening gates below.

## R1 release state

The release-preparation baseline is `8b19399cb84eb81556f84f2542bfae337c41b46f`
and the repository version is `0.2.0`. No GitHub Release has been published;
the existing `frequency-r10-rtx4090-48gb-internal-rc1/rc2` tags are internal
experiment tags, not R1 releases. A final release candidate is not frozen.
The baseline is suitable for release preparation, not yet a public
support claim: clean portable-package acceptance, independent hardware
evidence, and the declared human-listening scope remain gates.

Keep these evidence layers separate:

1. implementation and automated CI verification;
2. real-model hardware receipts for an exact machine/runtime/model;
3. human-listening observations for the named artifacts;
4. the narrower public release scope recorded in
   [`beta-release-scope.md`](beta-release-scope.md).

An implemented route or a mock/CI pass does not promote a model family,
backend, GPU, or package to supported status. CMP 50HX receipts remain scoped
historical/current evidence for their exact candidates; RTX 4090 remains
unassessed until an independent run is recorded.

### Current model acceptance records

The tracked [acceptance index](reports/acceptance-index.json) is the source of
current model and listening status. The two frozen CMP 50HX records currently
have mechanical synthesis and natural-EOS evidence plus scoped human listening:

* [Base portable 1.7B](reports/base-portable-cmp50hx-20261030.json) — two WAVs
  were listened to by the user; the subjective result was good, while the
  receipt leaves unassessed artefact and sequential-isolation criteria open.
* [VoiceDesign frozen 1.7B](reports/voice-design-frozen-cmp50hx-20261028.json)
  — the user confirmed clear speech, a good voice, and a normal final tail;
  instruction adherence and broader quality criteria remain conditional.

These are scoped `partial_pass` listening verdicts, not a universal release
acceptance. The exact payloads remain local under `.tmp/base-acceptance/` and
are identified in the tracked receipts by SHA-256.

Separately, the [native EOS-switch research receipt](reports/native-eos-switch-listening-cmp50hx-20261120.json)
records user-confirmed full text in eight standalone CMP WAVs (four unique
seed/policy cases with repeats). This is scoped listening evidence only;
the research policies, shared-prefix batch and R1 release remain unqualified.
The separate [prefix listening receipt](reports/native-eos-prefix-listening-cmp50hx-20261120.json)
confirms full text in three named single/dual continuations, with user-reported
gradual end-volume fading on batch seed 65. It does not qualify general audio
quality, live branch switching or release readiness.
The [offline seed-65 diagnostic](reports/native-eos-fade-comparison-20261120.md)
finds a similar quieter ending in single and batch, not a WAV-conversion fade;
the cause was not isolated. In the
[2026-11-21 follow-up](reports/native-eos-seed65-listening-cmp50hx-20261121.json),
the user found slight or effectively absent fading in single seed 65 and no
noticeable difference from the earlier track. This informal feedback does not
establish an actionable fade defect or qualify general audio quality.

The [2026-11-21 CMP corpus/timing research](reports/native-eos-corpus-and-decision-20261121.md)
adds 142 direct-engine baseline outcomes each for RU-stress and Base, plus
36 timing controls. All have valid PCM and natural EOS; RU-stress has three
non-short duration anomalies (seeds 72/75/78), versus none among Base's 64
eligible corpus cases. In the subsequent
[19-file listening](reports/native-eos-corpus-listening-20261121.json), the user
recognizes normal text in eleven files, is uncertain about one, and reports seven
as unrecognizable, inaudible or meaningless. The file-specific follow-up
confirms Base file18's full normal phrase, superseding its initial inferred
failure and the duration-proxy-miss interpretation; Base file14 remains a
failed short answer. The saved-PCM audit finds no copy/conversion
corruption: files03/04 are near silence; files14/18 have substantial signal,
which does not establish intelligible text. All other cases and voice-quality
criteria remain unassessed. Both canonical research receipts record failed
scoped listening. The observer preserves output on ten ON/OFF pairs, but frame-3 continuation does
not detect seed 72's later early EOS; measured warm N=2 pair decisions also
miss the first-chunk budget. Canonical research receipts are in the index.
No engine pin, sampler/default, live selector or release gate is promoted.

The separate [native prefill study](reports/native-prefill-study-20261121.md)
records 504 primary and 105 traced CMP outcomes, isolated graph/head/KV/window
controls, same-checkpoint ICL cost, matched-weight speech.cpp comparison,
and split/full-source prefix-KV tests. Small variants preserve the observed
sampled outputs; prefix reuse reduces latency but changes audio, so it is not
an equivalent optimization or EOS remedy. The user subsequently listened to
all 13 named WAVs: RU-stress/Base ICL baseline and prefix samples01-06 have
full text, correct stress and no cough, with acceptable delivery differences;
both identical CustomVoice prefix `Да!` samples contain extraneous
coughing/throat-clearing before the recognized word. Speaker-only RU-stress
has wrong `процессОр`, while Base has correct `процЕссор`. Native CustomVoice
file10 also has correct `процЕссор`; speech.cpp file11 has wrong `процессОр`.
Four indexed canonical receipts preserve this exact scoped feedback;
detailed voice matching, instruction adherence and broader quality remain
unassessed. The report's research summary is not release acceptance;
R1 gates, engine pin, ABI and sampler defaults remain unchanged.

The [prefill differential follow-up](reports/native-prefill-differential-20261121.md)
adds208 bounded outcomes and a separate12-request natural-EOS control. KV
restores are exact; drift begins before attention. A traced MMQ/MMVQ shape
switch materially changes short CustomVoice output; consistent MMQ restores
full PCM equality for the one tested short seed64 case. The user listened to
the three exact short WAVs: baseline01 and MMQ03 say `Да` without coughing;
ordinary-prefix02 says `КхмКхм Да`. Separate indexed receipts retain the failed
ordinary-prefix case and partial positive MMQ/baseline scope. Broader
seed/text/latency checks are extended in the
[short-utterance follow-up](reports/native-prefill-short-20261121.md);
the user has now assessed all18 selected WAVs. Baseline, ordinary-prefix and
MMQ-prefix each have a new indexed failed scoped listening receipt. Several
Russian MMQ failures are byte-identical to baseline; English `Hi!` seed64 adds
laughter under MMQ relative to its baseline. Target words are recognized in16
selected files;04 is distorted and18 remains text-uncertain. The other90 matrix
outputs and broader voice identity remain unassessed. The measured warm
CustomVoice first-PCM median60.896 to51.603ms is not a quality/EOS rescue.
No default is promoted; earlier scoped positive and failed receipts are preserved.

The [short-answer causal study](reports/native-short-quality-causal-20261121.md)
adds122 traced controls and54 independent sampler requests. All14 fresh-process
controls reproduce the earlier primed baseline; the selected defects do not
require preceding requests. Full-frame tracing preserves90 original-schedule
outputs, while MMQ without prefix preserves18/18 English baseline outputs.
For `Hi!` seed64, prefix-MMQ first changes acoustic `c1` in frame1 despite the
same first two Talker codes; the exact originating hidden operation remains
unlocalized. Talker top-1 and predictor greedy each reach natural EOS on the
14 selected short outcomes, but no new audio quality verdict follows from that.
All21 repeat pairs match. The user has now listened to all21 selected WAVs:
baseline and predictor greedy fail; Talker top-1 has scoped `partial_pass`
with no reported laughter/cough/extra speech, but `Hi!` seed64 sounds like
`Хау` and remains a pronunciation concern. Sad affect and slightly syllabic
`Готово` are recorded without inventing an instruction-adherence failure.
Separate indexed receipts preserve each candidate's scope; the mixed receipt
keeps six failed max-token controls, failed listening and release `blocked`.
Held-out coverage, broader voice criteria and prefix-plus-top-1 interaction
remain unqualified. No new latency claim, Base/Kraftwerk verdict, EOS policy
change or production promotion is made.

The [2026-11-22 comparative recovery preflight](reports/native-eos-recovery-preflight-20261122.md)
closes the331stderr-test race (exact-HEAD CI8/8) and extracts the isolated
N>1Predictor sampler corrective as engine Draft51 (CI2/2). The
[frozen recovery plan](reports/native-eos-recovery-plan-20261122.md) prioritizes
unchanged checkpoint replay, rollback1/2, then a genuine one-prefill fork;
top-k quality qualification stays separate. A buffered/uncommitted research
checkpoint tool compiles and passes19model-free CTests. Its earlier disk
refusal remains historical. After user cleanup, the
[executed CMP matrix](reports/native-eos-recovery-mechanics-20261122.md)
passes14retained streaming controls,21byte-exact buffered replay pairs and
21mechanically valid recovery groups. On the five known early terminals,
rollback1 lengthens5/5, rollback2 lengthens4/5 and EOS resampling lengthens2/5;
the user subsequently listened to all17 blinded WAVs. The
[per-file observations](reports/native-eos-recovery-listening-20261122.json)
record5/5 contextual OK for rollback1,4/5 for rollback2 and2/5 for EOS resample.
Separate indexed receipts preserve rollback1 scoped `partial_pass` and the
other candidates' failures; voice/stress and broader quality remain unassessed.
The [indexed receipt](reports/native-eos-recovery-cmp50hx-20261122.json)
retains mixed listening fail, zero committed PCM and no streaming qualification. Buffered codec
output changes even inside retained code prefixes; synchronous snapshot cost
is166–515ms, so neither seamless streaming nor cheap recovery is established.
That first matrix did not exercise standalone retry. The subsequent
[retry/codec comparison](reports/native-eos-retry-codec-20261122.md), with two
new indexed receipts, passes14controls/21replays/28comparison groups and31
teacher-forced one-lane codec-state checks. All10 full retries exactly match
fresh buffered64; repeated rollback1 outputs match earlier bytes. Streaming
restoration/reconstruction preserves complete PCM/state, including changed
continuation versus independent fresh decoding and the retained PCM prefix.
All14 production-ramp originals match retained streaming bytes. The normal
1then2frame ramp still requires a real chunk-boundary holdback; these tests
are not an AR+codec live commit-buffer. The user subsequently listened to all
seven exact WAVs: full text, no laughter/cough and normal delivery. The
[per-file record](reports/native-eos-retry-codec-listening-20261122.json)
separates one unique buffered full retry, five restored codec candidates and
one healthy64 control. Both canonical receipts now retain scoped `partial_pass`,
not aggregate acceptance. File03's longer USB/port pause is acceptable variation;
fast MGU is a nonblocking future abbreviation-adaptation observation, with no
text/frontend change. Voice identity, other artifact classes and broader quality
remain unassessed.
Current diagnostic host snapshots cost more than retry's second prefill;
different output lengths and buffered spans preclude a streaming speedup claim.
The subsequent [live rollback study](reports/native-eos-live-rollback-20261123.md)
and [indexed receipt](reports/native-eos-live-rollback-cmp50hx-20261123.json)
pass14retained controls,14unchanged live replays,6negative guards and7rollback1
groups on CMP50HX. Coherent single-lane AR+codec checkpoints restore pending
rows/ramp and an independently owned codec mirror; a bounded owned PCM holdback
preserves the irreversible in-memory sink. Four known early-EOS recoveries
retain1920committed samples, the fifth has zero commit; healthy42/64 are unchanged.
All positive sink bytes equal full PCM and independent fresh streaming-codec
reconstruction. All five candidate PCM/WAVs also match the preceding codec-only
outputs byte-for-byte; earlier positive listening remains scoped to its original
receipt. Direct user listening on2026-11-23 additionally confirms subjective OK
for healthy01 and five live rollback candidates03-07; the user explicitly
confirms problems in original control02. The indexed receipt records scoped
partial_pass, not detailed quality or release acceptance. This is actual live rollback mechanics
in an opt-in static probe, not Bridge worker integration, physical playback,
multi-lane, a detector or a latency improvement. Synchronous diagnostic capture
remains expensive. True fork, live selector, held-out quality and release gates
remain unverified.
The subsequent [new-corpus/checkpoint study](reports/native-eos-corpus-checkpoint-20261123.md)
and [indexed receipt](reports/native-eos-corpus-checkpoint-cmp50hx-20261123.json)
add 284 passing mechanical groups in 831.159 s on CMP 50HX: four 41-group A/B/B/A
matrices and 120 new-corpus groups. Pitched KV copies preserve complete codes,
PCM, sink/prefix and replay evidence; paired recovery capture cost falls 17.37%
at unchanged snapshot bytes/memory. This is checkpoint cost, not prefill/TTFA.
All 36 new text/seed controls repeat exactly and 12 unchanged replays pass.
The naive natural-EOS<=8 policy intervenes in 23/27 short-input cells and 0/9
longer-input cells; it establishes neither 23 rescues nor false-positive rates.
The user subsequently reports usually inaudible audio in both members of
pairs01-46. The indexed receipt now records failed scoped intelligibility,
without assigning46 per-file failures; controls47-50 remain unassessed.
Direct PCM16 analysis confirms30/46 files have absolute peak<=1 integer unit,
including12 complete original/candidate pairs. This is not successful speech
recovery despite passing mechanics. Earlier positive and failed verdicts
remain scoped to their original artifacts. Production orchestration,
detector quality, physical playback, RTX4090 and release gates remain open.
The subsequent [short-input reset controls](reports/native-eos-short-reset-20261123.md)
and [receipt](reports/native-eos-short-reset-cmp50hx-20261123.json) complete10
logical groups/14 AR attempts in41.172seconds on CMP50HX. Full retry1009-to64
matches independently admitted64 in complete codes and matched buffered PCM,
twice for each of Нет./Hi!; no retry-reset defect is reproduced. Both long64
streaming controls match retained84frames/PCM. Original1009 is nearly silent;
fresh/retry64 has more signal but only2/3frames. Direct user listening now
fails both exact short selections:01 has no audible intended word,02 has a
strange sound rather than Hi!;03 long control remains unassessed. Full retry
is not a remedy for these two inputs despite correct reset mechanics.
Cross-decoder PCM differences are not reset failures. No latency gain or
release acceptance is claimed.
The subsequent [checkpoint/conditioning comparison](reports/native-short-conditioning-20261123.md)
adds15 independent buffered64 groups in62.437seconds, with separate
[RU-stress](reports/native-short-conditioning-rustress-cmp50hx-20261123.json)
and [Base](reports/native-short-conditioning-base-cmp50hx-20261123.json)
receipts. All six new short repeat pairs preserve complete codes/PCM and
all effective samplers match the retained defaults; no fallback triggers.
RU-stress/speaker-only emits13/14frames for Нет./Hi!, Base/full-ICL11/8 and
Base/speaker-only8/11; long same-mode controls86/103/84. Direct user listening
now confirms Нет. in01-03, recognizable Hi! in04-06, and the full phrase
without laughter/cough/extra sounds in07-09. Separate model receipts record
scoped partial_pass, not complete quality/release acceptance.04's rising
intonation remains acceptable; occasional процессор stress on O among07-09
is a nonblocking pronunciation note with no file attribution. Prior failed
RU-stress/full-ICL short files remain failed. ICL removal also removes decoder
reference availability, so this is scoped mode dependency, not a transformer
root cause or universal EOS remedy. Models/defaults remain unchanged;
all failures and repeats are retained.
The [prospective expansion plan](reports/native-short-conditioning-expansion-plan-20261124.md)
now has a [completed CMP50HX execution](reports/native-short-conditioning-expansion-20261124.md),
with separate [RU-stress](reports/native-short-conditioning-expansion-rustress-cmp50hx-20261124.json)
and [Base](reports/native-short-conditioning-expansion-base-cmp50hx-20261124.json)
receipts. Exactly60 independent requests/attempts complete in108.875seconds:
48 primary short cases at new seeds2027/2029,8 longer voice comparisons and
4 ru-ok2027 repeats. All mechanics/repeat bytes/identities pass with no actual
retry; all120 raw/WAV pairs and4792320 conversion samples match. RU-stress/
full-ICL has8/12 near-silent primary shorts (plus its repeated control),10/12
end within3frames; RU-stress/speaker-only and both Base modes have no near-
silent primary shorts here. These are numerical findings, not speech-success
rates or a universal EOS remedy. ICL changes both AR and decoder conditioning.
Direct user listening to the16 selected outputs now records RU-stress fail:
06 speaker-only English changes voice around mid-phrase,09 ICL Ладно. is
empty,13 ICL All right. seems to contain only 'all' (tentative). Positive
01/02/05/10/14 observations remain scoped. Base records partial_pass:
all eight selected files contain the intended words;03/04/07/08/15/16 also
have approximately reference-like maintained voice, with inter-track
variation.11/12 explicitly confirm Ладно.; no separate precise voice verdict
is invented. Other quality criteria/unselected cases remain unassessed;
aggregate Base listening is not_assessed. Source/copy identities are unchanged
and each listened WAV is identified in its model receipt. ICL removal is
not a generally qualified RU-stress fallback given06's voice drift.
The initial storage block is preserved; execution followed user cleanup
without changing the frozen corpus or deleting earlier evidence. No further
GPU run, production fallback or model/mode promotion follows this feedback.
The subsequently authorized [exact state checks](reports/native-icl-state-repro-20261124.md)
complete five fresh requests in61.0seconds including identity checks, with
separate [RU-stress](reports/native-icl-state-repro-rustress-cmp50hx-20261124.json)
and [Base](reports/native-icl-state-repro-base-cmp50hx-20261124.json) receipts.
Every complete16-code history, matched buffered PCM, sampled decision and
EOS matches the retained persistent output: RU-stress/full-ICL Ладно./2027
and All right./2029 remain2/6frames, Base/full-ICL11/10frames, and RU-stress
speaker-only English voice82frames. The conditional full queues are not_needed,
not executed. Preceding requests are not necessary for these exact failures;
no broader absence of state defects or successful remedy is established.
All10 raw/WAV conversions are exact; no new listening verdict is inferred.
Preparation audit finds unchanged correctly transferred226-frame reference,
2048-value speaker vector and nonempty registry transcript; no confirmed
preparation defect. Static tokenizer/prompt/mask agreement is not forward or
extraction parity. Full-ICL remains the target. An important remaining
confounder is text geometry: native ICL is aligned/streaming-text, whereas
speaker-only is full-text. Upstream also provides a full-text ICL branch;
testing that branch while retaining full reference/decoder conditioning is
the next bounded candidate, not an implemented fix or default change.
The user subsequently confirms the exact Kraftwerk reference's spoken text
matches its registry/ICL transcript; both state-check receipts now record the
reference-only observation and exact WAV identity. Generated-output listening,
extraction parity, EOS failures and release status are unchanged; no new GPU
run follows this confirmation.
Production defaults/pins are unchanged; all research PRs
remain Draft and R1 stays NO-GO.

## Verified milestones

### Native qwentts.cpp runtime and DLL

The repository contains a working native candidate based on the pinned
`LimiNode/qwentts.cpp` fork. The native build enables `QWEN_SHARED=ON`, produces
the shared `qwen.dll`, and the bridge ABI adapter and native worker can load the
split talker/codec runtime and stream PCM on the validated CMP 50HX setup.
The canonical acceptance receipt records qwentts revision `130cb99`, ABI 6,
CUDA graphs enabled, and the exact worker/talker/codec hashes used for the run.

This is a real build and runtime milestone, not a claim that native has already
been promoted. Native Base is evaluated first for R1, while the native worker
and the in-process DLL adapter remain separate acceptance surfaces until the
documented quality, cancellation, lifecycle, packaging, and target-hardware
promotion gates are closed. See
[`native-qwentts-backend.md`](native-qwentts-backend.md),
[`native-qwentts-worker.md`](native-qwentts-worker.md), and the boundary ADR
[`architecture/adr-native-engine-boundaries.md`](architecture/adr-native-engine-boundaries.md).

### Russian stress model and explicit accents

The experimental `ru-stress` talker/codec pair was converted for the native
split runtime and exercised with the registered
`kraftwerk_robot_ru_warm` voice profile. The model follows the source model's
explicit combining-accent contract: U+0301 is rendered only when the selected
profile advertises `explicit_combining_stress`.

The canonical CMP 50HX acceptance receipt records:

* 12 Russian utterances, including homographs, numbers, abbreviations, plain
  text, and a long operational sentence;
* non-empty PCM, natural EOS, and no starvation in all 12 cases;
* a human-listening pass: intelligible Russian, intended explicit stresses, and
  preserved warm Kraftwerk voice identity;
* fixed provenance for qwentts revision/ABI, GPU, voice, seed, and talker and
  codec hashes.

Primary evidence:

* [`russian-stress-cmp50hx-acceptance-2026-10-07.json`](reports/russian-stress-cmp50hx-acceptance-2026-10-07.json)
* [`russian-stress-kraftwerk-profile-ab.json`](reports/russian-stress-kraftwerk-profile-ab.json)
* [`russian-stress-model-compatibility.md`](russian-stress-model-compatibility.md)
* [`russian-stress-oracle-parity.json`](reports/russian-stress-oracle-parity.json)

The result remains **experimental**, and the upstream stress repository is not
treated as directly compatible with the native split loader without the
documented conversion. The R1 native example/package configuration now names
`ru-stress` as the intended default, but that product default is conditional
on the remaining listening, dual-GPU, and release-package acceptance gates.

### Text preparation and playback/animation plumbing

`tts-front-cpp` is integrated as a model-neutral preparation boundary. The
submodule is pinned to focused upstream corrective commit
`64f73182d26de60af6c082724b1b199eb7310620`, based on the published v0.2.5
line and not a published v0.2.6 release:

```text
raw text -> TextFrontend -> PreparedText -> QwenTtsClient
```

`PreparedText` carries normalized text, pronunciation evidence, semantic stress
decisions, warnings, and uncertainty. The Qwen adapter renders U+0301 only for
an explicitly compatible stress capability. The native launcher derives that
capability from selected profile metadata; the low-level bridge does not guess
from a filename or profile name.
The historical v0.2.5 baseline remains
`d1b6a6e18e7f51f8c51fff548bb84f10e749004a` (tag `v0.2.5`). The bridge-level
comparison against v0.2.2 is recorded in
[`tts-front-v022-v025-effective-text.md`](reports/tts-front-v022-v025-effective-text.md);
three intended effective-text changes and one diagnostic-only change were
found, with 13 unchanged cases and no regression in the 17-case corpus. Targeted listening for the
three changed text surfaces remains outside this dependency-only checkout.

The bridge also has a verified optional speech-animation adapter. It forwards
playback PCM first, maps the canonical sample clock to animation-neutral timing,
and isolates animation queue/analyzer failures from TTS lifecycle. The archived
real-Qwen CMP 50HX receipt demonstrates contiguous PCM and animation ranges,
terminal fade anchored at the real PCM end, zero queue overflow, and a measurable
`mouth_open` signal. This proves the audio-reactive v0 data path, not complete
avatar or lip-sync presentation.

See [`tts-front-integration.md`](tts-front-integration.md),
[`speech-animation-integration.md`](speech-animation-integration.md), and the
[real-Qwen speech-animation receipt](reports/speech-animation-qwen-e2e-cmp50hx-20261009/README.md).

## Current architecture

```text
Application
    |
    +--> optional tts-front-cpp corrective 64f73182 (v0.2.5 line)
    |        |
    |        v
    |     PreparedText / pronunciation evidence
    |        |
    `------> QwenTtsClient
                 |
                 v
              QTB stdin/stdout
                 |
                 v
            selected worker
              |-- persistent Python -> PyTorch / Qwen runtime --+
              `-- optional native -> qwen.dll -> qwentts.cpp / GGML / CUDA --+
                                                                       v
                                                             PCM + canonical sample clock
                                                                       |             |
                                                                       v             v
                                                             application-owned sink  optional speech-animation adapter
                                                                                   sample-addressed animation timeline
                                                                                   physical playback-cursor acceptance pending
```

The dependency direction is deliberate:

* `tts-front-cpp` provides model-neutral preparation; it does not contain Qwen
  runtime logic.
* The bridge owns worker supervision, protocol, request lifecycle, PCM, and
  sample-addressed timing.
* Python and native engines are interchangeable backend routes behind the same
  client boundary.
* Playback and animation are downstream consumers. Animation must not delay,
  rewrite, or turn a successful PCM request into a TTS error.
* `speech-animation` remains generic and optional; avatar presentation adapters
  (VRM, Unity, Godot, and similar) are not claimed complete. The receipt proves
  a sample-addressed animation timeline, not physical playback-cursor
  synchronization.
* `tts-front-cpp` is optional; callers may provide already prepared requests or
  use another pronunciation provider.

## Status boundaries and next gates

| Area | Status | Boundary |
| --- | --- | --- |
| Python/Faster worker | Maintained acceptance route and alternative backend | Complete the same frozen dual-GPU/package/listening matrix |
| Native worker and `qwen.dll` | Priority R1 native route; conditional until accepted | Close promotion gates and record backend selection; in-process adapter is separate |
| RU-stress + Kraftwerk profile | Intended R1 default, still experimental | Expand dual-GPU, long-run, cancellation, packaging, and listening evidence |
| `tts-front-cpp` pinned corrective `64f73182` (based on v0.2.5) | Integrated preparation contract; 17-case oracle (13 unchanged cases) has no regressions | Keep frontend model-neutral; listen to the three changed surfaces before release claims; do not describe the corrective commit as a v0.2.6 release |
| PCM/sample-addressed animation | Audio-reactive v0 baseline validated | Predictive visemes and presentation remain downstream work |
| Avatar presentation | Not yet complete | Add a separate VRM/Unity/Godot adapter after playback-locked cues are stable |

Model weights, DLLs, CUDA runtimes, generated builds, and WAV captures remain
external artifacts. The committed receipts contain provenance and measurements,
not the model data itself.
