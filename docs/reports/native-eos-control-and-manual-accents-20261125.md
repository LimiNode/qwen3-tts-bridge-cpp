# Original full-ICL EOS control and manual accent-policy discovery

- Date: 2026-11-25.
- Status: mechanically completed; new listening and semantic recovery unassessed.
- Bridge preparation: `a133c595406fe80b8d5ee0c87be23e3fd6cbca1f`.
- Static research engine: `3a896743ada11cba6bfa7e6fd69c06ec39a10283`,
  [Engine #53](https://github.com/LimiNode/qwentts.cpp/pull/53).
- Canonical receipts: [RU-stress](native-eos-control-rustress-cmp50hx-20261125.json)
  and [RU-Stress-CF](native-eos-control-cf-cmp50hx-20261125.json).
- Payload: `.tmp/base-acceptance/eos-control-cmp50hx-20261125/run-001/`.

## Decision summary

The intervention changes EOS selection as intended, but it is **not a general
early-EOS fix**. One-shot exclusion usually buys one additional frame and then
EOS returns. Some known long failures instead continue for many frames under
one-shot or a constant penalty. Those are listening candidates, not rescued
speech until their exact recordings are assessed. No production policy changes.

The fixed A/D discovery corpus was executed completely: 100 traced A requests,
60 deduplicated manual D requests and 40 separate observer-OFF cost controls.
All 200 terminate naturally, preserve their complete audio codes/PCM, and remain
available, including near-silent and extremely short results. Natural EOS does
not establish complete words. No held-out corpus or adaptive penalty was run.

## Frozen setup and resource window

Only CMP 50HX, UUID `GPU-40361931-6cb5-ac58-a059-5ba3e70986fb`, was used.
The single authorized 1800-second window ran from 14:28:35 to 14:34:11 UTC,
336.766 seconds including coordination, with one model process at a time.
The supervisor sampled device memory approximately once per second: observed
peak 3544 MiB, against the 18432 MiB cap. This is not an allocator-level peak
instrument. Minimum observed free disk was 6,902,841,344 bytes, above 2 GiB.
Final indexed payload is 105,031,140 bytes plus its final inventory, below 1 GiB.
There was no deadline renewal or forced stop; no other GPU experiment followed.

The [frozen corpus](tts-research-corpus-20261125.json) SHA-256 is
`782a85496c55c547988b4527c21a0ae473483bf8c7e89df404f071f4852a3948`.
Its preparation-time status is a historical snapshot, not the current run
status. `plan.json` pins exact manifests, UTF-8 inputs, binary, models, codec,
runtime DLLs, original reference and scripts before execution. All identities
still match afterward. Probe SHA-256 is
`bc6da9a2b11a58f9ed26c138e61545e98c03662b06e7420231da5961dea7a434`.
Retained GGML build-cache provenance records CUDA toolkit 13.3.73; NVIDIA-SMI
581.94 reports a driver CUDA API ceiling of 13.0. These are different version
surfaces. Exact reused DLL hashes are authoritative; no GGML/CUDA rebuild was
performed during this window.

Both models use the original full aligned ICL: original 2048-float Kraftwerk
speaker vector, matching transcript, 226 complete 16-code reference frames,
and decoder reference context. Sampling stays stochastic Talker/Predictor
temperature 0.9, top-k 50, top-p 1, Talker repetition 1.05 and minimum 2 frames.
Guard, retry/rollback, reseeding, prefix reuse, full-text geometry and greedy
modes are off. The inherited research stack is not isolated Engine #51 and
must not be substituted for the production engine or Bridge gitlink.

## A: observed frame counts, not semantic scores

| Model / case | Baseline | Penalty 2 | Penalty 4 | Penalty 6 | One-shot |
| --- | ---: | ---: | ---: | ---: | ---: |
| RU-stress, «Ладно.», seed 2027 | 2 | 2 | 4 | 4 | 3 |
| CF, «Ладно.», seed 2027 | 2 | 2 | 4 | 4 | 3 |
| RU-stress, MGU sentence, seed 75 | 2 | 87 | 87 | 87 | 86 |
| CF, MGU sentence, seed 75 | 2 | 90 | 86 | 86 | 86 |
| RU-stress, MGU sentence, seed 72 | 6 | 6 | 6 | 113 | 7 |
| CF, MGU sentence, seed 72 | 109 | 110 | 110 | 110 | 109 |

MGU sentence: «МГУ находится в Москве. Инженер проверил USB-порт, GPS и новый
процессор». One codec frame is 0.08 seconds of audio. The unchanged short
«Нет.» RU-stress case still emits two frames under every constant penalty.
Thus even penalty 6 does not consistently produce a plausible-length answer.
No attempt reaches the 256-frame cap in this discovery sample; this is not a
general guarantee against delayed termination or garbage.

### What the causal capture establishes

At the first eligible EOS decision, frame 2 of RU-stress «Ладно.», the effective
final-sampler EOS probabilities are approximately 98.90%, 90.68%, 51.32% and
10.25% for baseline and penalties 2/4/6. These are probabilities reconstructed
from captured **final exponential weights**, not the earlier allowed-vocabulary
temperature-1 figures. The Philox uniform is unchanged at `0.38556522131`,
subsequence 32. Categorical selection is not an argmax or simply `u < p(EOS)`:
candidate ordering and cumulative weights determine the selected token.

Penalty 4/6 avoids EOS at this decision but generation returns to EOS at frame
4. The one-shot arm logs original token 2150 (EOS), effective token 1720, the
same draw/subsequence, and EOS at frame 3. It does not obtain another draw,
forward or prefill for the alternative selection. Ordinary Predictor/forward
work continues for any resulting new frame.

Offline checks establish exact raw EOS subtraction with every other captured
logit unchanged at frame 2 in all 60 penalty/model/case comparisons. The first
two complete audio-code frames remain unchanged. Policy logs agree with the
bounded observer tokens, uniforms and subsequences; the one-shot flag is never
spent twice. Penalty-log `initial` means the penalized sample, not an
unpenalized counterfactual on a later diverged trajectory.

**Interpretation:** in the observed short case, blocking one EOS does not remove
the model's repeated preference to stop. The strong longer continuations on
seed 75 show a different outcome from the same intervention. This does not
establish a training cause, a universal detector, or semantic recovery.

### Missing quality/control evidence

The corpus's short controls were declared candidates, not prequalified correct
speech. Their new outputs are only 2–13 frames across these arms. No exact new
baseline is yet qualified by listening, so the false-intervention rate on
legitimate short speech is **not assessed**. No Base control arm was added to
the frozen 200 requests, and a longer answer is not counted as a successful
control. The next tuning decision must not conceal this evidence gap.

## D: manually enumerated input policies, unchanged sampler

Each model completed 30 unique inputs: two contexts, three seeds
(64/2027/2029), raw/selective/full-available accents and normative versus
counterfactual stress. The 36 intended aliases share six raw duplicates, which
were executed once and are not independent evidence. These are manual U+0301
inputs, **not an executed or qualified `tts-front-cpp` pipeline**.

EOS at two frames occurs in 7/30 RU-stress and 7/30 CF requests. In particular,
RU-stress seed 2027 stops at two frames for every first-carrier accent variant;
its second carrier generally continues longer. For CF the counterfactual and
context outcomes differ again. These observations demonstrate setup/input/seed
dependence, not the correctness or naturalness of any accent policy.

Accent placement, phoneme integrity, voice and complete words remain unassessed
for these exact outputs. The listening selection uses seed 64 contrasts and
retains both models' raw seed 2027 controls. Deliberately wrong stress remains
supplementary, not a standalone release blocker. No training-frequency audit
was performed; the [retained annotation hypotheses](tts-research-findings-and-next-stage-20261125.md)
remain hypotheses.

## Timing boundary

Every policy/model has a separate process with two warmup requests followed by
one measured «Ладно.» and one measured long Russian request: 40 requests,
20 measured. Observer/logit capture is OFF; bounded research debug logs remain.
The direct-engine first PCM is 186.44–189.50 ms for «Ладно.» and
177.05–179.07 ms for the long text across arms. Long-text warm prefill is
151.97–153.29 ms and RTF is approximately 0.292–0.297.

This small, fixed-order cost check does **not** establish a statistically
significant speedup/regression, a p95 distribution, isolated sampler overhead,
physical playback or first usable speech. Do not pool the short and long texts
into a latency percentile. A failed 0.16-second answer can still have first PCM
near 188 ms. Penalty 6 extends the RU long control from 99 to 102 frames, so
its extra total time includes changed generation, not just policy overhead.

## Integrity and compact listening handoff

All 200 outputs pass exact F32-to-PCM16 conversion and sample/code conservation;
all 32 numbered candidate copies match their source WAV bytes. All 40 repeated
same-policy comparisons match complete codes and streaming PCM, including
observer ON/OFF and fresh-process versus warm controls. Eighteen matching
historical baseline cases also match the actual retained codes and PCM. These
checks distinguish correct intervention mechanics from speech quality.

One directory: `.tmp/base-acceptance/eos-control-cmp50hx-20261125/run-001/listening-eos-and-accents/`.

- 00: original voice reference.
- 01–10: «Ладно.» diagnostic ladders, RU-stress then CF; several are near-silent
  or only 2–4 frames. They are not advertised as recovered speech.
- 11–15: RU-stress MGU seed 75, baseline then penalties 2/4/6 and one-shot.
- 16–18: CF MGU seed 75, baseline, penalty 2, one-shot.
- 19–20: RU-stress MGU seed 72, baseline and penalty 6.
- 21–25 / 26–30: RU-stress / CF documents contrasts, seed 64.
- 31–32: raw documents seed 2027 controls (RU-stress short, CF 31 frames).

For the first EOS listening pass, prioritize 12–15, 17–18 and 20; expected text
is the MGU sentence above. Assess full text, extra speech/sounds, final phonemes
and stable voice independently. For D use 21–30 and the exact README text.
Selection was made after measurement to compare candidates and failures; it is
not held-out scoring and does not replace all 200 attempts. No new listening
verdict is currently recorded.

## Next decision

First assess the long continuations and accent contrasts. If genuine recovery
is confirmed, compare that limited benefit with the repeated-EOS short failures
and qualify correct short controls before adaptive decay or held-out scoring.
Do not promote a blanket minimum, permanent EOS ban or an energy-only detector.
Reference stability B, alternative models C and Engine #51 integration E remain
separate pending work, not implied completed by this A/D allocation.

Reproduction tools, resource journals, all source/output hashes, causal checks
and full matrix live in the sealed local inventory referenced by both receipts.
The five model-free runner tests cover the schedule, environment scrubbing,
resource limits, owned-process cleanup and observer validation. R1 remains
**NO-GO**. No merge, release, production default, ABI, QTB, pin or frozen package
was changed.
