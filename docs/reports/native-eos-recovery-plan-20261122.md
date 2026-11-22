# Comparative early-EOS recovery: frozen staged plan

Status: active research plan, frozen before new model execution on 2026-11-22.
This addendum supersedes the priority, not the historical evidence, of the
2026-11-21 short-answer study. Recovery correctness comes before sampler
qualification and further prefix-KV optimization. R1 remains **NO-GO**.

Executed first-stage evidence is now in the
[buffered mechanics report](native-eos-recovery-mechanics-20261122.md) and
[canonical receipt](native-eos-recovery-cmp50hx-20261122.json). This frozen
plan remains the specification for subsequent, still-unqualified stages.

## Boundaries and stop conditions

Use CMP 50HX UUID `GPU-40361931-6cb5-ac58-a059-5ba3e70986fb` only.
One bounded stage has at most 1,800 seconds of GPU work, including controls;
all policies share each logical request's deadline. Retain every attempt and
mark remaining cells `not_run` on budget exhaustion. Do not copy runtime
bundles, download weights or remove earlier evidence to make room. Measure
available disk before launch; reserve space for the worst-case bounded PCM,
logs and manifests plus 512 MiB. A smaller study must declare its own bound;
it must not bypass an older runner's 2-GiB requirement.

Engine/Bridge production pins, ABI, model weights, sampler defaults and the
frozen package remain unchanged. No automatic merge, tag or release. Keep
all four existing research PRs Draft. Correctives are separately reviewed.

## Evidence ladder

1. Reproduce the five known RU-stress early terminals and healthy controls
   with their original prepared inputs. Original text bytes, not a newly
   normalized sentence, own identity. A new diagnostic observer must pass
   unchanged-trajectory controls before it supports a causal claim.
2. Verify a **single-slot, entirely uncommitted** state snapshot and restore.
   Save the Talker KV/write head/hidden bridge, complete host history, RNG
   key/cursor, predictor state and owned prompt/reference data. Reject a
   mismatched engine/job or unsupported mode. Restore without a new prefill.
   Compare every complete 16-code frame and full PCM for the same seed.
   If codec state cannot be restored, redecode the retained complete code
   sequence; explicitly label this buffered stage, not a complete codec fork.
3. Only after exact replay passes, compare current-decision EOS resampling,
   rollback one frame, rollback two frames and full retry. Preserve original
   and candidate codes/PCM, explicit seed, actual boundary and intervention
   cost. A new longer recording is not semantic recovery.
4. Add an actual streaming commit buffer and test that no already committed
   sample changes. Rollback is allowed only inside the uncommitted suffix.
   Check codec prefix identity and boundary continuity, not just c0 identity.
   The buffered mechanics stage provides no TTFA, audible-onset or underrun
   qualification.
5. Implement a genuine one-prefill fork after zero/one/two complete frames;
   independent branch KV, predictor, RNG/history and codec. Two admissions
   with serial prefills and teacher-forced code replay are not this fork.
6. Compare live-only selection/risk signals, then combined policies. Final
   WAV length, future EOS and human labels are never live selector inputs.
   If both candidates fail, use a bounded fallback or explicit failure.

Failure of unchanged-trajectory replay blocks interpretation of intervention
results and promotion to streaming/fork tests. It does not erase failed runs.
Use model-free contract tests and negative cases before the GPU stage.

## Discovery and first mechanics matrix

RU-stress Q8_0 SHA-256
`f4672741608d145fae169075cb0ec775a5382cbe9183eccb59c7ab9cc4797427`;
original Q8_0 codec
`1883beeed99348fc35e23dd225e9082f93f6f8c109330a33d935baa8acdbfd94`.
Kraftwerk prepared speaker/reference/transcript hashes are frozen in
`tests/run_eos_corpus.py::PREPARED_HASHES` in the engine research branch.
Use 226 reference frames and exact unmodified UTF-8 transcript whitespace.
Frontend OFF, segmentation OFF, prefix cache OFF, seed schedule baseline,
Predictor unchanged, EOS guard OFF, original min-new-tokens=2.

Original text:

> МГУ находится в Москве. Инженер проверил USB-порт, GPS и новый процессор.

Discovery seeds: 2/14 (3 frames), 72 (6), 75 (2), 78 (3).
Healthy controls: 42/64. These are known examples, not independent samples.
The initial matrix repeats baseline streaming twice, then unchanged replay
from boundaries 0/1/2 for all seven seeds. A bounded follow-up compares EOS
resample, rollback-1, rollback-2 and full retry with continuation seed 64.
Use the same alternate seed for each method; do not pick a winning seed
after listening. For seed64's healthy control use alternate seed65.
Record buffered-original versus streaming equality separately from replay
equality: codec framing is an explicit variable, not a hidden tolerance.

