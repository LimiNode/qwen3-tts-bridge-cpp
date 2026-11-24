# Prospective short-input conditioning and voice comparison

Prespecified 2026-11-24, following the scoped positive listening in the
[seed64 conditioning study](native-short-conditioning-20261123.md).
Research only; R1 remains NO-GO. This stage changes no engine source,
sampler/default, model, Bridge pin, QTB, ABI or release package.

## Question and fixed corpus

Does the observed checkpoint/conditioning dependency extend to different
short inputs and seeds, and does speaker-only retain the reference voice?
Completeness, unwanted sounds and voice similarity are separate listening
questions. Removing ICL changes both AR conditioning and decoder reference
availability; this is not a pure transformer ablation or a root-cause proof.

Use exactly the following raw UTF-8 texts without trailing newline, frontend,
accent insertion, segmentation, prefix reuse, EOS gate or reseeding. The local
frozen specification owns the byte hashes. New seeds are **2027 and 2029**;
do not search for successful seeds or adapt the corpus after hearing results.

| ID | Language | Exact text |
| --- | --- | --- |
| ru-ok | russian | Ладно. |
| ru-understood | russian | Понятно. |
| ru-tomorrow | russian | Завтра. |
| en-sure | english | Sure. |
| en-later | english | Later. |
| en-all-right | english | All right. |
| ru-voice | russian | Сегодня мы проверили оборудование и записали результаты. Теперь можно спокойно завершить работу. |
| en-voice | english | The equipment passed every check this morning. We can now finish the report and close the workshop. |

Keep preceding Нет./Hi!/MGU discovery examples out of the new denominator.
Do not borrow the separately reserved tuning/held-out corpus from the
[recovery plan](native-eos-recovery-plan-20261122.md). This small prospective
conditioning comparison does not qualify a detector or fallback policy.

## Balanced schedule and resource boundary

Four cells, in order: RU-stress/full-ICL, RU-stress/speaker-only,
Base/full-ICL, Base/speaker-only. Each cell uses a separate loaded engine;
requests within it share the engine, with no parallel inference.

Each cell has fifteen groups: ru-voice/2027; the six short IDs above in table
order at2027, then the same six at2029; en-voice/2027; ru-ok/2027 again.
Thus48 primary short cases,8 longer voice comparisons and4 repeat controls:
**60 independent intended AR attempts**, not120 successes. Both ICL modes
get identical text, seed and speaker vector. Each model has its own receipt.

Reuse clean engine `4e47ed266f08cab9e13e277aa460a33bb607e769` and static
probe SHA256 `8bd699d6f12d31198e004ed82ef67a4d6aa515c6a361a52353e203d682abef5f`.
Model/codec/conditioning hashes remain those in the preceding plan.
Full ICL uses the unchanged226-frame Kraftwerk reference; speaker-only
retains its speaker vector but omits reference codes/transcript.

Use the existing buffered full-retry probe path only to capture complete
16-code histories: threshold1, continuation seed equal to original seed.
Require NOT-triggered, one attempt/prefill, zero snapshot/restore, identical
original/final codes and PCM. An unexpected fallback invalidates that cell;
retain/count every attempt and do not report a rescue. Maximum physical
attempts on this failure path are120. Stop later cells on a mechanical gate
failure, but not merely because a valid natural-EOS result is quiet/short.

Only CMP50HX UUID `GPU-40361931-6cb5-ac58-a059-5ba3e70986fb` is in scope.
One1800-second wall deadline starts before identity preflight; each request
has one60000ms deadline and256-frame cap, each process a watchdog bounded
by the remaining shared deadline. Kill/reap owned children on interruption.
Require worst-case output storage plus the existing512MiB safety reserve
before GPU launch. No model/DLL copies or deletion of old evidence.

## Mechanical and listening gates

Hash selected models, codec, probe, runtime DLLs, speaker/reference tensors,
text/spec/runner and clean source before/after. Capture exact manifests,
environment, all natural-EOS decisions, effective samplers,16-code histories,
f32PCM and unmodified PCM16 WAVs, including failed/quiet results. Require
byte-exact repeat codes/PCM within each cell and unchanged retained defaults.
Audit finite correctly sized PCM and every f32-to-WAV conversion sample.
Report missing/failed/not_run groups and actual attempts separately.
The repeat gate covers only ru-ok/2027, not repeatability of every new case.

Near-silence is the existing diagnostic RMS<0.0001 AND peak<0.001, not a
semantic detector. Do not equate natural EOS, duration, energy or mechanical
success with spoken words. Do not trim/normalize or select only long WAVs.

The actual reference is
`.tmp/base-acceptance/native-r1-aa2770ec-20261120/voice/reference.wav`,
844844bytes, SHA256
`90e5f7576991ea5b9f0a85e9109f7bd31ff667c4a12d58783a06c650796c3ca1`.
Its adjacent registry identifies the Kraftwerk profile/transcript; the same
WAV hash is retained in the historical evidence-migration report. Preserve
its bytes, do not reconstruct a reference from synthesized speech.

Prepare one listening folder: the exact reference plus ru-voice/en-voice
ICL/speaker-only pairs for each model (8 new WAVs), one ru-ok/2027 pair
per model (4), and one en-all-right/2029 pair per model (4). At most17 WAVs
initially; all other short cases and all suspect outcomes remain in the full
matrix with signal diagnostics for a later, explicitly scoped assessment.
Record exact expected text, mode, seed and hashes. New listening starts
not_run; prior verdicts do not transfer. Ask separately about full text,
unwanted sounds and voice similarity relative to the actual reference.
No automatic voice-fidelity score or semantic pass is inferred.
Assess English accent/intonation separately from similarity to the Russian
reference voice; full-ICL is a comparator, not an assumed flawless standard.

Store payloads only in
`.tmp/base-acceptance/short-conditioning-expansion-cmp50hx-20261124/`.
Keep plan-only and execution attempts in exclusive child directories so a
preflight result is never overwritten by a subsequent real run.
Publish separate small tracked Base/RU-stress receipts and update the index
and status after execution, even if incomplete. A storage-preflight block
means not_run, not a failed synthesis or completed quality study. Draft PR332
remains Draft; no merge, tag, release or production mode promotion.
