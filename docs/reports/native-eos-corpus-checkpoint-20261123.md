# New-text live recovery and strided checkpoint transfers

Recorded 2026-11-23, following the [frozen plan](native-eos-corpus-checkpoint-plan-20261123.md).
The [indexed canonical receipt](native-eos-corpus-checkpoint-cmp50hx-20261123.json)
owns acceptance status. Research only; R1 remains **NO-GO**.

## Result and limits

All 284 planned groups passed their mechanical checks in one 831.159-second
batch, within the shared 1800-second bound. Strided KV transfers preserve the
observed complete codes and PCM while reducing checkpoint cost. The new corpus
extends live restoration mechanics, not semantic recovery acceptance: all 23
interventions occurred on short inputs, none on the nine longer-text cases.
New listening is **not_run**, and there is no new long-text rescue demonstration.

The preceding user feedback remains scoped to its original artifacts: healthy
control01 and live rollback candidates03-07 were subjectively OK; failed
control02 has problems. It is not a verdict on this new corpus or engine build.

## Exact identities and unchanged boundaries

- Runner/new probe: engine `4e47ed266f08cab9e13e277aa460a33bb607e769`.
- Preserved legacy probe build: `8ad3171e561c6340b7648a24ba308dd9b1e094bb`.
  Its current runner source is **not** its historical binary build identity.
- Bridge pre-run documentation checkout: `23e2763718ec318633323c994adadf9da100bea8`.
- GGML: `c044c6f03892f9d5e98213b05f8afea1f8b0d3c9`.
- Legacy binary: 582144 bytes, SHA256
  `002c969b5822e7f15b9d273e112e06f2bdc5155964e378fc99579ff239315f80`.
- Strided binary: 581632 bytes, SHA256
  `c73ffff8ee82ef179f5d9a66e4295c1b2a4cfc8297a4318acf575d08a065c187`.

CMP 50HX UUID `GPU-40361931-6cb5-ac58-a059-5ba3e70986fb`, driver 581.94;
MSVC 14.44.35207, CUDA 13.3 SM75, CUDA graphs ON, forceMMQ OFF. RU-stress Q8_0
talker SHA256 `f4672741608d145fae169075cb0ec775a5382cbe9183eccb59c7ab9cc4797427`,
original Q8_0 codec `1883beeed99348fc35e23dd225e9082f93f6f8c109330a33d935baa8acdbfd94`.
Unchanged Kraftwerk speaker and 226-frame reference/transcript retain their
before/after hashes in every plan/result. Existing runtime DLLs/models were
reused in place. File identities are not a loaded-module audit.

Only research KV transfer calls changed: per-head get/set loops became pitched
`get_2d/set_2d`. Precision, padded rows, offsets, host packing, bytes, codec
ownership and computation remain unchanged. Frontend, segmentation, prefix
reuse, EOS guard and scheduled reseeding stay OFF; stochastic Talker/Predictor,
min2 and codec ramp 1/2/4/8 are unchanged. Production engine pin `130cb99`, ABI 6,
QTB, defaults, models and the frozen package are untouched. This static probe
uses an irreversible in-memory sink, not the production Bridge worker or a
physical audio device.

## A/B/B/A equivalence and checkpoint cost

Each of four matrices retains 14 ordinary controls, 14 unchanged replays, six
negative guards and seven rollback groups. All 164 checks pass. Every matrix
matches A1's complete codes, full PCM, original output, sink, committed prefix,
fresh codec and replay-step artifacts. Two independent checks found:

- 693 corresponding artifact-field comparisons with no differences;
- 1005 comparisons of all 335 generated code/raw/WAV files against the other
  three matrices, with no missing or differing files.

Cancel, original deadline, capacity, sink refusal, stale checkpoint and newer
admission guards remain effective. No already committed sample is replaced.

For timing, average A1/A2 and B1/B2 **within each identical case**, then take
the stated cross-case statistic. Do not pool unmatched output lengths. A
`capture_ms` field is the sum of captures in a group, not automatically the
latency of one snapshot.

| Matched workload/statistic | Legacy ms | Strided ms |
| --- | ---: | ---: |
| Replay single-capture cell median |58.986|48.432|
| Replay restore cell median |38.678|29.505|
| Seven recovery groups, summed capture cost |2351.707|1943.255|
| Recovery capture cost / 40 captures |58.793|48.581|
| Five intervened recovery restore cell median |39.374|29.455|

The recovery capture reduction is **17.37%** at equal work. Recovery groups
contain 3/4/7/9 captures depending on history; each phase has 40 total. Paired
median recovery group-total saving is 65.719 ms; controls without checkpoints
change by -1.071 ms, consistent with small timing variation. Individual runs
and all matched costs remain in `summary.json`. An alternative pooled median
over the ten restore observations is 39.230 to 29.221 ms; it is a different
aggregation, not a conflicting measurement.

