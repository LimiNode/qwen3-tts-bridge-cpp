# Coherent live rollback and bounded PCM holdback

Status: frozen before model execution on 2026-11-23. Research only.
This executes stage4 of the [comparative recovery plan](native-eos-recovery-plan-20261122.md),
after exact buffered AR replay and separate streaming-codec restoration.
The earlier [retry/codec report](native-eos-retry-codec-20261122.md) remains
historical evidence; its listening verdicts do not transfer to new WAVs.

## Scope and identity

CMP50HX UUID `GPU-40361931-6cb5-ac58-a059-5ba3e70986fb` only; at most1800s
for the complete sequential stage, including controls and reconstruction.
Each logical request retains its original60s monotonic deadline. Keep all
failures and partial output. Budget exhaustion leaves later cases `not_run`.
No RTX4090, Bridge worker, public DLL, physical playback or package execution.
The opt-in static probe exercises engine-owned state and a probe-owned sink;
it is not implementation of Bridge production recovery orchestration.

Use the unchanged original RU-stress Q8_0 talker, original Q8_0 codec,
Kraftwerk speaker/226-frame reference/transcript, and exact126UTF8 spoken
bytes identified in the preceding report. Frontend, segmentation, prefix
reuse, scheduled reseeding and EOS guard remain OFF; stochastic sampling,
min2 and codec ramp1/2/4/8 remain unchanged. New plan.json records clean
source/submodule HEAD, static probe SHA256 and all model/runtime/input hashes
before GPU execution; verify them again afterward. Runtime DLLs are reused
in place. No model/runtime copies, downloads or cleanup of prior evidence.

## State and commit invariant

Capture only between completed engine steps, for one active lane and complete
AR frames0..8. A checkpoint independently owns Talker/Predictor KV, bridge,
host prompt/history/RNG and codec persistent tensors/position. It also saves
pending code rows, chunk target, lane mapping and live flag. The reference
snapshot LRU cannot own recovery checkpoints because it can evict entries.

An AR checkpoint at frame2 normally has decoded frame1 plus one pending
frame: AR frame and codec boundary are different quantities. Let D be the
saved decoded-sample cursor and C the current irreversible sink cursor.
Restore is allowed only if C<=D, preserving C and every committed byte.
Restore owned held PCM only from [C,D), then restore pending rows and codec
state. Reject stale checkpoints rather than retracting sent audio. The probe
copies callback PCM immediately; engine callback storage is reusable scratch.

Hold the newest ordinary codec chunk; the next ordinary callback commits
the previous held chunk. The bounded EOS observer freezes commits before
terminal drain; it never calls engine APIs. At most16frames of current held
PCM covers an8-frame chunk plus a7-frame terminal tail. Check capacity before
append. Saved held slices and the diagnostic sink are separate storage and
must not be misreported as part of that16-frame bound or physical playback.

Only successful natural EOS<=8frames triggers one rollback1 with the frozen
alternate seed64 (65 for healthy64). This is a discovery-only trigger, not
a qualified detector. Never retry cancellation, error or token-limit outcomes.
External cancellation/deadline remains current across restoration; no newer
admission, including an admitted-and-retired job, may reuse an old checkpoint.
No fresh retry is spliced after a nonzero commit.

## Ordered checks and stop rules

1. Model-free build/contracts: copying, bounded append, monotonic commits,
   partial/stale restore, terminal draining, cancellation/deadline, sink
   failure, and unsupported/null engine guards. Existing tests must pass.
2. Fourteen ordinary controls: seeds2/14/72/75/78/42/64 twice, compared with
   retained streaming full PCM and complete16-code histories. Fresh full
   streaming-codec reconstruction must also match actual PCM.
3. Fourteen unchanged live replays: checkpoint1/2 for every seed. Advance one
   complete engine step and restore unchanged RNG before continuing. Compare
   full codes/PCM against controls; frame2 cases exercise a nonzero1920-sample
   commit and saved pending frame, except seed75 whose EOS freezes commits
   at0 before terminal drain (retired-to-active replay). Mismatch blocks later
   intervention claims.
4. Explicit GPU negatives for cancellation, expired original deadline, buffer
   capacity, sink refusal, stale checkpoint and newer admission. Verify refusal
   without publishing late held PCM or rewinding committed output. The sink
   is an owned in-memory all-or-none test sink, not an arbitrary device API.
5. Seven rollback1 groups: five known early terminals plus two healthy controls.
   Capture a rolling last-two-checkpoint set, select original_frames-1 after
   natural EOS, restore coherent state and truncate only uncommitted PCM.
   Independently compare original bytes, committed prefix, retained complete
   code prefix and candidate PCM versus fresh full streaming-codec reconstruction.

All attempts retain exact seeds, frame/decoded/pending/commit boundaries,
finish reason, callback/commit observations, capture/restore cost and WAV/raw
artifacts. Freeze a worst-case disk allowance plus512MiB reserve before launch.
Times include diagnostic host copies and are not TTFA/speedup measurements.
Prepare one small numbered listening folder; new speech completeness and
quality remain unassessed until the exact files are heard.

## Disposition

Publish a tracked report/canonical receipt and update the acceptance index and
project status, including failures. Keep engine50 and Bridge332 Draft. No
merge/tag/release, production pin/ABI/default/package change. R1 remains NO-GO.
Mechanics success would permit further held-out/overhead/Bridge integration
work, not promotion of a detector, genuine fork or universal EOS remedy.
