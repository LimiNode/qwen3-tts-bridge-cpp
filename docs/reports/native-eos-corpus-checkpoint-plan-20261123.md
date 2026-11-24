# Frozen plan: new-text live recovery and strided KV transfers

- Date: 2026-11-23
- Status: frozen before GPU execution; research only
- Predecessor: [live rollback study](native-eos-live-rollback-20261123.md)
- Production baseline: qwentts `130cb99`, ABI 6; unchanged

## Questions and boundaries

1. Does the existing one-frame live rollback preserve its mechanical invariants
   for new texts/seeds, including legitimate tiny answers?
2. How often does the deliberately naive natural-EOS-at-most-eight-frames policy
   intervene on short-answer inputs? This is intervention incidence, not a
   false-positive rate until the originals are independently judged on listening.
3. Can the same padded KV bytes be copied with one strided backend transfer per
   K/V layer rather than one per attention head, without changing codes or PCM?

Use only CMP 50HX UUID `GPU-40361931-6cb5-ac58-a059-5ba3e70986fb`, unchanged
RU-stress Q8_0 talker, original Q8_0 codec, and Kraftwerk speaker/226-frame
reference/transcript. Preserve their exact hashes in each executable plan.
Frontend, segmentation, prefix reuse, scheduled reseeding and EOS guard stay
off; stochastic Talker/Predictor and the normal 1/2/4/8 codec ramp stay unchanged.
No model algorithm, public ABI, QTB, production pin, package or default change.

This is still a static, single-lane probe with an in-memory irreversible sink,
not integration into the Bridge worker or physical playback qualification.

## Frozen corpus and order

Seeds are **1009, 2003, 3001**, in that order. The one intervention continuation
seed is **64**, selected before seeing results, with no search for a good seed.
The short replies intentionally overlap familiar words; the longer texts are
new stress-test inputs. Do not call this a calibrated held-out detector test.

| Label | Language | Exact spoken text |
| --- | --- | --- |
| ru-yes | russian | Да. |
| ru-no | russian | Нет. |
| ru-thanks | russian | Спасибо. |
| ru-ready | russian | Готово. |
| en-yes | english | Yes. |
| en-no | english | No. |
| en-hi | english | Hi! |
| en-thanks | english | Thank you. |
| ru-short | russian | Я здесь. |
| ru-new | russian | После обеда инженер проверит оборудование и отправит результаты испытаний. |
| ru-two | russian | На улице закончился дождь. Мы открыли окно и продолжили обсуждение нового проекта. |
| en-new | english | The technician checked the equipment and sent a detailed report before lunch. |

After the transfer-equivalence prerequisite, run:

1. 72 baseline groups: repeat-major (two), text-major, seed-major. The second
   complete-code and PCM outputs must match the first for each text/seed pair.
2. 12 unchanged checkpoint-1 replays: text-major, seed 1009. Replay must match
   its own baseline, not a control for another text with the same seed.
3. 36 rollback1 groups: text-major, seed-major. The same <=8-frame policy is
   intentionally exercised on short and long inputs. Do not exempt short
   answers after observing their results or label every intervention a rescue.

Every effective UTF-8 file and language is hashed before execution. Every
original, changed continuation and failure is retained, including short audio.
No semantic verdict is inferred from duration, energy, EOS or finite PCM.

## Transfer change and prerequisite measurement

Replace only research KV head-copy loops with GGML get_2d/set_2d, preserving
offset, packed host stride, tensor pitch, padded rows, head count and precision.
Do not trim masked rows, change attention math, reduce KV precision, reuse an
evictable codec mirror, or add a device-side snapshot implementation here.

The static expected KV transfer call count is 528 to 66 per capture/restore for
this model; codec/bridge copies and allocations are unchanged. This is not an
8x wall-time prediction. Require executable CPU strided-copy/sentinel tests,
including F32/F16, multiple heads and a nonzero view offset, before GPU use.

Run the preceding 41-group live matrix in **A/B/B/A** order: A is the preserved
legacy probe from engine `8ad3171`; B is the newly built strided-copy probe.
Preserve both binary hashes and the distinct runner/source identities. Each
matrix retains the 14 controls, 14 unchanged replays, six negative guards and
seven discovery rollback groups; compare corresponding full codes, PCM,
originals and sink bytes across all four matrices, not only reported booleans.
Do not enter the new corpus if transfer equivalence or a guard fails.

The existing capture_ms measures the sum of captures in a group (for example,
four snapshots for the three-frame failures, nine for healthy controls), not
the latency of one snapshot. Compare equal group workloads and report capture
and restore separately. These diagnostic measurements, including fresh codec
reconstruction, are not streaming TTFA, audible onset or a retry speedup claim.

## Limits, failure handling and evidence

One overall **1800-second** GPU wall-clock budget covers all four matrices and
the corpus, including model loads and process waits. Each logical request keeps
its original 60-second deadline and 256-frame cap; at most one rollback is used.
The currently held PCM cap remains 16 frames. Saved slices, retained diagnostic
output and AR/codec snapshots have separate memory costs and are not hidden by
that cap. Preflight conservative disk requirements plus a 512 MiB reserve.

Run processes sequentially with owned watchdog teardown. A failed prerequisite
stops later GPU stages. Any deadline, interruption or missing groups remain
explicitly failed/not_run; retain flushed evidence and do not silently retry.
The probe fails closed on non-natural or mechanically invalid outcomes.

Check finite PCM, complete 16-codebook histories, original-vs-baseline identity,
full final sink identity, current committed prefix, pending/ramp coherence and
independent fresh streaming-codec reconstruction. Keep one monotonic commit
cursor; never replace already committed samples. The old cancellation,
deadline, stale-snapshot, newer-admission, capacity and sink-refusal guards must
remain effective.

Store new payloads below
`.tmp/base-acceptance/eos-corpus-checkpoint-20261123/`. Do not mutate prior frozen
payloads. Publish a small indexed canonical receipt and report with exact
source, model, binary, corpus, hardware and artifact identities. New listening
starts not_run. Prepare one numbered listening folder with original/candidate
pairs and expected text; include all intervened cases and representative
unchanged short/long controls, with an explicit manifest for any selection.

R1 remains **NO-GO**. Keep research PRs Draft; no merge, tag or release. True
dual-fork, multi-lane, Bridge orchestration and RTX 4090 are outside this batch.
