# Live single-lane rollback with irreversible PCM commits

Recorded2026-11-23, following the [frozen plan](native-eos-live-rollback-plan-20261123.md).
Research only; R1 remains **NO-GO**. The [canonical receipt](native-eos-live-rollback-cmp50hx-20261123.json)
owns current status. Earlier buffered and codec-only evidence remains intact.

## Identity and execution boundary

Clean engine source/runner `8ad3171e561c6340b7648a24ba308dd9b1e094bb`,
GGML `c044c6f03892f9d5e98213b05f8afea1f8b0d3c9`. Bridge documentation
checkout before execution: `50887f5c843addbd81b326bb67e714771ad9eb63`.
Static probe582144bytes, SHA256
`002c969b5822e7f15b9d273e112e06f2bdc5155964e378fc99579ff239315f80`.
MSVC14.44.35207, CUDA13.3 SM75, CUDA graphsON, forceMMQOFF, research seamsON.
Production pin `130cb99af9ae12d554962fd0920e08fb4268af01`, ABI6, defaults
and frozen package remain unchanged. No public DLL or Bridge worker execution.

CMP50HX UUID `GPU-40361931-6cb5-ac58-a059-5ba3e70986fb`, driver581.94 only.
RU-stress Q8_0 talker SHA256
`f4672741608d145fae169075cb0ec775a5382cbe9183eccb59c7ab9cc4797427`,
original Q8_0 codec
`1883beeed99348fc35e23dd225e9082f93f6f8c109330a33d935baa8acdbfd94`.
Unchanged Kraftwerk speaker/226-frame reference/transcript and original126UTF8
request bytes, SHA256
`d917e809733280d0fcc4603828e8253593839a22e29161216868f18ef4ba8a5e`:

> МГУ находится в Москве. Инженер проверил USB-порт, GPS и новый процессор.

Frontend, segmentation, prefix reuse, EOS guard and scheduled reseedingOFF;
original min2, stochastic Talker/Predictor and production codec ramp1/2/4/8.
Existing DLLs/models reused in place and hashed before/after; assets and clean
source unchanged. Runtime-file hashes are not a loaded-module audit.
Payload: `.tmp/base-acceptance/eos-live-rollback-20261123/live-001/`.
The complete sequential runner took126.531s against1800s bound; each logical
request retained its original60s deadline. Disk preflight14999392256bytes free
against1050017792 required, including512MiB reserve. No missing/timeout cells.

## What was actually exercised

The opt-in engine checkpoint now owns coherent AR and codec state, including
pending complete-code rows, chunk target, lane mapping and live flag. Its codec
mirror is independently owned, not an evictable reference-cache slot. The static
probe owns a bounded PCM holdback and an in-memory irreversible test sink.
Callback scratch is copied immediately. One newest ordinary chunk is held;
the next ordinary callback commits the previous chunk. EOS observation freezes
commits before terminal drain. This is live AR+codec restoration, not buffered
redecoding masquerading as streaming, but not production Bridge integration or
physical playback either.

The cursor C never moves backward. Restoration requires C<=D, where D is the
checkpoint's decoded PCM boundary; held audio is restored only for [C,D).
Saved pending rows continue through the restored normal codec. A checkpoint at
AR frame2 has decoded frame1/pending1/target2, not two decoded frames.

All41 planned groups passed, in prerequisite order:

| Gate | Result | Independent evidence |
| --- | --- | --- |
| Ordinary controls |14/14|Two repeats/seven seeds match retained complete16 codes and streamingPCM|
| Unchanged live replay |14/14|Checkpoint1/2, immediate replay step, full codes/PCM and actual sink bytes match|
| Negative guards |6/6|Cancel, original deadline, capacity, sink refusal, stale checkpoint and newer admission reject recovery|
| Rollback1 discovery |7/7 mechanics|Five interventions and two untouched healthy controls; candidate matches fresh full streaming-codec reconstruction|

Six checkpoint2 replays preserve a nonzero1920-sample commit. Seed75 instead
reaches EOS after2frames, so its terminal drain correctly leaves C0; replay
restores an internally retired job without duplicating its terminal notification.
Every successful final sink file equals full observed PCM. Stale refusal occurs
with5760samples already committed past its saved1920-sample boundary. Cancel,
deadline, capacity and sink-refusal groups commit zero samples. Cancelled engine
statistics report0frames; actual saved-code counts1/1/3/3/7 are recorded separately.