KV backend calls fall 528 to 66 per capture/restore (566 to 104 including bridge
and codec copies), **not** an eightfold wall-time gain. Payload stays68338304
bytes/checkpoint: Talker58720256, Predictor655360, bridge8192, codec8954496.
Two retained snapshots use136676608 bytes; replacement transiently owns a
third, totaling205014912 payload bytes. Allocations, transferred bytes and
memory are not reduced. These are not peak VRAM/RSS measurements.

Fresh-codec reconstruction and synchronous diagnostic work remain present.
This study measures checkpoint costs, not prefill, streaming TTFA, audible
onset, physical playback or end-to-end recovery speedup. Cheaper copies alone
do not establish that the current snapshot strategy is cheap enough for production.

## New corpus

The frozen 12-text corpus, exact languages and UTF-8 hashes are in the plan.
Seeds 1009/2003/3001 and continuation64 were fixed before execution. Familiar
short words are intentional; this is not a calibrated held-out detector test.

All 72 baselines establish 36 byte-exact text/seed repeat pairs; all 12
checkpoint1 unchanged replays match their own controls. All 36 conditional
rollback1 groups preserve full codes/PCM, actual sink bytes, saved prefix and
fresh streaming-codec reconstruction. Three new short interventions retain
nonzero irreversible commits: 1920 samples for ru-yes1009 and ru-thanks2003,
5760 for ru-no2003. The other 20 intervened cases have zero commit.

Values below are frames in seed order 1009/2003/3001; a frame is 80 ms. Candidate
columns include unchanged outputs where no intervention occurs.

| Text label | Original frames | Final frames | Interventions |
| --- | --- | --- | ---: |
|ru-yes|3 /2 /2|3 /2 /2|3|
|ru-no|2 /7 /2|2 /9 /3|3|
|ru-thanks|2 /5 /2|2 /4 /15|3|
|ru-ready|2 /12 /2|2 /12 /4|2|
|en-yes|2 /2 /2|2 /2 /3|3|
|en-no|2 /2 /2|2 /2 /2|3|
|en-hi|2 /2 /2|2 /2 /2|3|
|en-thanks|2 /2 /2|2 /2 /17|3|
|ru-short|14 /12 /15|14 /12 /15|0|
|ru-new|69 /69 /59|69 /69 /59|0|
|ru-two|84 /86 /90|84 /86 /90|0|
|en-new|61 /65 /64|61 /65 /64|0|

The deliberately naive natural-EOS<=8 trigger intervenes in23/27 short-input
cells and 0/9 longer-input cells. Twenty candidates still terminate at <=8 frames;
three exceed it. None of these duration observations establishes text coverage,
rescue, false positive, false negative or an improvement in pronunciation.
There is no seed search or unreported second retry. Safe restoration mechanics
and selection of a useful new continuation are separate problems.

## Evidence, listening and disposition

Payload: `.tmp/base-acceptance/eos-corpus-checkpoint-20261123/`. All five plans,
results, original/candidate PCM and complete codes, negatives, sink/prefix/step
files, logs, binary copies and evidence scripts remain retained. The inventory
identifies 2413 files, 252438710 bytes, excluding the inventory itself. Inputs,
runtime, models, probe and clean engine source were unchanged before/after.
The original 60 s logical-request deadlines, 256-frame cap and 16-frame PCM
holdback apply throughout. There are no missing, failed or timeout cells.
Snapshot allocations and saved PCM slices are separate from the holdback cap.

One listening folder:
`.tmp/base-acceptance/eos-corpus-checkpoint-20261123/listening-corpus-checkpoint/`.
Files 01-46 are all 23 consecutive original/candidate pairs; 47-50 are untouched
`ru-short`, `ru-new`, `ru-two`, `en-new` controls at seed1009. README supplies
expected text, selection-manifest supplies exact source/copy identities. WAVs
are untrimmed, unnormalized PCM16 mono 24 kHz copies. New listening remains
not_run; original short outputs are retained rather than silently rejected as
failed speech. Assess requested words and extra sounds separately. The full
corpus is not replaced by this listening selection.

Local research CTest 26/26, corpus runner 22/22 and live runner 20/20 pass.
The 18-case CPU stride fixture covers F32/F16, multiple heads, nonzero view
offset and unchanged sentinels/tails. Research-OFF CPU/shared build, C ABI
probe and five sampling/frame/guard CTests pass. Engine exact-HEAD CI 2/2 passes
at 4e47ed2 (run45096878771). Independent corpus audit checks 638 identity entries,
156 WAV identities, 40688 complete codec IDs, 35 prefix checks and 12 replay
steps; all 45 unique PCM hashes are finite. Source/asset identity checks and
mechanical results do not constitute human listening.

The final Bridge documentation commit requires its own CI; no earlier pass is
inherited. The indexed receipt and project status preserve mechanical,
listening and release layers separately. Engine#50/Bridge#332 remain Draft;
no merge, tag or release. Still unqualified: short-answer quality and live
detector, general recovery efficacy, cheaper-memory/device-side snapshots,
genuine one-prefill dual fork, production Bridge orchestration, multi-lane,
physical playback/timing, RTX4090 and release quality. Stop GPU work here;
listening to the new exact artifacts is the next quality decision.
