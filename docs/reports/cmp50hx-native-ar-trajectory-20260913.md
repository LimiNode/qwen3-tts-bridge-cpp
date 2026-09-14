# CMP 50HX native AR trajectory analysis — 2026-09-13

This diagnostic experiment explains why the same native Base request can end
after 26 codec frames for one seed and reach the 2048-frame generation limit
for another. It is research evidence, not semantic or release acceptance. No
sampling, EOS, generation-limit, or production-profile setting was changed.

## Method

Four seeds were selected from the post-padding semantic soak:

| Seed | Prior behavior |
| ---: | --- |
| 1006 | very short natural EOS |
| 1000 | normal-length natural EOS |
| 1002 | long natural EOS |
| 1008 | `max_tokens` runaway |

Every run used the same preloaded registered ICL reference, target text,
language, GGUF files, worker, and `stream_max_chunk_frames=1`. Startup
synthesis warmup was disabled. The opt-in qwentts diagnostic recorded prompt
geometry and fingerprints, the first 128 Talker sampling steps, and the first
two complete predictor frames. A naturally terminating run shorter than 128
steps recorded all of its steps.

The trace observes the final multinomial weights and the existing Philox draw.
It does not consume another random number and does not change sampling.

## Fixed-input verification

All four runs reported identical prompt geometry:

```text
T_ctx=236
T_trailing=1
ref_T=226
```

All engine diagnostic fingerprints also matched:

```text
prompt_ids_hash=d0f93610a7cca36e
input_hash=64cd364a2d82af99
trailing_hash=45a6fd74b5820cfa
speaker_hash=1f559899313e76ea
ref_codes_hash=a1baa1af50d7b4f1
```

This rules out seed-dependent prompt construction, reference extraction,
speaker conditioning, or trailing-text placement for these runs.

## Hardware results

| Seed | First PCM | Codec frames | Audio duration | Outcome |
| ---: | ---: | ---: | ---: | --- |
| 1006 | 1418.9 ms | 26 | 2.08 s | natural EOS |
| 1000 | 1422.8 ms | 156 | 12.48 s | natural EOS |
| 1002 | 1427.2 ms | 464 | 37.12 s | natural EOS |
| 1008 | 1415.7 ms | 2048 | 163.84 s | `max_tokens` |

Each captured WAV has the same SHA-256 as the corresponding seed in the
earlier non-diagnostic semantic soak. This hardware result confirms that the
trace did not perturb the generated token/PCM trajectory.

The comparison is executable rather than a manual transcription check:

```powershell
python scripts/validate-cmp50hx-ar-evidence.py `
  --probe-root C:\path\to\native-ar-trace `
  --evidence docs/reports/evidence/cmp50hx-native-ar-trajectory-883b608.json `
  --prior-evidence docs/reports/evidence/cmp50hx-native-reference-bisection-ab734.json