The newer-admission test checks the old snapshot while the newer job is active,
then after its cancellation/retirement. For the latter identity-isolation check
only, cancellation is cleared and terminal metadata temporarily set to OK/EOS;
actual CANCELLED metadata is restored before reporting. This synthetic guard
exercise is not a successful newer synthesis or an EOS outcome. It reports
two admissions/prefills, unlike one-prefill positive groups.

## Changed continuation and commit safety

One rollback is triggered only for successful naturalEOS<=8frames, with seed64
fixed before execution. This threshold is a known-case discovery trigger, not
a calibrated early-EOS detector. Explicit seeds opt into this research policy.

| Original seed | Original frames | AR restore | Decoded/pending | Committed samples | Candidate frames |
| --- | ---: | ---: | --- | ---: | ---: |
|2|3|2|1/1|1920|87|
|14|3|2|1/1|1920|104|
|72|6|5|3/2|1920|71|
|75|2|1|1/0|0|85|
|78|3|2|1/1|1920|86|

Healthy42/64 remain101/84frames with identical original/final bytes and no
intervention. Every candidate preserves the original complete-code prefix and
all actual pre-restore committed bytes. Fresh reconstruction resets codec state,
primes the full reference and decodes the entire candidate through the same
production schedule, without restoring a checkpoint; every resulting f32sample
equals the live result. Reconstruction is diagnostic and occurs before final
held-tail release, so measured spans are not operational streaming latency.

All five candidate PCM/WAVs also equal the prior production-ramp codec-only
rollback1 outputs byte-for-byte. Those exact earlier WAV hashes have positive
user listening recorded in the [preceding receipt](native-codec-stream-restore-cmp50hx-20261122.json).
This is an artifact-identity fact, not a transferred acceptance verdict for the
new engine execution. Listening was `not_run` at initial publication. On
2026-11-23 the user directly listened to the new-run folder and confirmed
subjective OK for healthy control01 and live rollback candidates03-07. The user
explicitly clarified that original failed control02 has problems; it is not
included in the positive scope. The canonical receipt now records scoped
`partial_pass`, with exact per-WAV identities. This feedback is not a detailed
voice-fidelity, transcript, tail or sequential-isolation audit and does not
qualify new texts/seeds or the release. The frozen payload remains unchanged.

## Cost, checks and disposition

Current held-PCM capacity is16frames=30720samples=122880f32bytes. Admission
peak records16frames; saved held slices, complete diagnostic output, sink and
AR/codec snapshots are separate allocations, not included in this buffer cap.
Two retained checkpoints contain136676608bytes of copied payload; constructing
a replacement transiently retains a third checkpoint. This is not peakVRAM,
process memory or a cheap device-side ring-buffer measurement. Intervened-group
median capture245.673ms, restore39.954ms; healthy snapshot capture529-560ms.
These synchronous diagnostic costs establish no TTFA, audible-onset or speedup.

Local research CTest24/24, new runner tests20/20; ordinary researchOFF CPU/shared
build, C ABI probe and6sampling/guard CTests pass. Engine exact-HEAD CI2/2 passed
at8ad3171. Model-free independent review found and corrected replay retirement,
seed75 zero-commit handling, cancelled-frame metadata, identity-test confounds
and failed-attempt evidence retention before GPU. Source APIs reuse existing
codec state-copy walkers and the normal AR/codec path, not another decoder.
New code is research-only orchestration/ownership and executable evidence
checks; no sampler, model algorithm, public ABI or production pin change.

The380-file local inventory covers all originals, candidates, negatives, step
replays, actual sink files, manifests, logs and numbered listening copies.
One folder: `.tmp/base-acceptance/eos-live-rollback-20261123/listening-live-rollback/`.
Seven WAVs include five candidates, one healthy and one failed original control;
README gives expected text and the method key stays outside the folder.
No evidence was removed and no human verdict is inferred from duration.

The demonstrated boundary is safe, bounded single-lane live rollback mechanics
on known inputs, including a nonzero irreversible commit. Still unqualified:
held-out texts/seeds and legitimate tiny replies, live risk detector, genuine
one-prefill dual fork, low-overhead checkpointing, Bridge worker orchestration,
multi-lane/compaction, physical playback/underruns, streaming timing, RTX4090
and release quality. Engine50/Bridge332 remain Draft; no merge/tag/release.
