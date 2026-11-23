# Prospective short-input conditioning and voice comparison

Recorded2026-11-24. Research only; R1 **NO-GO**. Executes the unchanged
[60-group plan](native-short-conditioning-expansion-plan-20261124.md).
Separate scoped receipts:
[RU-stress](native-short-conditioning-expansion-rustress-cmp50hx-20261124.json)
and [Base](native-short-conditioning-expansion-base-cmp50hx-20261124.json).
New human listening is **not_run**; no earlier verdict transfers.

## Result and interpretation boundary

All60 intended independent requests complete with exactly60 AR attempts in
108.875seconds including identity preflight/postflight, under the single
1800-second bound. No actual retry, snapshot/restore, committed PCM, timeout,
missing result, changed identity or repeat disagreement. The buffered
threshold1 path only captures full codes; it never intervenes.

There are48 primary short cases,8 longer voice-comparison cases and4 repeat
controls. Keep these denominators separate. Of the48 short cases,8 meet the
prespecified near-silence diagnostic; all8 belong to RU-stress/full-ICL.
Its repeated ru-ok2027 is also near-silent, making9 quiet outcomes among60
total requests, not9 distinct primary short failures. All9 have PCM16
absolute peak1LSB. These are signal observations, not human semantic verdicts.

Frames below are **seed2027 / seed2029**; Q marks the prespecified diagnostic
RMS<0.0001 AND peak<0.001. One frame is80ms. No minimum-duration acceptance
rule or success rate is inferred.

| Exact short text | RU-stress / ICL | RU-stress / speaker-only | Base / ICL | Base / speaker-only |
| --- | --- | --- | --- | --- |
| Ладно. |2Q /2Q|18 /12|11 /15|15 /11|
| Понятно. |7 /2|10 /12|10 /13|15 /15|
| Завтра. |2Q /2Q|18 /10|14 /15|15 /15|
| Sure. |2Q /2Q|12 /15|15 /15|13 /11|
| Later. |2Q /2|11 /15|9 /7|9 /13|
| All right. |2Q /6|11 /14|9 /10|13 /12|

RU-stress/full-ICL ends within3frames in10/12 primary short cases; removing
ICL changes the histories to10-18frames with no near-silent short case here.
Base/full-ICL gives7-15frames and Base/speaker-only9-15, neither near-silent
in these12-case cells. Absence of the near-silence diagnostic does **not**
prove correct words, absence of laughter/cough or preserved voice identity.
The two nonquiet2-frame results remain suspect, not accepted speech.

The four cells' ru-voice/en-voice controls have99/78,86/82,92/86 and104/84
frames respectively. They have normal numerical signal levels but have not
been listened to. No voice-fidelity conclusion follows from them yet.

This strengthens the observed **checkpoint/conditioning-mode dependency**
beyond the earlier Нет./Hi! seed64 examples. It is not a universal early-EOS
fix or localized root cause. Speaker-only intentionally removes both AR
reference text/codes and decoder-reference availability while retaining the
speaker vector. It is not a single-transformer-layer ablation. Model changes
also change model-dependent context; no matched upstream/native arithmetic
parity is claimed. Neither mode is silently selected for production.

## Exact execution and checks

Bridge pre-run HEAD: `cc3ffc7e9872fc39bb70eab98f64b717a7eaa0ad`.
Engine remains clean at `4e47ed266f08cab9e13e277aa460a33bb607e769`, GGML
`c044c6f03892f9d5e98213b05f8afea1f8b0d3c9`.
Existing static probe SHA256
`8bd699d6f12d31198e004ed82ef67a4d6aa515c6a361a52353e203d682abef5f`;
executed local driver SHA256
`9b2689a648ecd39f3da7552ff4e3271742d812a407164d933fdc837c93e9e03d`.
No engine rebuild. MSVC14.44.35207, CUDA13.3 SM75, driver581.94, CUDA graphs
ON and forceMMQ OFF. Only CMP50HX UUID
`GPU-40361931-6cb5-ac58-a059-5ba3e70986fb` is in scope.

RU-stress/Base/codec and Kraftwerk speaker/reference hashes are in the
canonical receipts. Models, runtime DLLs and original conditioning were
reused in place. Each cell has a separate process, persistent across15
sequential requests; cells are sequential. Native logs name the expected
checkpoint/codec paths and the sole visible CMP50HX; this is not a loaded-
module audit. No RTX4090 or GTX1060 evidence is transferred.