Keep earlier full-text listening for switch-after:1/2 seeds2/14 intact.
Switch-after:3 failed those controls; rollback before frame3 is a new test,
not an already demonstrated repair. One frame is 80ms, not one callback;
the normal codec chunk ramp is 1 -> 2 -> 4 -> 8 frames.

## Frozen prospective splits (not yet executed)

Discovery includes all previously generated/listened texts and seeds. Never
include them in held-out success-rate denominators. The following exact
texts and seeds are designated before any new audio. The execution manifest
will own UTF-8 byte hashes, order, frontend effective bytes and conditioning.

| Split | Seeds | RU / EN texts |
| --- | --- | --- |
| Tuning | 901,902 | `Верно.` / `Certainly.`; `Не сейчас.` / `Not yet.` |
| Tuning | 901,902 | `На станции проверили датчики температуры и закрыли журнал наблюдений.` / `The station staff checked the temperature sensors and closed the observation log.` |
| Held-out | 1201,1202,1203,1204 | `Можно.` / `Agreed.`; `До завтра!` / `See you tomorrow!` |
| Held-out | 1201,1202,1203,1204 | `Посылку доставят к восьми часам вечера, пожалуйста, проверьте номер квартиры.` / `Please leave the parcel beside the blue door before eight this evening.` |
| Held-out | 1201,1202,1203,1204 | `Техник записал 12,5 вольта и проверил USB-порт. После короткой паузы он отключил питание и завершил осмотр.` / `The technician recorded 12.5 volts and checked the USB port. After a short pause, she switched off the power and completed the inspection.` |

Keep legitimate tiny replies in both splits; no universal minimum-duration
acceptance rule. Start with raw frontend OFF. A separately named frontend
ON/segmentation ON slice must freeze actual prepared text before inference.
Never pool these slices. First voice is exact Kraftwerk conditioning above;
a second verified reference voice is a later, explicitly pinned scope.

Secondary sampling qualification starts with the same CustomVoice Q8_0,
ryan and F16 codec identities from the short-quality study, prefix OFF.
Compare stochastic Talker top-k50/1/2/4, do_sample=true, temperature0.9,
repetition1.05 and unchanged Predictor. Cross fresh first use and persistent
warm execution; test Base and RU-stress independently. No full greedy
substitution and no transfer of CustomVoice findings to Kraftwerk.

## Measurements and review

The final policy comparison includes baseline, retry, EOS resample,
rollback-1/2, shared-prefix dual continuation, risk+rollback,
risk+conditional-dual and separately top1+rollback. Report live information
boundaries, failures, intervention/false-positive rates, sample counts and
confidence intervals. No trained detector is qualified on its tuning data.

Disk-limited preflight smoke, declared before execution: the same five
known short seeds, two streaming repetitions (10groups), then unchanged
replay boundaries0/1/2 (15groups), cap8frames and at most600seconds total.
No alternative seed/policy is evaluated. The cap is a diagnostic variable;
it must not be used to claim full-speech recovery or healthy long replay.
Budget40attempts at the8frame PCM cap,8MiB logs plus512MiB free reserve.
Failure still blocks the full matrix; success qualifies only this smoke.

Measure first PCM, actual audible onset, second/third chunk availability,
p50/p95, RTF, underruns/gaps, extra GPU work, branch/snapshot cost and peak
VRAM separately. Instrumented/buffered spans are not streaming timing.
Human listening and auxiliary ASR distinguish full text, missing/extra words,
unwanted vocalizations, repetition, stress, voice identity and prosody. Use
a small numbered blinded shortlist, preserve all unselected failures, and
leave unlistened audio unassessed.

Publish per-failure causal boundaries, replay correctness, individual and
combined-policy results, exact identities and a minimal engine/Bridge plan.
No algorithm recommendation becomes a default without separate review.

## PR dependency ledger

| PR | Dependency / review scope | Readiness |
| --- | --- | --- |
| Engine49 | master; sampler fix plus reseeding/replay research | research Draft, not a production merge unit |
| Engine50 | Engine49; prefill/profile/quality tooling | research Draft, parent scope must not enter master implicitly |
| Engine51 | actual master130cb99; isolated sampler correction only | independent Draft corrective, exact-HEAD checks required |
| Bridge331 | main; segmentation/EOS research and native-worker tests | Draft; stderr-test corrective and exact-HEAD CI required |
| Bridge332 | Bridge331; prefill/quality reports | Draft; update parent before claiming integrated test fix |

Current measured heads and checks belong in the accompanying results report;
the plan does not present a passing old HEAD as evidence for a new HEAD.
