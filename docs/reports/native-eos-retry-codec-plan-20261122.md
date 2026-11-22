# Full retry and streaming-codec state: bounded comparison plan

Status: frozen before model execution, 2026-11-22. Research only; supplements
the [staged recovery plan](native-eos-recovery-plan-20261122.md). User-positive
rollback1 discovery listening is not transferred to new artifacts.

Use only CMP50HX UUID `GPU-40361931-6cb5-ac58-a059-5ba3e70986fb`, unchanged
RU-stress Q8_0, original Q8_0 codec, Kraftwerk reference226 and exact original
126-byte text. All hashes/settings remain those of `matrix-001`. No frontend,
prefix reuse, EOS guard, sampler/default/ABI/pin, model or release changes.
All PRs stay Draft. No merge, tag or cleanup of evidence.

## Prespecified order and comparisons

1. New probe must pass model-free contracts. Freeze source, binary and runner
   identity, environment, inputs and asset hashes before execution.
2. Run14 retained streaming controls (seeds2/14/72/75/78/42/64, twice), then
   21 unchanged buffered replay pairs (boundaries0/1/2). Stop interpretation
   on any changed control or replay mismatch; preserve failed outputs.
3. Compare rollback1 and genuine full retry twice on all seven seeds:
   28groups. Repeat0 orders rollback/retry; repeat1 reverses that order for
   each seed. Alternate seed64 (65 for healthy64) is fixed, not selected by
   future duration/listening. Natural EOS<=8frames is only a discovery trigger.
   Full retry re-admits on the same loaded engine and recomputes prefill;
   it captures no AR snapshots. Restore frame=-1 distinguishes it from
   restoring boundary0. Both attempts share one monotonic60s group deadline.
   Admission/prefill is not interruptible; the same cancellation deadline is
   polled at frame boundaries, not a hard prefill timeout.
4. Independently compare original code/PCM to same-run replay originals,
   repeat byte equality and full-retry seed64 to a fresh buffered seed64
   original. Healthy controls must not intervene or change bytes. Compare
   actual group_total_ms, snapshot/restore, retry admission and prefill spans;
   no hypothetical snapshot-free speedup or streaming TTFA claim.
5. Teacher-force saved complete code histories into the existing private
   streaming codec: five matrix-001 rollback1 candidates and healthy64.
   Each saved frame-major AR input is explicitly transposed into codebook-major
   input, with both identities retained. This stage does not run AR generation.
   Prime the full226-frame reference through the production staging path.
   Compare unchanged snapshot restore, reset+reference/prefix reconstruction,
   complete f32 PCM and private persistent state tensors/absolute position.
   Compare a restored changed continuation against independently decoded full
   candidate with the same schedule, not merely copied retained-prefix bytes.
6. Test fixedT1 boundaries0/1/2 separately from production ramp boundaries0/1/3.
   Only actual call boundaries inside both histories' common complete-code
   prefix are eligible. Original2-frame seed75 therefore cannot supply
   boundary2 for a one-frame rollback. No fictitious frame2 ramp snapshot.
   Compare production-ramp original PCM to retained streaming controls.
   If it differs, report the qualification limit rather than silently changing
   chunk widths/tolerances until it matches.

One overall1800s budget includes all new GPU controls and codec probes;
600s per process. Run GPU work sequentially. Budget exhaustion leaves later
cells `not_run`; retain interrupted/failed runs. Disk preflight reserves
worst-case112 capped256-frame AR attempts (f32+WAV),32MiB logs,128MiB codec
payload and512MiB free reserve. Reuse existing DLLs/models in place, no copies.
All outputs use a new exclusive repository-local acceptance directory.

## Interpretation and handoff

All attempts, original/final codes, PCM, seeds and costs remain available.
New WAVs are unassessed until exact-file listening. Byte-identical copies may
be identified as such, but no general quality verdict transfers between modes.
The codec check is one-lane teacher forcing using existing device snapshots,
not an AR+codec fork, selection policy, commit buffer, multi-lane/compaction
test or live recovery. Host inspection copies invalidate timing claims.
Record the current result in tracked canonical receipts and project status.
R1 remains NO-GO. A production holdback/checkpoint ring, held-out detector,
genuine shared-prefill dual fork and RTX4090 remain separate later work.
