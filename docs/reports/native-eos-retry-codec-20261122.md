# Full retry and streaming-codec restoration on CMP50HX

Recorded2026-11-22. Research only; R1 remains **NO-GO**. This executes the
[bounded comparison plan](native-eos-retry-codec-plan-20261122.md), following
the [buffered rollback/listening study](native-eos-recovery-mechanics-20261122.md).
The two indexed canonical receipts own the current scoped results:
[full retry](native-eos-full-retry-cmp50hx-20261122.json) and
[private streaming codec](native-codec-stream-restore-cmp50hx-20261122.json).
New artifacts are not yet listened to; previous buffered listening is preserved.

## Exact identity and scope

Engine source/runner: clean `514b71813ff037cf5ae5fefc9f996668b5fbf8df`.
Bridge pre-run documentation checkout: `5cfc0e53d183d26152dc5482d7dff3f4994db1cc`;
Bridge worker/package/public DLL were not executed. GGML remains
`c044c6f03892f9d5e98213b05f8afea1f8b0d3c9`. Static probes are pinned in the
plan and receipts. Build: MSVC14.44.35207, CUDA13.3 SM75, opt-in research seams,
CUDA graphs ON, forceMMQ OFF. Local CTest21/21 passed, including both probe
selftests and Python collection/transposition tests.

CMP50HX UUID `GPU-40361931-6cb5-ac58-a059-5ba3e70986fb`, driver581.94 only.
RU-stress Q8_0 SHA256 `f4672741608d145fae169075cb0ec775a5382cbe9183eccb59c7ab9cc4797427`,
original Q8_0 codec `1883beeed99348fc35e23dd225e9082f93f6f8c109330a33d935baa8acdbfd94`.
Kraftwerk conditioning retains the exact speaker,226-frame reference and
transcript hashes. Text is the original126UTF8 bytes, SHA256
`d917e809733280d0fcc4603828e8253593839a22e29161216868f18ef4ba8a5e`:

> МГУ находится в Москве. Инженер проверил USB-порт, GPS и новый процессор.

Frontend, segmentation, prefix reuse and EOS guard OFF, original min2 and
stochastic Talker/Predictor unchanged. Existing runtime DLLs/models reused in
place; all before/after hashes match. No reload between attempts/groups within
each AR probe process. Separate stages/processes load normally. No runtime,
model, evidence or unrelated file was removed. Disk preflight:19,182,223,360
bytes free versus1,034,944,512 required for the complete bounded study.

Payload: `.tmp/base-acceptance/eos-retry-codec-20261122/`. Raw plans/results,
all originals/candidates, failed discovery audio, code histories and costs
remain local;729-file SHA inventory is referenced by both receipts. AR used
a900s bound; codec another900s, sequentially. First AR log creation to final
codec result spans about389s; codec runner reports177.844s. These are wall-clock
provenance including diagnostics/I/O, not GPU-utilization or latency benchmarks.
No timeout, interruption or missing group occurred. RTX4090 was not used.

## Full retry versus rollback1

All14 streaming controls match retained frame counts, naturalEOS and rawPCM.
All21 unchanged buffered replay pairs match complete16-code histories and
f32PCM byte-for-byte. Only after these gates passed were28 comparison groups
executed: seven seeds, two policies, two repeats, reversed policy order on
repeat1. Each policy intervenes10times and leaves4healthy controls unchanged.
All final AR outcomes reach naturalEOS; this does not establish word coverage.

| Original seed | Original frames | Rollback1 final, both repeats | Full retry final, both repeats |
| --- | ---: | ---: | ---: |
| 2 | 3 | 87 | 84 |
| 14 | 3 | 104 | 84 |
| 72 | 6 | 71 | 84 |
| 75 | 2 | 85 | 84 |
| 78 | 3 | 86 | 84 |

Alternate seed64 was fixed in advance. Every triggered full retry recomputes
prefill on the same loaded engine, with no AR snapshot/restore, and exactly
matches a same-run fresh buffered64 original in complete codes and PCM.
Original seed identity is retained separately from continuation seed64.
Healthy42/64 remain101/84frames, one attempt, no changed bytes. Each method's
repeated codes/PCM match. New rollback1 outputs also match matrix-001 exactly;
their known-case buffered listening evidence remains attached to that earlier
receipt, not automatically transferred to newly decoded streaming output.

