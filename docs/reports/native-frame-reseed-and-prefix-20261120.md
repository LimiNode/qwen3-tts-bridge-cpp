# Frame reseeding and shared-prefix continuations on CMP 50HX

Research, 2026-11-20. R1 remains **NO-GO**. No sampler/EOS defaults,
Bridge dependency pin, frozen package, model, or historical receipt changes.
Scoped standalone-WAV listening is recorded below; no production-recovery,
physical-playback or RTX gate is promoted.
Experimental engine code is in [qwentts.cpp Draft PR #49](https://github.com/LimiNode/qwentts.cpp/pull/49).

## Measured result

The first one/two bad frames do **not** force every continuation to terminate
early. This justifies further shared-prefix research, not a production recovery
claim. Always reseeding per frame did not improve this small prospective sample.

| Policy | Short-duration natural-EOS proxy / 24 unique non-short cases |
| --- | ---: |
| Baseline | 0/24 |
| Per-frame reseed | 2/24 |
| Early-2 reseed | 1/24 |
| Early-4 reseed | 0/24 |

Each denominator is eight seeds on each of the original RU, unseen RU and
unseen EN texts; the eight legitimate `Да!` cases and repeats are separate.
The new per-frame failures were original-text seeds 68 and 70 (5 and 4
frames); early-2 failed at seed 71 (3 frames). Do not interpret the zero for
early-4 as a statistically demonstrated improvement over zero baseline errors.

The known seed-2/14 controls reproduce three-frame EOS twice each. Their own
forced one/two-frame prefix replays reproduce all original codes and raw PCM.
The other selected short controls are seed 4: 5 frames, seed 21: 10 frames,
and seed 31: 4 frames. These discovery controls are not a random failure-rate
estimate. The 18 baseline observations also match the earlier pre-correction
baseline bit-for-bit in complete codes and full f32 PCM.

| Input seed | Baseline | Switch after 1 frame | After 2 frames | After 3 frames |
| --- | ---: | ---: | ---: | ---: |
| 2 | 3 frames | 85 | 85 | 4 |
| 14 | 3 frames | 95 | 95 | 3 |

Both repetitions match. The unchanged complete prefixes have length exactly
1/2/3 respectively. Changing draws after the third frame did not escape the
short-duration outcome in these cases; changing them earlier changed history.

### Scoped listening: switch after one/two frames

On 2026-11-20 the user confirmed listening to all four WAVs in each of
`matrix-final-006/switch-1` and `switch-2`: the complete original sentence is
spoken in every file and the overall speech is normal. The user noted that
`МГУ` is sometimes pronounced too quickly, without attributing this to a
particular file. The [canonical listening receipt](native-eos-switch-listening-cmp50hx-20261120.json)
records the eight exact paths, byte counts and SHA-256 values.

This is **eight listened files, four unique WAV payloads**: seeds 2/14,
switch-after 1/2, each repeated. Seed 2 produces 6.8 s and seed 14 produces
7.6 s. Full-text coverage is now user-confirmed for these cases, not inferred
from duration. Overall listening remains `partial_pass`; detailed voice
fidelity, individual stress accuracy, artifact-free continuity and live branch
transitions were not separately assessed. Restart qualification remains absent.

This result does not transfer to per-frame/early-N reseeding, other texts or
seeds, teacher-forced single/dual prefixes, another GPU or production recovery.
It does not revise the prospective 0/24 versus 2/24 comparison above. Keep the
abbreviation-speed issue as a separate frontend A/B check; do not silently
change the frozen discovery text when comparing EOS trajectories.

Single-slot teacher-forcing results on **unique continuation seeds 64..71**:

| Preserved bad prefix | Above 12 frames, natural EOS | Short-duration proxy |
| --- | ---: | ---: |
| Seed 2, one complete frame | 8/8 | 0/8 |
| Seed 2, two complete frames | 8/8 | 0/8 |
| Seed 14, one complete frame | 7/8 | 1/8 |
| Seed 14, two complete frames | 8/8 | 0/8 |

Additional continuation seed 1 is above the proxy in all four cases. None
of these counts alone establishes speech coverage. Seed 14's one-frame prefix with
continuation seed 64 still fails, including its repeat.

### Scoped listening: one-frame seed-2 prefix

On 2026-11-20 the user confirmed the complete correct original phrase in the
three specifically linked outputs: single seed 64 (6.96 s), batch seed 64
(6.96 s), and batch seed 65 (7.20 s), all with one complete seed-2 frame
preserved. The [separate canonical receipt](native-eos-prefix-listening-cmp50hx-20261120.json)
records their exact paths, sizes, hashes and listening scope.

On 2026-11-20 the user reported **gradual fading toward the end only for the
batch seed-65 artifact** (`dual-seed-2-frames-1/group-1-lane-1.wav`), while confirming its
full correct phrase. This is a listening observation with unresolved cause and
perceptual severity, not a demonstrated batch, sampler or codec defect. Do not
label that output artifact-free or constant-volume. Text coverage passes for
the three named artifacts; overall listening remains `partial_pass`, without
transfer to other continuations, a real state fork or live PCM switching.

A subsequent [offline matched-seed comparison](native-eos-fade-comparison-20261120.md)
finds similar quieter late portions in single and batch seed 65: 90 identical
complete code frames, but nonidentical raw PCM. Whole-file batch/single RMS
differs by -0.002285 dB; conversion to WAV adds no gain/fade. The contour is
not monotonically decreasing and is not explained solely by the low-level
final tail. Cause was not isolated, and at that time single seed 65 had no
listening verdict. This does not rule out other batch-dependent
artifacts or overwrite the user's observation.

On 2026-11-21 the user listened to single seed 65 and found slight or
effectively absent fading, less noticeable at medium/high playback volume,
with no noticeable difference from the earlier track. The
[new scoped receipt](native-eos-seed65-listening-cmp50hx-20261121.json) records
an informal comparison, not a general quality pass or calibrated equivalence.
No actionable fade defect is established; the earlier three-file text-coverage
verdict is preserved without extending it to single seed 65.

True two-slot forced-prefix groups have **24/24 byte-identical first PCM
chunks**, and 36/36 first same-seed single/dual comparisons have identical
complete generated codes. However, all-output PCM is not bit-deterministic
across codec lanes: same-seed paired lanes can differ despite identical codes
(peak absolute f32 difference 0.00186..0.00613; RMS difference
0.0000915..0.000169). Their first shared chunk still matches exactly.
Audible significance of these numerical differences and full codec-state
equivalence remain unassessed. The reported seed-65 fade is not causally
attributed to the cross-lane PCM differences.

Illustrative warm instrumented timings, excluding each process's first group:

| Case | Lane count | First PCM p50 / p95 | First-to-second PCM gap p50 / p95 |
| --- | ---: | --- | --- |
| Seed-2 one-frame prefix | 1 | 179.5 / 196.2 ms | 50.4 / 57.0 ms |
| Same prefix, paired continuations | 2 | 355.7 / 356.4 ms | 71.1 / 79.0 ms |
| Seed-2 two-frame prefix, paired | 2 | 356.8 / 365.4 ms | 70.8 / 71.2 ms |

For these stable N=2 examples, whole-step-four completion is about 95 ms
after first PCM: every measured warm lane misses the first 80-ms audio budget
by at least 14 ms. This is not a measured intermediate EOS-decision timestamp
and does not rule out an earlier in-step selector. There is no physical-playback
or inaudibility claim. Median common-group-span/per-lane-audio RTF is about
0.30 single / 0.49 paired; paired aggregate-throughput RTF is about 0.25 and
must not be substituted for a user's per-branch latency.

## Failures and incomplete qualification

`matrix-final-006` planned 288 lane observations. It retains **274 analyzed
observations: 272 normal terminal outcomes and 2 cooperative cancellations**.
The last independent-pair run hit the 240-second external watchdog and is
explicitly unscored, including any partially written raw results. The canceled
lanes are the repeated seed-14/two-frame pair 64/65. This is not a 288/288 PASS.

The earlier corrected-runtime `dual-smoke-005` independently completed all
14 independent-pair observations (two short-duration controls, twelve above
the proxy). Its separate 18 baseline controls also passed. Do not hide the
later failed run by replacing it with this earlier success.

Host saturation was observed after the slowdown (100% total CPU after the
probe exited); a normally ~4-second model-free diagnostic test then took
~210 seconds. This is a confounder, **not an isolated cause** of the timeout.
The affected late timings are not pooled into the illustrative timing table.
The direct kill did not confirm termination within 15 seconds; later inspection
found no remaining probe and the GPU back at 11 MiB. The updated runner records
this termination outcome separately; its independent-child watchdog unit test
passes. No GPU reset or unrelated process termination was used.

After host load subsided, one separately retained, bounded
`post-load-recheck-007` repeated only the two affected scenarios with the same
probe, runtime, inputs and seeds. All **26/26** lanes terminated with natural
EOS, with no errors, cancellations, max-token limits or watchdogs. The
seed-14/two-frame-prefix scenario completed 12/12 lanes (79..104 frames),
including exact complete-code and full-f32-PCM reproduction of its repeated
64/65 pair. Its first PCM chunks match in 6/6 paired groups. Independent pairs
completed 14/14 lanes, retaining the two known three-frame seed-2/14 failures;
all 14 outcomes, complete codes and full PCM match `dual-smoke-005`.

This targeted repeat does **not** erase the cancellations/timeout in 006 or
establish their cause. Warm callback TTFA p50/p95 was 355.9/361.8 ms for the
prefix pairs and 354.8/355.2 ms for independent pairs; these separate results
are not pooled into the earlier table. All 22 warm lanes still miss the first
80-ms audio budget at whole-step-four completion, which is not an intermediate
Talker EOS-decision timestamp. Batch stability and live-selection qualification
remain incomplete. Earlier sampler-correction/stale-build reruns are retained
and identified below.

For non-OK engine retirements, the engine's native frame-count field can be
zero despite earlier PCM. The CSV retains `observed_trace_frames` separately.
For a process killed mid-group, only already flushed earlier groups and
traces survive; the final group's in-memory PCM is not a recovered WAV.

Coarse device-wide memory snapshots were about 3,544 MiB for N=1 and
4,652 MiB for N=2. They are snapshots, not measured peaks or an allocation
profile. An initial attempted snapshot landed between processes (142 MiB) and
must not be quoted as an active two-slot measurement.

Same-slot normal repeats match the observed traces/PCM in this scope. The
two canceled repeat lanes are not successful determinism comparisons; the
four same-seed/different-lane PCM differences are recorded separately above.
No universal cross-lane or cross-GPU determinism contract is inferred.

## Retained identities

The [research evidence metadata](native-frame-reseed-evidence-20261120.json)
contains executable, backend, CUDA dependency, model, conditioning, plan and
analysis hashes plus nine listening candidates. The
[observation CSV](native-frame-reseed-observations-20261120.csv) exposes all
274 analyzed main-matrix rows, 32 separate preflight rows and 26 separate
post-load-recheck rows (332 total), with dataset identity, seeds, policy,
terminal status, timing and PCM/WAV hashes. Repeats are not independent samples.

The measured engine source is `5b03c53ee8bb2f7f4f102005ab7f6ba148ffd92c`,
ggml `c044c6f03892f9d5e98213b05f8afea1f8b0d3c9`, ABI 6; compiler MSVC 19.44,
CUDA 13.3, sm75, Release, graphs and flash attention enabled. Later research
runner/watchdog documentation changes do not change the measured model code.
The recheck records runner/source HEAD
`0141bd2b96d3133db3186eb56b8c2ccbf17bc3e6`; its probe and runtime hashes are
unchanged from 006, rather than a newly built inference implementation.
GPU: CMP 50HX UUID `GPU-40361931-6cb5-ac58-a059-5ba3e70986fb`, driver 581.94.
RU-stress Q8_0 and Kraftwerk conditioning are unchanged; frontend is OFF.
Maximum generation is 256 frames, streaming chunk cap 8 (ramp 1/2/4/8).

Payload root, relative to the primary Bridge checkout:
`.tmp/base-acceptance/eos-reseed-branching-20261120/`.
Preserve `baseline-001`, `matrix-001`, `singles-002`, `dual-control-003`,
`matrix-batchfix-004`, `dual-smoke-005`, `matrix-final-006` and
`post-load-recheck-007`.
The first two N=2 aborts precede the correction. `matrix-batchfix-004` also
aborted because local Ninja missed changed-header dependencies and retained
the old engine object; it is invalid as a corrected-runtime check. The owner
was explicitly rebuilt, the executable hash changed, and `dual-smoke-005`
then verified the corrected runtime before the main matrix. Historical and
stale-build payloads are not pooled as corrected-runtime success.

## Questions and method

This follows the [same-history source-checkpoint probe](early-eos-source-checkpoint-probe-20261120.md).
It investigates changing stochastic continuations, not a newly demonstrated
native/source arithmetic defect or a model-training correction.

1. Does deterministic reseeding per complete codec frame reduce the observed
   short-EOS proxy on new seeds/texts, rather than merely move failures?
2. Can a bad seed-2/14 prefix of one/two **complete 16-codebook** frames have
   a long continuation, and can two such continuations run in a true batch?

The internal engine probe admits one/two slots before stepping the engine.
It does not submit sequential QTB requests. It reuses loaded weights and
captures raw f32 PCM, PCM16/mono/24-kHz listening WAVs, complete early codes,
finish reason, status and common-clock callback/step timings. A cooperative
60-second group deadline is backed by a 240-second process watchdog, within
one 1,800-second run budget. Output directories are exclusive; failed and
superseded runs remain intact.

The probe statically links the engine core and loads the new GGML backends;
the separately built qwen.dll is a co-product, not the library called by this
probe. All measured policies use the same bounded AR trace instrumentation.
These are instrumented callback timings, not an untraced packaged-worker or
physical-playback performance qualification.

The full matrix is frozen before the GPU launch: known seeds
2/4/14/21/31 and controls 1/42/43/44 twice; switch-after 1/2/3 on seeds 2/14
twice; four text/seed sets for baseline/per-frame/early-2/early-4; complete
one/two-frame seed-2/14 prefixes with other seeds and self-seed transparency
controls; true two-slot same-prefix and independent pairs. Independent seeds
are 64..71; the four texts are the original abbreviation sentence, `Да!`,
one unseen RU sentence and one unseen EN sentence. Repeated seeds are
separate reproducibility checks, not additional independent observations.

Seed schedules use SplitMix64 v1 to derive one 64-bit frame key shared by
Talker and all 15 predictor draws. Existing Philox subsequences remain
`16*f + codebook`; PCM chunk boundaries do not affect reseeding. `early-2/4`
holds its final derived key after that window; `switch-after:N` leaves the
first N complete frames unchanged. Neither logits nor EOS suppression changes.
The research compile option defaults OFF and ordinary builds do not read
the research environment variables.

Prefix-only teacher forcing is separate from tensor-dump mode. It overrides
complete frames before history and codec consumption without heavy diagnostic
graphs/readbacks. Self-seed replay must reproduce the original codes **and
raw PCM**, not only the supplied prefix. This is independently recomputed
state, not a state snapshot/fork.

## Concrete batched sampler defect

The first true N=2 run aborted before producing audio at
`GGML_ASSERT(ggml_can_repeat(b, a))`. A no-prefix N=2 control also aborted,
so this was not evidence that a shared prefix was intrinsically invalid.
The predictor sampler mixed a `[1,N]` greedy mask with `[N]` selected IDs.
The forced-code row view also had the wrong per-slot stride at N>1.

The fork correction uses a contiguous `[N]` uniform/mask and the correct
`[N]` forced-code row. Materializing the strided uniform is necessary for
the CPU scale operation too. Model-free CPU tests exercise mixed greedy,
stochastic and forced N=1/2/3 lanes, including a nonzero predictor step.
No model weights, sampling probabilities, EOS policy or public ABI changed.
Original and stale-build aborts are retained as failures, not silently discarded.

## Interpretation boundaries

`natural EOS and <=12 frames` on a non-short text is only a duration anomaly
proxy. A larger output does not establish that all text was spoken, the
reference voice stayed stable, or the join sounds correct. Short text is
excluded by its known input label, not by its future outcome. For example,
legitimate `Да!` outputs can contain only two codec frames.

The one/two-frame experiments answer prefix salvageability, not detector
accuracy. No general classifier, live selector, automatic retry, state fork,
winner cancellation, or PCM splice is installed. Identical first-frame codes
alone do not establish identical first PCM; the latter is checked as raw
f32 bytes. Batched arithmetic need not reproduce single-slot trajectories.

Both slots currently pay serial prefill before either emits PCM. This is not
a zero-added-TTFA fork. Callback TTFA is measured directly from one clock
started before both admissions; native first-code TTFA is a different metric.
Common group spans are used for RTF; per-lane batched phase times are not
summed. Fourth-step timing relative to the first 80-ms audio budget is only
a hypothetical timing bound, not a qualified branch decision or underrun test.
It is the **end of the whole step**, not a timestamp of the intermediate
Talker EOS decision. A selector inserted earlier inside that step might
decide sooner; these measurements alone cannot prove such a design impossible.
Natural retirement N=2->1 is not cancellation of a selected losing branch.

## Reproduction and next boundary

Build qwentts PR #49 with `QWEN_RESEARCH_FRAME_SEEDS=ON`, `QWEN_SHARED=ON`,
CUDA and the machine's explicit GPU architecture. Run
`tests/run_eos_research.py --help`; all model, retained-conditioning, registry,
discovery-analysis, executable, output and GPU paths/identities are explicit.
`tests/analyze_eos_research.py MATRIX_DIR NEW_JSON` performs offline comparisons
without interpreting retrospective outcomes as live selection. Its
`--self-test` is model-free.

Ignored PCM, tensor inputs and manifests are not transferred by Git. An
independent repeat requires the exact retained conditioning evidence and its
verified inventory, not a similarly named voice. Current task scope is CMP
50HX only; RTX is deliberately not run.

Next: qualify the broader corpus and measure the actual decision/commit timing
before deciding whether
a narrowly opt-in true state fork/selector merits implementation. That work
must cover all slot/KV/codec/pending-frame state, bounded loser cancellation,
one deadline, commit boundaries and actual playback. Keep immediate baseline
streaming available; do not silently enable universal reseeding or a mandatory
startup gate from this small corpus.
