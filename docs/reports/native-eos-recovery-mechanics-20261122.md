# Early-EOS recovery: verified buffered replay and first intervention matrix

Recorded 2026-11-22. **Research only; R1 remains NO-GO.** This is the first
executed mechanics stage of the [frozen plan](native-eos-recovery-plan-20261122.md),
not the full comparative recovery assignment. The earlier
[disk refusal](native-eos-recovery-preflight-20261122.md) remains historical;
the user freed space, and a new exclusive `matrix-001` completed normally.
No evidence, runtime or model was removed by this task.

The indexed [canonical receipt](native-eos-recovery-cmp50hx-20261122.json)
owns current acceptance status. Raw evidence is local under
`.tmp/base-acceptance/eos-recovery-20261122/`, not transferred by Git.

## Identity and execution boundary

| Component | Exact identity |
| --- | --- |
| GPU | CMP 50HX, `GPU-40361931-6cb5-ac58-a059-5ba3e70986fb`, driver581.94, CUDA13.3 |
| Bridge report checkout before run | `f3d76de86c36e7ba6269555cd532562a8d158f7e`; Bridge itself was not executed |
| Engine runner checkout | clean `b16d8af6c365e9deb0fd503df9a695c1092ad4f4` |
| Native probe build source | `382e20a3fd52d341820d35f6ea5a2d5c23d42447`; subsequent runner/tests/CI changes do not change native source |
| Static-core probe SHA-256 | `ef53929578325efba9c74028997adbb8ee486c3470ef108ba462505deaf94435` |
| GGML | `c044c6f03892f9d5e98213b05f8afea1f8b0d3c9`; existing runtime DLL hashes in plan/results |
| RU-stress Q8_0 | `f4672741608d145fae169075cb0ec775a5382cbe9183eccb59c7ab9cc4797427` |
| Original Q8_0 codec | `1883beeed99348fc35e23dd225e9082f93f6f8c109330a33d935baa8acdbfd94` |
| Frozen plan SHA-256 | `56b43b54d740e04c10d74dfca4a21c72d44412667f82c49ff8bae3820f1c93dd` |

Kraftwerk speaker/reference tensors and the exact 226-frame reference
transcript retain their original hashes. The spoken UTF-8 text (126bytes,
SHA-256 `d917e809733280d0fcc4603828e8253593839a22e29161216868f18ef4ba8a5e`):

> МГУ находится в Москве. Инженер проверил USB-порт, GPS и новый процессор.

Frontend, segmentation, prefix-KV and EOS guard OFF; initial minimum2frames,
default stochastic Talker/Predictor and baseline seed schedule unchanged.
Limit256frames, 60s per logical original+continuation, 600s per process,
1800s overall. The final plan records15,665,684,480free bytes versus
859,439,104required. Probe logs span approximately00:20:01–00:22:32UTC;
final result was written00:22:47UTC, far below the30minute budget. This is
wall-clock provenance, not a GPU-utilization or inference-latency measurement.
No further GPU batch was launched. Models, probe and runtime hashes match
before/after; no interrupted or missing groups. This does not execute the
Bridge worker, public DLL API or portable package.

## Correctness gates

1. **14/14 streaming controls** match retained frame counts, natural EOS and
   f32PCM SHA-256, twice for seeds2/14/72/75/78/42/64.
2. **21/21 unchanged replay pairs** match every complete16-code frame and
   f32PCM byte-for-byte, restoring boundaries0/1/2 without another prefill.
3. **21/21 intervention groups** are mechanically valid:15 interventions
   and6 healthy controls. All actual seeds, trigger/restore boundaries,
   finite PCM, code sizes/ranges and unchanged code prefixes were checked.

Independent read-only audit checked actual files, not just probe flags.
Every buffered original full-code history is stable across the42 replay/
recovery groups; captured original Talker decisions match retained streaming
observations. However, **0/42 buffered-original PCM files equal streaming PCM**.
Exact within-buffer replay therefore does not establish streaming-codec parity.

## Intervention results, not semantic success rates

Each early case uses continuation seed64. The threshold naturalEOS at8frames
or fewer is a discovery trigger for this sentence, not a qualified detector
for arbitrary short replies. Every final outcome below is naturalEOS.

| Original seed | Original frames | EOS resample | Rollback1 | Rollback2 |
| --- | --- | --- | --- | --- |
| 2 | 3 | 3 | 87 | 87 |
| 14 | 3 | 3 | 104 | 2 |
| 72 | 6 | 6 | 71 | 84 |
| 75 | 2 | 94 | 85 | 84 |
| 78 | 3 | 97 | 86 | 85 |

Thus current-decision resampling lengthens2/5 known failures, rollback1
lengthens5/5, and rollback2 lengthens4/5. Rollback2 is not monotonically
better: seed14 instead ends at2frames. Seed42/64 healthy controls remain
101/84frames with no intervention and identical original/final codes/PCM.
These are selected discovery examples, not held-out samples or estimated
general recovery rates. **Longer does not mean complete speech**; every new
candidate remains unassessed on listening and requested-text coverage.

Captured code prefixes before the restored boundary are unchanged. This is
not enough for audio splicing: in the offline byte comparison, all11
trajectory-changing interventions with a nonempty retained prefix also
change PCM within that prefix after whole-sequence codec redecode. The three
unchanged EOS-resample results preserve PCM, and rollback2/seed75 has an
empty prefix. No PCM had been committed (`committed_samples=0`).

## Cost and interpretation

Across replay/recovery groups, summed synchronous snapshot capture costs
166.3–515.1ms per original attempt; each actual restoration costs36.4–42.2ms.
Host copies of device payload retain178,151,424–534,454,272bytes per group.
Even healthy non-intervened recovery controls pay roughly506–515ms capture
cost. This diagnostic implementation is **not a cheap production policy**.
These spans include host/device copies and are neither kernel-only timings,
peak VRAM/process-memory observations nor streaming TTFA. Empty chunk lists
and `streaming_qualified=false` are deliberate. No first-chunk improvement
is claimed. An optimized bounded device-side snapshot/ring buffer is a new
experiment, not a result of this run.

The supported causal boundary is narrower: retaining the exact AR state and
changing the continuation trajectory one frame before EOS can escape all
five demonstrated short endings in this matrix. Neither the original forward
arithmetic nor the general root cause of early EOS was established defective.
Later intervention is insufficient for three cases; more rollback can also
fail. The live commit boundary and codec state remain the major next boundary.

## Listening handoff and next slice

One folder: `.tmp/base-acceptance/eos-recovery-20261122/listening-recovery/`.
It contains17 numbered WAVs, the exact expected text in `README.md`, and a
hash manifest. All15 intervention candidates on the five seeds are included,
including short failures, plus two controls. The fixed method/seed mapping
is outside that folder in `listening-key.json`; copies are byte-identical.
No new WAV is marked listened. Existing positive seed2/14 switch-after1/2
observations are preserved and do not transfer to these new artifacts.

Next: record scoped listening for these exact WAVs; compare a bounded full
retry; then establish codec-state restoration and an irreversible streaming
commit buffer before a genuine shared-prefill dual fork. Selection must use
only information available before commit. Never splice the current buffered
PCM prefixes into an audible stream. Independent seeds/texts, legitimate
short replies, held-out quality, risk detector/combinations, physical playback,
real streaming latency and RTX4090 are **not_run**.

All research PRs remain Draft; no merge, pin, ABI, sampler-default, frozen
package or release change. Production engine pin remains
`130cb99af9ae12d554962fd0920e08fb4268af01`. The existing independent sampler
corrective remains a separate review unit, not permission to promote recovery.
