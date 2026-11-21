# Short-utterance prefix-KV controls and separate timing

Status: bounded CMP 50HX matrix and timing complete; new audio is not yet listened to.
Date: 2026-11-21. No production/default, engine pin, ABI or sampler promotion.

This extends the [differential study](native-prefill-differential-20261121.md).
The earlier three exact-file user observations remain unchanged: baseline and
forced-MMQ prefix say `Да`, while ordinary prefix coughs before the word.
Those observations do not qualify any newly generated WAV.

## Frozen scope

The GPU is CMP 50HX UUID `GPU-40361931-6cb5-ac58-a059-5ba3e70986fb`,
driver581.94, CUDA13.3. Only native CustomVoice1.7B Q8_0, speaker `ryan`,
and the matched F16 comparator codec are tested. No Base/RU-stress ICL,
RTX4090, packaged worker, frontend, or release acceptance is implied.

The statically linked research probe SHA-256 is
`7e9ff122761e48b435272609980ae23692ed84f9794d7caa7feddc7ac0558443`;
the patched GGML CUDA DLL is
`bd54280b060357d21d0345cd1ecbc3f58e220b169561cd44f4c3a42255661b30`.
These are the retained differential-study binaries, built from engine
`53ac793c956dfc4d42c66b61402367ec0564cdf7` with its isolated dispatch patch,
not binaries rebuilt from the newer harness HEAD. Original build/patch
provenance and its limits remain in the differential report.

The quality matrix compares no-prefix baseline, full-source prefix9,
and full-source prefix9 with forced MMQ. Fusion is OFF for all three.
Russian and English use separate processes and longer primers, before and
after each16-case block. Eight short phrases (`Да!`, `Нет.`, `Спасибо.`,
`Готово.`, `Yes.`, `No.`, `Hi!`, `Thank you.`) use seeds64/65/72/75:
96 short outcomes plus12 primer controls per complete108-request run.
All raw PCM/WAV, final logits, input bytes, runtime hashes and failures remain
in ignored local evidence. Natural EOS and duration are not word coverage.

## Historical first run

`.tmp/base-acceptance/prefill-short-20261121/quality-001/` produced all108
results. Its collector incorrectly treated the unconditional `[ResearchJob]`
seed/serial line as a forbidden tensor/decision trace and marked all six
blocks incomplete. This is a harness-validation error, not a missing GPU run.
One actual synthesis failure also occurred: baseline `Hi!`, seed72, reached
the256-frame limit. That failure is retained and is not successful EOS.
Original results and their incorrect collector labels are not rewritten.

## Current repeated matrix

`quality-002/` uses corrected harness
`ef66c542bc4c72035003479e22743d0d4b8f85ba`. All108 planned rows and valid finite
PCM artifacts are present. No process, observer, effective-route or artifact
validation failure remains. The one baseline `Hi!`/seed72 synthesis again
reaches256 frames/20.48s instead of natural EOS: its block is explicitly
`completed_with_failures`, the runner returns nonzero, and the result is not
counted as successful synthesis. A complete observation reference is not a
quality acceptance; its documented failure does not prevent a separately
preplanned Russian timing experiment.

| Prefix variant | RU short PCM equal to baseline | EN short PCM equal to baseline | Natural EOS, all36 requests |
| --- | --- | --- | --- |
| No prefix, control | 16/16, self-control | 16/16, self-control | 35/36 |
| Ordinary full-source prefix9 | 0/16 | 0/16 | 36/36 |
| Full-source prefix9, forced MMQ | 16/16 | 4/16 | 36/36 |

The four exact English candidate cases are `Thank you.` seeds64/65/72/75.
`Yes.`, `No.` and `Hi!` change PCM for all four seeds even with MMQ. This
rules out universal equivalence. Layer-level diagnostics were not enabled
here, so the remaining English drift is not newly localized to one operation.
Russian numerical equality does not certify quality: baseline/MMQ `Нет.`
seed75 lasts15.76s and `Спасибо.` seed65 lasts6.16s; both are selected for
listening, not silently treated as good speech.

All108 raw PCM hashes, frame counts and terminal results repeat the first
run exactly. In every one of the six blocks, returning to the starting
primer after16 other requests reproduces its PCM. This is narrow sequential
evidence, not a full cache-reset, cancellation, restart or worker-isolation
qualification. No short-duration threshold is used as a text-coverage pass.

