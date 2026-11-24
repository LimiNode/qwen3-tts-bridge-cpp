# Reference conditioning and native/source causal comparison

- Date: 2026-11-24. Research only; R1 remains **NO-GO**.
- Bridge base: `8ccdc515399b6c691a57566cad6098ce0b3e9174`.
- Full-text geometry is a completed negative experiment; do not repeat it.
- Freeze further rollback/snapshot development for this batch.

## Prior exact-head CI verified before this batch

| PR | Exact head | Completed successful checks | Disposition |
| --- | --- | --- | --- |
| Engine51 | `541f1f702e725dc002e0e9ebf6f1460dca8c3100` |2/2 | Separate production-candidate GPU smoke |
| Engine52 | `1416928594cb6fa9230afca8dd3116125c0d6fe0` |2/2 | Research only |
| Bridge331 | `09c10a1d6f67a7d3d76d43d0cb5db1d9b39779d1` |8/8 | Segmentation needs its own qualification |
| Bridge332 | `8ec5466c1f0ce011bc45719a28e96ffab41c9c15` |7/7 | Retain rollback/prefill research |
| Bridge333 | `8ccdc515399b6c691a57566cad6098ce0b3e9174` |7/7 | Completed negative full-text experiment |

Observed with `gh pr view --json headRefOid,isDraft,statusCheckRollup` on
2026-11-24. All five PRs remain Draft. CI does not imply hardware or listening
qualification, authorize merge, or change the production engine pin.

## Independent tracks and unchanged boundaries

1. Qualify Engine51 `541f1f702e725dc002e0e9ebf6f1460dca8c3100`
   separately against production master `130cb99af9ae12d554962fd0920e08fb4268af01`.
   Build real isolated ABI6 DLLs with no research macros. Exercise the
   existing21-case sampler graph contract on CUDA0, including N1/2/3,
   then compare four ordinary Base/full-ICL CLI requests and one repeat
   per engine. This is not N2/3 whole-model synthesis or release acceptance.
2. Retain full aligned ICL and unchanged sampler settings while varying
   contiguous reference PCM and speaker-vector origin. Reuse the previous
   exact original-reference A outcomes only after sealed identity checks.
3. Verify original RU-stress source provenance and compare initial prompt,
   embeddings and early Talker decisions. Compare forced complete16-codebook
   histories separately from free trajectories; identical seed is not an
   RNG-equivalence claim. High-precision native control is conditional on
   available resources, never silently replaced with Base.

No production default, Bridge gitlink, public ABI, QTB, model pin, frozen
package, merge, tag or release change is authorized by this batch. Engine51
gets a separate merge recommendation; research PRs remain research.

## Fixed reference experiment

Original source:17.6s Kraftwerk WAV, SHA256
`90e5f7576991ea5b9f0a85e9109f7bd31ff667c4a12d58783a06c650796c3ca1`.
Use exact PCM16 mono24kHz slices without normalization or synthesized audio:

| Fragment | Exact source range | Transcript |
| --- | --- | --- |
| Short,4.00s | samples0..95999,0.00–4.00s | `Я твой слуга, я твой работник.` |
| Medium,8.84s | samples96960..309119,4.04–12.88s | `Жёлтый луч мягко лёг на шестерёнки; внизу щёлкнуло реле, сверху загудел вентилятор.` |

Nonzero cut boundaries have at least100ms measured silence on either side;
offline CPU ASR confirms no lost initial/final word. The medium/full ASR
transcriptions differ in two endings from the user-confirmed full transcript;
preserve that discrepancy rather than treating ASR as a new human verdict.
Crop-only human listening remains not_run.

Retain the existing12000-sample trailing-zero preparation. Regenerate the
original226 reference frames and2048-value speaker vector using the existing
native extractor; require exact equality to the sealed retained latents
before crop synthesis. Short/medium expect56/116 frames. Decode all16 codebooks
without changing order and retain matching decoder reference context.

For both RU-stress and Base compare:

- A: original full ICL with original speaker, reused exact artifacts;
- B: each cropped reference/transcript/codes with original speaker;
- C: each cropped reference/transcript/codes with its own extracted speaker.

Use these four fixed inputs, without seed search:

| Text | Language | Seed |
| --- | --- | --- |
| `Ладно.` | russian |2027 |
| `All right.` | english |2029 |
| `Сегодня мы проверили оборудование и записали результаты. Теперь можно спокойно завершить работу.` | russian |2027 |
| `The equipment passed every check this morning. We can now finish the report and close the workshop.` | english |2027 |

Eight new conditioning cells,32 diagnostic attempts and64 observer-OFF
ordinary streaming attempts (two fixed cycles per cell). Capture initial/raw
logits, suppressed logits, sampler weights, actual uniform choices, complete
codes, prompt/reference lengths, raw PCM/WAV, EOS and exact identities.
Keep diagnostic times separate from first-PCM/prefill timing; first PCM is
not first audible speech. Timing code histories must match diagnostics and
same-mode repeats must reproduce. Unexpected extra attempts invalidate the
single-attempt comparison, not count as rescues.

## Resources, integrity and decision

Only CMP50HX `GPU-40361931-6cb5-ac58-a059-5ba3e70986fb`.
One serialized1800s GPU deadline for all tracks starts2026-11-24T06:15:20Z;
absolute machine-monotonic deadline3170194.937. Every owned child receives
only the remaining time. CPU source preparation may proceed independently.
Keep at least512MiB disk reserve plus bounded evidence. No new model download
or high-precision conversion without a separate sufficient-space check.

New payloads remain below `.tmp/base-acceptance/`; previous sealed runs,
WAVs, failures and weights remain untouched. Preserve transitive runners,
source/runtime/input hashes and all failed/not_run outputs. Canonical tracked
receipts own current status, not local payload metadata.

Prepare one small numbered listening selection, retaining the reference and
expected text. Deduplicate exact PCM without discarding the complete matrix.
Mark near-silent outputs explicitly; energy, duration or natural EOS alone
never prove text completeness. New voice similarity, artifacts and stress
need exact-artifact listening. No old verdict transfers to new audio.

Decide separately whether shorter conditioning improves known failures,
changes first PCM, or alters voice; whether source enters the same bad
trajectory; and whether Engine51 can be merged independently. Numerical
differences between Q8 and FP32 alone are not proof of an inference defect.

## Batch handoff, not completion of the research objective

Engine51 completed its isolated GPU smoke in63.494s; see the separate
[report](native-engine51-gpu-smoke-20261124.md) and canonical receipt.
Reference and native/source preparations completed, but their GPU allocations
were not reached before the absolute batch deadline. No reference extraction,
new AR case or new source forward is claimed. See the exact
[reference stopping boundary](native-reference-conditioning-20261124.md)
and [source preflight](native-source-causal-20261124.md). The enclosing window
includes coordination time; it is not1800s of actual GPU inference.

Before publication, all40 indexed receipts validate. The validator regression
suite runs18 tests:17pass and one optional JSON-Schema dependency check skipped.
The three new receipts also pass local artifact-byte/hash verification using
the primary checkout payload root, not the evidence worktree's absent `.tmp`.
`git diff --check` passes. No model/quality conclusion follows from these
documentation/preparation checks. Remaining GPU matrices need a new explicitly
bounded batch and new run identity; preserve the expired run as history.
