# Full-ICL text geometry: CMP 50HX comparison

- Status: completed bounded research; new listening **not_run**; no promotion.
- Date: 2026-11-24.
- Frozen [plan](native-icl-geometry-plan-20261124.md).
- Canonical receipts: [RU-stress](native-icl-geometry-rustress-cmp50hx-20261124.json)
  and [Base](native-icl-geometry-base-cmp50hx-20261124.json).

## Decision

Full-text ICL is **not a remedy for the tested RU-stress short failures**.
It retains near-silent `Ладно.`/2027, makes `All right.`/2029 near-silent,
and produces only three frames for the long Russian voice control.
It also increases warm first-PCM latency from about 178 ms to231 ms here.
Do not promote this layout, remove ICL, change the sampler or deploy an
automatic retry policy from this result. Keep the opt-in experiment for review.

This rules against the specific claim that changing only this text layout
removes these failures. It does not identify the checkpoint/native-forward
root cause or prove that full-text ICL is universally unsuitable. Base is a
scoped comparator, not a qualified replacement. Actual words, extra sounds
and voice identity in new outputs remain unassessed until listening.

## Implementation and identities

The existing prompt builder reuses the same tokenization, text projections,
speaker vector, reference codes and decoder conditioning. Only research builds
(`QWEN_RESEARCH_PREFILL=ON`) read the opt-in `QWEN_ICL_FULL_TEXT=1` switch.
Unset/0 retains the aligned layout.

The full-text branch follows upstream
`generate_icl_prompt(non_streaming_mode=True)` at
`25cc5886a753035ac3ed9d4000440b2e842e5e56`:

1. `[reference text; request text; tts_eos]` summed with codec-pad.
2. `[codec_bos; every reference audio frame]` summed with tts-pad.
3. One trailing tts-pad overlay during generation.

This is prompt composition, not a request to disable streamed PCM. No second
builder, cache or public API was added. Shared pure helpers cover stream
composition, positions and causal masks; the existing aligned computation
uses those same helpers without changing its arithmetic.