All effective samplers match retained defaults: stochastic Talker/Predictor,
temperature0.9, top_k50, top_p1, original repetition settings, min2.
Frontend, segmentation, prefix reuse, EOS guard and scheduled reseeding
remain OFF. New texts and seeds were fixed before generation, without seed
search or accent/text adjustments. Independent corpus preflight did not find
the exact new inputs/seeds in812 checked local input/plan files or prior
tracked reports; reserved recovery tuning/held-out texts are not borrowed.

The initial plan-only storage block is preserved under `plan-only-001/`.
The user freed space; execution then had sufficient storage for the frozen
991428608-byte worst-case bound including512MiB reserve. Corpus size/order
did not change. No old model, WAV, journal or acceptance evidence was deleted.

Before executing, the local driver was corrected to preserve an explicit
failed result if a postflight observation raises, and to rehash manifests
after execution. Eleven model-free tests pass, including injected postflight
error and storage rejection before GPU launch. The original plan-only driver
is separately preserved; no model computation changed. Its remaining malformed-
JSON attempt-metadata failure path is not fully hardened. Actual native rows
are all valid objects with complete metadata, independently audited below;
do not claim broader corruption-handling coverage from this normal run.

All selected model/codec/probe/runtime/conditioning/source/input/manifest/
runner/actual-reference identities match before/after. Root separately
checks native group/lane/seed and exactly60 one-attempt observations, actual
original/final full-code and PCM bytes, and ru-ok2027 repeat bytes in every
cell. The repeat gate covers only that one input/seed, not the entire matrix.
All120 original/final raw/WAV pairs,4792320 source samples, match PCM16
rounding/clamping exactly, mono24kHz; no normalization/trimming or signal
loss in conversion. Duplicate original/final files are not extra AR attempts.
All33 canonical receipts validate;17 validator regression tests pass with
one optional skip. Both new receipts also pass local artifact hash/size
checks. No new engine build/CTest run is claimed for this source-free reuse.

Payload root:
`.tmp/base-acceptance/short-conditioning-expansion-cmp50hx-20261124/run-001/`.
All427 finalized files excluding the inventory itself are hash-inventoried,
35674892bytes. The probe, exact executed driver, imported local helper sources
and finalizer are preserved under `evidence-tools/`; tracked engine helpers
are pinned by engine HEAD. All136 previously inventoried conditioning files
remain unchanged. Ignored payloads are not transferred or backed up by Git.

## One listening folder

`run-001/listening-conditioning-voice/` contains17 unchanged WAVs. The exact
source/copy identities are in `selection-manifest.json`; README has every
expected text.00 is the actual17.6-second Kraftwerk reference,844844bytes,
SHA256 `90e5f7576991ea5b9f0a85e9109f7bd31ff667c4a12d58783a06c650796c3ca1`.
Its registry and historical migration report establish provenance; no new
embedding extraction or synthetic reference reconstruction was performed.

Within **each quartet**, the order is RU-stress/full-ICL, RU-stress/speaker-
only, Base/full-ICL, Base/speaker-only:

| Files | Expected text / purpose |
| --- | --- |
|00|Original Kraftwerk reference, not new synthesized output|
|01-04|Сегодня мы проверили оборудование и записали результаты. Теперь можно спокойно завершить работу.|
|05-08|The equipment passed every check this morning. We can now finish the report and close the workshop.|
|09-12|Ладно. (seed2027)|
|13-16|All right. (seed2029)|

09 is a deliberately retained near-silent original control (0.16s, peak1LSB),
not a missing/incorrect listening copy. Other suspect outcomes are retained
in the full matrix and named by `matrix-summary.json`; the first16 new files
do not substitute for assessing all48 short cases.

Assess **complete intended text**, **unwanted sounds** and **similarity to
reference voice00** separately. English accent/intonation is a separate
question from speaker identity, and full-ICL is not assumed to be flawless.
New files remain not_run until direct user observation. Earlier positive
Base/RU-stress words and earlier failed full-ICL words keep their own receipts.

No production defaults/pins/models/ABI/QTB/frozen package change, automatic
ICL fallback, merge, tag or release. This buffered corpus is not a first-PCM
latency, physical-playback, production recovery or release-acceptance test.
