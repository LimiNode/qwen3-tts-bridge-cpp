# Exact full-ICL state reproducibility checks

Prespecified 2026-11-24 after the
[conditioning expansion](native-short-conditioning-expansion-20261124.md).
Research only; full-ICL cloning remains the target. No source-model, sampler,
production pin/default, ABI, QTB or frozen-package changes.

## First discriminating checks

Run five independent fresh processes using the unchanged static probe and
engine `4e47ed266f08cab9e13e277aa460a33bb607e769`:

| Cell | Exact input | Seed | Retained persistent group |
| --- | --- | --- | --- |
| RU-stress/full-ICL | Ладно. | 2027 | 1 |
| RU-stress/full-ICL | All right. | 2029 | 12 |
| Base/full-ICL | Ладно. | 2027 | 1 |
| Base/full-ICL | All right. | 2029 | 12 |
| RU-stress/speaker-only | The equipment passed every check this morning. We can now finish the report and close the workshop. | 2027 | 13 |

Compare actual complete16-code histories, matched buffered-decoder f32 PCM,
terminal status/frame count and sampled decisions without timestamps against
the exact retained expansion outputs. Rehash historical payloads before/after;
do not rely only on equality flags. Group1 already equals group14 in the old
session, so another identical persistent queue is conditional, not mandatory.

Only if a fresh result differs, repeat that cell's complete original15-request
order in a separate persistent process, without changing text, seed, sampler,
reference or decoder. Compare every repeated group with the old matching
group. At most three such conditional cells: RU-stress/full-ICL,
Base/full-ICL, RU-stress/speaker-only. Five initial requests, at most50 normal
requests in total. A mismatch is an observation, not a mechanical failure or
automatic proof of stale state; preserve all outcomes.

The fifth request tests the separate voice-drift observation in old file06.
Do not equate it with the full-ICL short-text failure. Speaker-only removes
both AR and decoder reference conditioning and changes prompt geometry;
its earlier successes do not localize the defect to the Talker.

## Unchanged controls and resource limits

Keep exact assets from the expansion plan, including the226-frame Kraftwerk
reference, the same2048-value speaker vector and the actual17.6-second WAV.
Use the full-retry capture path only with threshold1 and the original seed;
require NOT-triggered, one AR attempt/prefill, zero snapshot/restore/commit,
original/final complete codes/PCM equal. Preserve every short/quiet outcome.
The worst failure-path budget is100 attempts, not100 successful requests.

Only CMP50HX UUID `GPU-40361931-6cb5-ac58-a059-5ba3e70986fb` is allowed.
One1800-second deadline starts before identity preflight; per-request60000ms,
256-frame cap, process watchdog bounded by the remaining shared deadline.
Kill/reap owned children. Require worst-case output plus512MiB reserve before
launch. No model/DLL copies, deletion of old evidence, seed search, frontend,
segmentation, prefix reuse, EOS guard or sampler changes.

Validate flushed results as objects with positive integer attempt metadata;
missing/corrupt rows make accounting incomplete rather than defaulting to one.
Preserve the executed driver and imported helper sources. Hash source,
assets, inputs, manifests, helpers and retained compared evidence before/after.
Save all f32 and PCM16 WAV outputs; verify every conversion sample. Duration,
energy and natural EOS do not establish semantic success.

## Preparation audit and follow-up boundary

In parallel, inspect transcript/reference provenance, codebook/frame layout,
special IDs, prompt text slicing, masks/positions and RU-stress model contract.
Structural agreement is not numerical forward parity, semantic transcript
verification or proof of regenerated extraction equivalence. Do not conflate
the unchanged hashes with correct preparation.

If fresh and historical outputs agree, prioritize a fixed-input comparison of
full-ICL prompt geometry/native execution with the source checkpoint rather
than another seed sweep. Quantized native and unquantized upstream outputs
are not automatically arithmetic parity. Any alternate prompt path requires a
separate opt-in research change; do not promote it from this state check.

Payloads: `.tmp/base-acceptance/icl-state-repro-cmp50hx-20261124/` in exclusive
plan-only/execution children. Publish separate small tracked RU-stress/Base
receipts, index and status. New WAV listening starts not_run; prior judgments
remain attached to old artifacts even if bytes match. Draft PR332 stays Draft;
R1 NO-GO, no automatic fallback, merge, tag or release.