The built GPU engine is `afa3df01417c90ff141dd54892eeb518d08580b0`, based on
Engine50 `4e47ed266f08cab9e13e277aa460a33bb607e769`. The source/plan Bridge
HEAD is `ac53416984bc436cf178791e760d478cd50f3f77`, stacked on Bridge332
`8ec5466c1f0ce011bc45719a28e96ffab41c9c15`. Probe SHA-256:
`6c86e4d69f0c0dbc26e35c360e0b6903dc976b0ad61aa3c34dbbaaa1bbe0f6fa`.
Later CI/evidence-only edits must not be described as the built GPU revision.
Engine [PR52](https://github.com/LimiNode/qwentts.cpp/pull/52), HEAD
`a4b74bdbacc9b1c9f65cce99efc21641fdcc022e`, subsequently adds the geometry test to both CI jobs and
preserves original-attempt logit/weight files before a possible full retry.
The latter has a model-free overwrite/bounds regression and a separately
rebuilt probe self-test; no new hardware run is claimed for that HEAD.

The isolated static probe was rebuilt with MSVC14.44, C++17, Release,
existing GGML `c044c6f03892f9d5e98213b05f8afea1f8b0d3c9` import libraries and
the retained CPU/CUDA runtime. No new production DLL, worker or package was
built. The build retains an existing C4244 warning in snapshot frame-policy
code; the entire engine compile is not claimed warning-free.

Only CMP50HX UUID `GPU-40361931-6cb5-ac58-a059-5ba3e70986fb` was used:
SM7.5,20GB, driver581.94, CUDA13.3. Model, codec, runtime DLL, probe and input
hashes are recorded before/after in the executed plan and canonical receipts.
All source/assets/inputs/manifests were unchanged through the run.

Full ICL is retained in both arms: the same 2048-float speaker vector, all
16x226 reference codes, nonempty reference transcript and decoder reference.
The original 17.6 s Kraftwerk WAV has SHA-256
`90e5f7576991ea5b9f0a85e9109f7bd31ff667c4a12d58783a06c650796c3ca1`.
The user previously confirmed its spoken text matches the transcript. No new
extraction or numerical upstream parity is claimed. Keeping conditioning
inputs is distinct from proving the generated voice stayed identical.

## Fixed matrix and preservation

Four cells: RU-stress/aligned, RU-stress/full-text, Base/aligned,
Base/full-text. Each cell uses a separately loaded process and sequential
requests, without concurrent GPU inference. Four frozen text/seed pairs:

| Label | Text | Language | Seed |
| --- | --- | --- | --- |
| shortRU | `Ладно.` | russian | 2027 |
| shortEN | `All right.` | english | 2029 |
| longRU | `Сегодня мы проверили оборудование и записали результаты. Теперь можно спокойно завершить работу.` | russian | 2027 |
| longEN | `The equipment passed every check this morning. We can now finish the report and close the workshop.` | english | 2027 |

Each diagnostic cell runs these four then repeats shortRU:20 requests total.
Observers/profile enabled; no tensor/layer dumps. Buffered full-retry capture
plumbing has threshold 1, never triggers, and retains histories only. Every
request has exactly one attempt/prefill, no snapshot/restore/PCM commit.
Every aligned control matches retained complete codes and buffered PCM before
interpreting full-text. There was no search for successful seeds.

Each timing cell runs the four-case schedule three times:48 requests total,
ordinary streaming, observers/profile OFF. Complete codes are copied at
retirement, not before first PCM. All streamed codes equal the diagnostic
case codes. Same-mode repeats are exact; buffered and streamed PCM are not
asserted equivalent across decoder modes.

Corrected run002 completed68/68 attempts in179.453 s. The shared stage,
including run001 and the intervening correction, consumed629.140 s of the
approved1800 s budget. Limits were256 frames,60000 ms/request,8-frame chunk cap,
owned-process watchdog and512MiB storage reserve. No existing files/models/
WAVs were deleted. All attempts, including short and silent ones, remain.

## Observed results

Frames before natural EOS, in frozen text order:

| Checkpoint/layout | shortRU | shortEN | longRU | longEN |
| --- | ---: | ---: | ---: | ---: |
| RU-stress/aligned | 2 | 6 | 99 | 78 |
| RU-stress/full-text | 2 | 2 | 3 | 91 |
| Base/aligned | 11 | 10 | 92 | 86 |
| Base/full-text | 11 | 9 | 92 | 90 |

Repeated shortRU outcomes match exactly. All requests mechanically complete
with natural EOS and valid finite PCM. This does **not** establish semantic
success. RU aligned shortRU and RU full-text shortRU/shortEN have PCM16 peak
only 1 LSB. RU full-text longRU is 0.24 s, peak 837 LSB, RMS 0.000725: not classified
near-silent by the frozen proxy, but plainly a suspiciously short candidate
for this input. No Base output crosses that proxy; that is not listening.

Aligned context has 236 positions and a256-position padded KV window. Full-text
has 318/317/338/333 positions, with 512-position padded windows. Layout changes
positions and attention-visible sequence, so numerical/output equality between
A and B is neither expected nor used as an acceptance criterion.

## Corrected EOS evidence

The first run completed the same 68 requests. Post-run inspection found a
diagnostic error: `sample_top_k_p_with_uniform` overwrites its input with
unnormalized `exp(logit-max)` weights. The first observer recorded those as
decision-logits and the first finalizer applied softmax again. **Run001 derived
EOS probabilities are invalid.** Its original prefill logits, decisions,
complete codes, PCM and timings remain valid. The sealed directory/inventory
is preserved unchanged, including the invalid interpretation, not silently
replaced. Its inventory SHA-256 is
`6d8d426984500b936eb6bc40d5fb264d53a1314ad748c4a34448e797a270d34e`.

The corrected engine copies suppressed pre-sampler logits separately from
post-chain exponential weights and retains the original uniform draw and
subsequence. The sampler calculation is unchanged. The same matrix was
repeated as run002. All68 complete-code histories and matched-mode raw PCM
files equal run001 byte for byte: instrumentation did not repair the speech.

For all 143 captured selections (first eight plus terminal EOS), normalizing
weights **once** and replaying the saved F32 categorical CDF reproduces the
sampled token exactly. An independent audit additionally rounds the serialized
uniform explicitly to F32; all 143 selections and probabilities still match.
These probabilities describe the post-suppression/top-k/temperature sampler
distribution, not unfiltered model probabilities or future speech completeness.

| RU-stress case | Aligned EOS frame / probability | Full-text EOS frame / probability |
| --- | ---: | ---: |
| shortRU | 2 / 98.8985% | 2 / 98.8635% |
| shortEN | 6 / 99.7981% | 2 / 41.1918% |
| longRU | 99 / 99.5128% | 3 / 99.1918% |

Thus these terminal choices are reproduced by the saved categorical inputs;
they are not a WAV writer truncation or forced EOS. In particular, high EOS
weight is already present at the bad RU shortRU terminal decision. Why the
native conditional forward distribution reaches those weights is unresolved.
This is not proof of an upstream model defect or native arithmetic parity.

## First-PCM latency, without diagnostic observers

Milliseconds from admission start; first-use is separated. Each warm pool
contains11 requests; same-text repeats contain8. Small descriptive sample,
fixed order, no confidence interval or broad performance claim:

| Cell | First-use | Warm 11 p50 / p95 | Same-text 8 p50 / p95 |
| --- | ---: | ---: | ---: |
| RU-stress/aligned | 1552.495 | 178.577 / 190.760 | 178.399 / 179.381 |
| RU-stress/full-text | 1574.970 | 231.541 / 260.406 | 231.498 / 255.830 |
| Base/aligned | 1532.307 | 178.144 / 189.902 | 178.018 / 178.602 |
| Base/full-text | 1613.761 | 231.846 / 260.977 | 231.419 / 256.155 |

Full-text is about 53 ms slower here, not an acceleration. The longer context
and larger padded window accompany that result; this run does not apportion
their separate costs. First PCM can itself be silent and is not first audible
speech, a detector decision, physical playback or an end-to-end worker metric.

## Verification and exact local evidence

- Model-free geometry/settings C++ contracts pass under MSVC C++17 `/W4 /WX`:
  shorter/equal/longer streams, boundaries, prefix/end canaries, every reference
  row, trailing overlays, positions, masks and first generated position.
- The research probe observer `--self-test` passes without model loading.
- Eleven local runner tests and `py_compile` pass, covering the fixed matrix,
  identity/storage preflight, environment isolation, attempt accounting,
  PCM/logit separation, bounds/finiteness and distinct exp-weight semantics.
- Independent read-only audit verifies all 421 inventory hashes,68 repeated
  code/PCM pairs,143categorical draws and88 exact raw-to-WAV conversions,
  totaling6,666,240 samples. All16 listening copies retain original levels.
- The new geometry target/test is added to both Linux/CPU and Windows research
  CI jobs. Local manual builds are not a full CMake/CTest qualification.
- Bridge332 exact HEAD 8ec5466c has 7/7 successful CI checks, independently
  rechecked on2026-11-24. That success is not the new branch's CI status.
- All37 canonical receipts pass validation; the validator suite runs18 tests,
  17 passed/1 optional schema test skipped. Both new receipts also pass local
  artifact-size/SHA-256 checks against the primary checkout's payload root.

Payload root (ignored/local only):
`.tmp/base-acceptance/icl-geometry-cmp50hx-20261124/run-002/`.
It contains plan/results, manifests, complete codes, initial logits,
suppressed decision logits, sampler weights, decisions, raw PCM, WAVs,
runtime/source identities, build/runner/transitive-tool copies and the
independent audit. Inventory covers421 files/50,787,749 bytes excluding itself;
inventory SHA-256:
`e8e5b81f70d52b72525cf8e8908263cdd1463da041e89ebfb543645187e879d8`.
Ignored payloads are not transferred or backed up by Git.

## One listening folder and remaining boundary

Use only
`.tmp/base-acceptance/icl-geometry-cmp50hx-20261124/run-002/listening-icl-geometry/`.
It contains00 reference and16 numbered outputs, with expected text in README.txt.
Aligned/full-text pairs:01/05,02/06,03/07,04/08 and09/13,10/14,11/15,12/16.
01/05/06 are measured near-silent;07 is the suspicious0.24 s longRU result.
Do not normalize or count length/energy as success. Assess full words, extra
sounds, stable voice and similarity to00 independently; all new verdicts are
currently **not_run**. Earlier positive/negative listening stays attached to
its own historical artifacts.

Engine51 was [independently reviewed](native-engine51-independent-review-20261124.md)
at 541f1f70: exact-head CI 2/2 and21/21 focused CPU graph regressions pass;
the new tests fail against130cb99. No blocking changed-code defect was found.
This is not speech/GPU qualification; Engine51 is **not integrated** here.

Quality review: prompt composition and masks reuse one model-free owner,
not a parallel builder. Diagnostic buffers are bounded and allocated before
callbacks; borrowed pointers are deep-copied and cleared. One shared writer
retains actual original/final decision rows without serializing unused
capacity. No cache, public API, new dependency or speculative recovery policy
is introduced. Existing probe orchestration remains a separate historical
large-file boundary, not a new framework in this experiment.

The next discriminating technical question is matched-history native/upstream
forward behavior with exact prompt tensors, rather than more layout switches
or snapshot optimization. Quantization, reference extraction and kernel
differences must be isolated before attributing the cause. That new GPU study
is outside the completed matrix.
Production engine pin 130cb99, ABI6, QTB, sampler/model defaults and frozen R1
package remain unchanged. No merge/tag/release. R1 remains **NO-GO**.
