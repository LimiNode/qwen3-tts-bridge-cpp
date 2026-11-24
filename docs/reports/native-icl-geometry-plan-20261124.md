# Frozen full-ICL geometry experiment

- Status: frozen before GPU execution; research only.
- Date: 2026-11-24.
- Engine candidate: `568bc48e0264f4a2c3ced6a5fb80cf308092e74a`, stacked on
  PR50 `4e47ed266f08cab9e13e277aa460a33bb607e769`; Engine51 is **not** integrated.
- Bridge research base: `8ec5466c1f0ce011bc45719a28e96ffab41c9c15` (PR332).
- Prior evidence: [conditioning expansion](native-short-conditioning-expansion-20261124.md)
  and [exact fresh-state controls](native-icl-state-repro-20261124.md).

## Question and fixed boundary

Does the upstream full-text ICL layout improve the two known short failures
while retaining complete reference conditioning and voice identity?
The reference transcript, speaker embedding, all226 reference frames and
decoder reference remain unchanged. There is no speaker-only fallback.

A is the existing aligned layout. B is enabled only in a research build by
`QWEN_ICL_FULL_TEXT=1`: projected `[reference text; request text; tts_eos]`
summed with codec-pad, then `[codec_bos; every reference frame]` summed with
tts-pad. The trailing text overlay becomes one tts-pad row. This matches
`generate_icl_prompt(non_streaming_mode=True)` at upstream
`25cc5886a753035ac3ed9d4000440b2e842e5e56`; it does not turn off PCM streaming.
The existing builder and unchanged projection/tokenization paths are reused.

The pure composition/position/mask helpers are covered by model-free tests
for shorter/equal/longer text, text/reference boundaries, complete reference
rows, trailing overlays, prefix canaries and causal visibility. These tests
do not establish model/forward parity; the A control must reproduce retained
complete codes and matched buffered PCM before interpreting B.

## Matrix frozen before execution

Four cells, in order: RU-stress/aligned, RU-stress/full-text, Base/aligned,
Base/full-text. Each phase uses its own loaded process per cell, with
sequential requests. No concurrent GPU inference.

| Order | Text | Language | Seed |
| --- | --- | --- | --- |
| 0 | `Ладно.` | russian | 2027 |
| 1 | `All right.` | english | 2029 |
| 2 | `Сегодня мы проверили оборудование и записали результаты. Теперь можно спокойно завершить работу.` | russian | 2027 |
| 3 | `The equipment passed every check this morning. We can now finish the report and close the workshop.` | english | 2027 |

Diagnostic phase: the four requests above, then repeat request0. Total20
requests. Profile/decision observation enabled, no tensor/layer dump. Preserve
initial unfiltered logits plus bounded post-sampler logits (first eight
selections and terminal EOS), sampled tokens, complete16-code histories,
raw f32 and PCM16 WAV. Negative infinity is valid in the filtered logit
vectors, not in initial model logits or PCM. The existing buffered full-retry
capture path uses threshold1 and the same continuation seed solely to retain
histories. Require one attempt/prefill, no trigger, snapshot, restore or
committed PCM. A trigger invalidates the planned single-attempt comparison;
retain its artifacts and stop, do not search for another seed.

Timing phase: repeat the same four-request schedule three times in each
cell. Total48 requests; decision/logit/profile observation OFF, ordinary
streamed chunks. Private complete-code capture is ON for equality checks;
its host copy occurs at retirement, not before first PCM. Retain first-use
separately from warm requests. Compare identical texts/seeds by pair; the
small pooled p50/p95 is descriptive, not a broad performance claim. Buffered
and streamed PCM are **not** compared as a decoder-equivalence claim.

All68 intended requests and any failure-path extra attempt remain counted.
No post-result seed selection. Diagnostic20 can reach at most40 attempts
only if forbidden capture plumbing triggers; those runs are invalid, not
rescued successes. Timing48 has no retry. Every missing outcome is not_run
or failed, never an invented one-attempt pass.

## Identity, resources and preservation

- CMP50HX only, UUID `GPU-40361931-6cb5-ac58-a059-5ba3e70986fb`.
- Single1800-second deadline starts before identity preflight; child watchdogs
  use remaining time. Request deadline60000ms; frame cap256; chunk cap8.
- RU-stress Q8 SHA256 `f4672741608d145fae169075cb0ec775a5382cbe9183eccb59c7ab9cc4797427`.
- Base Q8 SHA256 `4b9a33a236908dd9435a42f7a396e38038329d053b704342a6413c08544c4fda`.
- Codec Q8 SHA256 `1883beeed99348fc35e23dd225e9082f93f6f8c109330a33d935baa8acdbfd94`.
- Same retained2048-float speaker,16x226 codes and transcript as the prior
  expansion; exact input hashes and runtime DLL identities in machine plan.
- Source reference WAV SHA256
  `90e5f7576991ea5b9f0a85e9109f7bd31ff667c4a12d58783a06c650796c3ca1`;
  user confirmed its spoken text matches the transcript. No new extraction.
- Stochastic Talker/Predictor defaults unchanged: temperature0.9, top_k50,
  top_p1, Talker repetition1.05, Predictor repetition1, minimum2.
  EOS guard, frontend, segmentation, prefix reuse, forced MMQ and reseeding OFF.
- Isolated static probe rebuilt from the candidate C++ sources using MSVC
  Release and existing GGML `c044c6f` import libraries/runtime. Not a new
  production DLL/package build. Build recipe and logs retained locally.
- New payload only under `.tmp/base-acceptance/icl-geometry-cmp50hx-20261124/`;
  build `.build/icl-geometry-engine/`. Recheck worst-case storage plus512MiB
  reserve. Preserve previous WAVs, models, failed runs and frozen R1 package.
- Copy runner/transitive tools and hashes into the payload; record exact
  clean engine/Bridge HEAD, probe SHA, inputs and runtime before/after.

## Decision and non-goals

One numbered folder contains source reference00 and16 A/B outputs at original
levels, with exact expected texts. New listening remains **not_run** until
the user assesses complete words, extra sounds and voice stability/similarity
independently. Natural EOS, duration, nonzero energy or longer output cannot
establish improvement. Mechanical repeatability and semantic acceptance are
separate. Do not transfer earlier listening verdicts to new WAVs.

Publish a research report and separate model receipts. Positive listening
would justify broader qualification, not a universal EOS remedy. Negative
results close or narrow this layout hypothesis; do not add another recovery
framework. Engine51 independent review remains separate. No production
default, Bridge gitlink, public ABI, QTB, sampler, model pin, release package,
merge or tag change. R1 remains **NO-GO**.