The [machine-readable summary](native-prefill-short-20261121.json) retains
per-case comparisons, duration/level proxies, exact plan/results hashes,
runtime/model/input provenance and block-level timing. Full local analysis
is `.tmp/base-acceptance/prefill-short-20261121/analysis-001/analysis.json`;
its hashed offline analyzer is retained alongside the runs. Neither generated
run is rewritten or discarded.

## Separate timing protocol

Timing uses the same frozen runtime/model/codec and one original Russian text,
seed64, in two counterbalanced sets of baseline/default-prefix/MMQ-prefix
processes. Each process has one first-use request and eight warm repeats.
Profiling, tensor dumps, route traces and decision observers are OFF.
The retained binary still emits existing operational seed/serial, prefix-hit,
bounded first-sample and ordinary engine logs; their overhead is included.
This is not a fully log-free or CUDA-event benchmark. Failed/incomplete timing
blocks must not enter latency aggregates. First-use is separate from warm
results; repeated identical inputs measure jitter, not a text population.

`timing-001/` produced54/54 finite natural-EOS outcomes: six processes,
first-use plus eight warm requests each. All54 PCM outputs equal their
same-variant quality control, despite the disabled observer. All six blocks
are eligible; no failed or incomplete timing sample is omitted.

| Variant | Warm first PCM p50 / p95, ms | Warm prefill p50 / p95, ms |
| --- | --- | --- |
| Baseline | 60.896 / 79.098 | 34.670 / 45.713 |
| Ordinary prefix9 | 51.320 / 63.657 | 25.428 / 36.932 |
| Prefix9, forced MMQ | 51.603 / 65.250 | 25.284 / 36.641 |

Each row has16 warm repeats. Nearest-rank p95 is the observed maximum at
this small n, not a reliable population tail estimate. MMQ first-PCM median
is9.292ms (15.3%) below baseline here. The difference is visible in both
counterbalanced blocks:60.489 vs51.783ms and61.074 vs51.255ms. MMQ and ordinary
prefix differ by only0.283ms in the aggregate median; no meaningful speed
advantage of one prefix route over the other is established.

The six first-use, cache-miss requests range257.736–279.669ms. These start
after model load; they are not CLI startup measurements or evidence that a
new voice's first request benefits from an already-populated cache. The
earlier approximately46ms saving for the much longer Base/RU-stress ICL
context is not remeasured or generalized by this CustomVoice-only run.

All GPU work, including the preserved first attempt and full repetition,
ran approximately15:11–15:24 UTC, within the shared30-minute budget. GPU is
idle after completion; no RTX run or release-package mutation was performed.

## One listening directory

`.tmp/base-acceptance/prefill-short-20261121/listening-short-first-pass/`
contains18 numbered unchanged WAV copies and a machine-readable manifest:

- 01–04: MMQ Russian `Да!`, `Нет.`, `Спасибо.`, `Готово.`, seed64; PCM equals
  the corresponding baseline, so redundant baseline copies are not added.
- 05–06: long MMQ/baseline-identical `Нет.` seed75 and `Спасибо.` seed65.
- 07–14: baseline/MMQ pairs for `Yes.`, `No.`, `Hi!`, `Thank you.`, seed64.
- 15–16: baseline/MMQ `Hi!`, seed72, including the baseline max-token failure.
- 17–18: ordinary-prefix `Да!` seed64 and long `Thank you.` seed72 controls.

The manifest fixes exact text, seed, source path/hash, duration and terminal
state. This is a bounded listening selection including failures, not a
replacement for the full matrix or an inferred success rate. Assess complete
words separately from cough/extra sounds and voice quality. All new-file
listening remains `not_run`; previous feedback is not silently transferred.

## Decision boundary

MMQ remains an experimental numerical-dispatch control, not an early-EOS
repair or a general equivalence claim. The narrow CustomVoice warm-request
latency gain is measured; Russian short sampled-PCM equality has expanded
to16 cases, but English equivalence fails in12/16 cases. New word coverage and
cough/voice quality require exact-file listening. R1 remains blocked under
its existing canonical acceptance records; historical failed prefix receipts
are preserved, not superseded by this study.