| Observed span,10 triggered groups/policy | Rollback1 | Full retry |
| --- | ---: | ---: |
| Median complete group, original+candidate+artifact work | 3330.25ms | 3201.10ms |
| Snapshot capture, median (range) | 230.35ms (171.78–398.22) | 0 |
| Restore, median | 38.03ms | 0 |
| Retry admission including prompt/prefill, median | 0 | 159.86ms |
| Second prefill alone, median | 0 | 153.28ms |

These are **buffered diagnostic costs, not streaming TTFA**. Output lengths
differ,71–104 versus84frames, so total-time medians are not matched-work
speedup evidence. Rollback retains178–416MB of host-copied device payload in
intervened groups; healthy rollback controls still capture snapshots. They pay
roughly505–747ms capture cost, unlike retry's zero snapshot cost. No claim is
made about a future device-side rollback implementation. One original60s
deadline covers both attempts; admission/prefill is not interruptible and
cancellation is polled at frame boundaries. Final job time must not be mistaken
for whole-group time. The discovery<=8frame trigger is not a qualified detector.

## Streaming decoder state:31 exact local checks

This stage teacher-forces saved original/rollback1 complete codes for the five
known seeds and healthy64. It does not generate new AR continuations. Inputs
are explicitly transposed from AR[T,16] to codec[16,T], retaining both hashes.
The full reference is primed through the actual staging path, then copied to
one active lane. Existing private device snapshots capture all convolution
contexts, transposed-convolution carries, transformer KV rings and absolute
position. No engine state walker or production decoder was reimplemented.

FixedT1 and production-ramp schedules are tested separately. Eligible boundaries
are actual completed calls inside both histories' common complete-code prefix:

| Original seed | FixedT1 boundaries | Production-ramp boundaries |
| --- | --- | --- |
| 2/14/78 | 0,1,2 | 0,1 |
| 72/64 | 0,1,2 | 0,1,3 |
| 75 | 0,1 | 0,1 |

All31 cases pass:

- Snapshot restoration recovers every existing snapshot tensor byte and position.
- Unchanged suffix replay preserves completePCM and final snapshot state.
- Reset+full-reference+prefix reconstruction recovers boundary/final state andPCM.
- Changed continuation after restoration matches an independently decoded fresh
  full candidate in completePCM and final state; the fresh candidate also
  preserves the original PCM prefix up to the chosen boundary.

All14 production-ramp original comparisons match retained streamingPCM exactly
(six unique histories, several tested boundaries). This parity was independently
checked, not inferred from mechanical_pass. All output samples are finite and
sizes match complete frames. State inspection uses synchronous host reads;
codec timing is deliberately unqualified.

The earlier buffered-prefix mismatch is therefore not evidence of broken
streaming snapshots. Source inspection identifies a conditioning difference:
streaming primes the full reference; buffered chunked decode seeds a bounded
reference tail. This difference alone is not a quantified causal decomposition
of every buffered/streaming sample discrepancy. The relevant new demonstrated
property is exact restoration under the same streaming schedule/reference.

## Listening and next boundary

One folder: `.tmp/base-acceptance/eos-retry-codec-20261122/listening-retry-codec/`.
Seven numberedWAVs plus expected text inREADME.txt. File01 represents the ten
byte-identical buffered full retries;02–06 are the five production-ramp restored
rollback1 histories at boundary1;07 is healthy64. The method/source/hash key is
outside the folder. All new exact-file assessments remain **not_run**.
All unselectedT1/boundary variants and originals remain retained, not hidden.

This supports keeping full retry as the simple comparator and proceeding to a
bounded streaming commit-buffer experiment. It does not yet implement it.
Normal ramp emits1then2frames; rolling AR back before frame3 is not a codec
checkpoint after frame2. Coherent recovery must retain pending code rows,
codec chunk target/mapping, owned uncommitted PCM and a commit watermark, and
restart decode from an actual still-uncommitted chunk boundary. Callback pointers
are reusable scratch and must be copied. Already audible samples cannot change.
AR host snapshots also need a separate low-overhead bounded design.

Held-out seeds/texts, legitimate short replies, a live selector/risk detector,
genuine one-prefill dual fork, multi-lane/compaction, irreversible live commit,
physical playback, streaming latency and RTX4090 remain unqualified. No universal
EOS remedy, arithmetic defect or first-chunk speedup is established. Production
pin `130cb99af9ae12d554962fd0920e08fb4268af01`, ABI6, defaults and frozen package
remain unchanged. All research PRs stay Draft; no merge/tag/release.

Quality review: retry extends the existing attempt owner and shared deadline;
codec probe reuses the existing state-copy/decoder paths. The independent fresh
candidate check avoids treating copied-prefix identity as proof of restoration.