```

The validator hashes every raw WAV and compares its frame count and terminal
outcome with both sanitized evidence files. It also verifies the recorded
step-0 top-five values and Philox draw for every diagnostic seed. The earlier
seed-1008 soak hash was corrected from a one-character transcription error
after checking the raw WAV (`...154fb3...`).

These are cold-synthesis measurements: the worker preloaded the registered
reference, but `ready.warmed_up` was false. They must not be compared with the
previous approximately 182 ms warmed first-PCM result.

## First divergence

The observed step-0 Talker top-five distribution is identical for every seed.
Token `1721` has probability `0.774972141` and is selected in all four runs.
The trace does not persist a full-vocabulary weight hash, so this evidence
deliberately claims identical observed top-five values, not an unqualified
full-distribution identity. The trajectory
nevertheless starts diverging inside the predictor that completes this first
codec frame: its sampled codebook values already differ by seed.

The next Talker token then separates the trajectories visibly:

| Seed | Talker step 1 token | Philox draw | Selected probability |
| ---: | ---: | ---: | ---: |
| 1006 | 2 | 0.0528006479 | 0.105176575 |
| 1000 | 2 | 0.0330969468 | 0.124969915 |
| 1002 | 367 | 0.2176649570 | 0.0524411313 |
| 1008 | 1687 | 0.8325841427 | 0.584706068 |

The different step-1 probabilities for token `2` are expected: the predictor
has already supplied a different complete previous frame to the Talker. The
seed-dependent duration is therefore an autoregressive trajectory effect that
starts at the first predictor frame, not a difference in the fixed prompt.

## EOS behavior

Seed `1006` demonstrates that native EOS is functional. EOS first enters the
50-candidate set at step 25 with probability `0.002219` and rank 39. At step
26 it becomes rank 1 with probability `0.968020` and is selected.

The longer trajectories do not show a plausible-but-repeatedly-unlucky EOS in
the captured window:

| Seed | Non-zero EOS steps in trace | Maximum EOS probability | Best EOS rank | Final outcome |
| ---: | ---: | ---: | ---: | --- |
| 1000 | 8 / 128 | 0.010713 (step 116) | 17 | natural EOS at frame 156 |
| 1002 | 9 / 128 | 0.002064 (step 98) | 23 | natural EOS at frame 464 |
| 1008 | 6 / 128 | 0.001138 (step 112) | 37 | `max_tokens` at frame 2048 |

For seed `1008`, EOS is outside the final top-50 candidate set on 122 of the
first 128 steps. Even its best captured probability is only about 0.11%, with
rank 46 at that step. The runaway is therefore not explained by EOS being
available at a strong probability and merely losing several random draws.
After the early predictor divergence, the model state normally assigns EOS
negligible or zero post-filter probability.

Seed `1000` begins to assign EOS measurable probability near step 103 and ends
naturally after the bounded trace stops. Seed `1002` also ends naturally much
later, so the first-128-step trace intentionally does not claim to describe
their final termination transition.

## Static cross-implementation check

The native source and pinned FasterQwen commit `90b596d2` agree on Talker and
predictor sampling: temperature `0.9`, top-k `50`, top-p `1.0`, and Talker
repetition penalty `1.05`. Both apply repetition penalty before temperature and
top-k filtering. With top-p disabled at `1.0`, their active categorical policy
has the same shape.

Native qwentts assigns one explicit Philox subsequence to the Talker token and
15 subsequent subsequences to the predictor tokens in every codec frame.
FasterQwen calls `torch.multinomial` once for the Talker and once per predictor
codebook, including from its captured predictor graph. Equal integer seeds do
not establish token-for-token cross-runtime parity until those RNG-consumption
and categorical-selection mappings are compared directly.

Two static contract differences were found, neither of which explains the
captured seed-`1008` runaway:

- FasterQwen's default `min_new_tokens=2` suppresses EOS for Talker steps 0 and
  1. Native currently suppresses EOS only at step 0. This affects only very
  early termination; seed `1008` did not select EOS at either step.
- For non-default `top_p < 1`, native keeps the first candidate that crosses
  the nucleus boundary, matching the Hugging Face policy documented by
  qwentts. The pinned FasterQwen helper's descending implementation removes
  that crossing candidate. The traced request used `top_p=1`, so this branch
  was inactive.

These differences need focused contract tests and an explicit policy decision;
they are not a reason to tune the production profile from this four-seed run.

## Conclusion

The experiment supports four bounded conclusions:

1. Prompt and reference construction are stable across seeds.
2. The first seed-dependent state divergence occurs inside predictor sampling
   for codec frame 0; the main Talker token diverges at step 1.
3. EOS masking is not globally broken, because EOS becomes dominant and is
   selected on the short natural trajectory.
4. The `1008` runaway follows an AR state in which EOS probability collapses
   after early divergence; changing EOS penalties or sampling defaults without
   a cross-implementation comparison would be speculative.

The next targeted investigation should compare native Talker/predictor
sampling order, RNG consumption, filtering, and EOS handling with the pinned
Python/FasterQwen implementation. Any production change should be justified by
that comparison and then rerun through the multi-seed semantic soak and audio
listening gates. The first model-free step is tracked in
[`qwentts.cpp PR #8`](https://github.com/LimiNode/qwentts.cpp/pull/8): it adds
an explicit-uniform sampler seam and deterministic policy tests without
changing production defaults.

## Follow-up instrumentation

The subsequent qwentts.cpp parity work added two opt-in diagnostics. The
explicit-uniform policy harness compares native sampling with a dependency-free
Python reference over fixed edge cases; the predictor Philox trace records the
`base+1` through `base+15` subsequences and uniforms for the first two frames.
The latter is emitted only when the diagnostic dump is enabled and does not
consume or alter the production RNG stream. This historical report predates
those traces, so no new schedule claim is retroactively attributed to the four
recorded runs. Future hardware probes must preserve and validate the new
`predictor_philox` records before drawing RNG-schedule conclusions.

Sanitized measurements and bounded derived traces are stored in
[`evidence/cmp50hx-native-ar-trajectory-883b608.json`](evidence/cmp50hx-native-ar-trajectory-883b608.json).

The later seed-1006 hybrid capture has a separate executable Philox schedule
check. It validates all 30 recorded predictor uniforms and documents the
hybrid-runtime performance caveat without retroactively changing this
four-seed evidence:
[`cmp50hx-native-philox-schedule-20260914.md`](cmp50hx-native-philox-schedule-20260914.md).
