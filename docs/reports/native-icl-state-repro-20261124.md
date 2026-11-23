# Exact full-ICL state checks and preparation audit

Executed 2026-11-24 against the
[frozen plan](native-icl-state-repro-plan-20261124.md), following the
[conditioning expansion](native-short-conditioning-expansion-20261124.md).
Full-ICL voice cloning remains the target. No production source, model,
sampler/default, pin, ABI, QTB or release-package change. R1 remains NO-GO.

## Result and scope

All **five fresh-process requests** match their retained persistent-session
counterparts in actual complete16-code histories, matched buffered-decoder
f32 PCM, sampled decisions without timestamps, and frame/status/EOS outcome.
The comparison includes failed/near-silent outputs, not only usable speech.

| Fresh request | Seed | Historical group | Frames / duration | Complete codes / PCM / decisions |
| --- | --- | --- | --- | --- |
| RU-stress/full-ICL, Ладно. | 2027 | 1 | 2 /0.16s | exact |
| RU-stress/full-ICL, All right. | 2029 | 12 | 6 /0.48s | exact |
| Base/full-ICL, Ладно. | 2027 | 1 | 11 /0.88s | exact |
| Base/full-ICL, All right. | 2029 | 12 | 10 /0.80s | exact |
| RU-stress/speaker-only, English voice text | 2027 | 13 | 82 /6.56s | exact |

The English voice text is exactly: `The equipment passed every check this
morning. We can now finish the report and close the workshop.`

The historical empty Ладно. and tentative partial All right. therefore do
not require earlier requests in that session to reproduce. Likewise the
fresh voice-text PCM is byte-identical to historical file06, where the user
reported a mid-phrase voice change. This disconfirms preceding-queue state
as a necessary condition for **these exact outputs**; it does not exclude
every possible state defect, explain the model trajectory, or qualify a fix.

No cell differed, so all three conditional full15-request queue repetitions
were correctly **not_needed**, not counted as completed inference or missing
failed synthesis. The earlier RU-stress group1/group14 repeat also remains
byte-identical. We did not rerun a broader seed sweep or the old retry/reset
comparison.

## Execution identity and mechanical evidence

* Bridge pre-run HEAD `572de846e5577cf915104732375b7d226927a86d`, clean.
* Engine `4e47ed266f08cab9e13e277aa460a33bb607e769`, clean; ggml
  `c044c6f03892f9d5e98213b05f8afea1f8b0d3c9`.
* Existing isolated static probe SHA256
  `8bd699d6f12d31198e004ed82ef67a4d6aa515c6a361a52353e203d682abef5f`;
  no rebuild or local DLL override. Runtime DLLs reused in place.
* CMP50HX UUID `GPU-40361931-6cb5-ac58-a059-5ba3e70986fb`, SM7.5,
  driver581.94, CUDA13.3. No RTX4090/GTX1060 inference.
* Exactly5 flushed independent AR attempts, no fallback, snapshot, restore
  or PCM commit; one prefill per request, natural EOS for all five.
* **61.0seconds** including preflight/postflight identity checks, under the
  single1800-second deadline. This is not GPU utilization or a latency gain.
* Preflight free5291642880bytes versus required932446208, including512MiB
  reserve and worst-case conditional/failure output. No old evidence deleted.

Model/codec/reference identities are unchanged from the expansion. All
effective samplers match stochastic defaults: temperature0.9, top_k50,
top_p1, original repetition settings and min2. EOS guard, reseeding,
segmentation, frontend, prefix reuse and forced MMQ remain OFF. Capture uses
the existing buffered full-retry path with threshold1 only to retain complete
codes; its NOT-triggered guard passes in every request.

Assets, clean source, inputs, manifests, runner/imported helper sources,
actual reference and compared historical payloads match before/after.
Native logs identify the selected model/codec and sole visible CMP50HX;
this is not a loaded-module audit. The independent finalizer verifies native
group/lane/seed/attempt metadata and actual historical code/PCM bytes again.
All10 original/final f32-to-PCM16 mono24kHz conversions,426240samples,
match sample-for-sample without trimming/normalization. Nine model-free
driver tests pass, including scalar/missing/invalid attempt metadata,
guard changes, token changes and storage rejection before GPU launch.
All35 canonical receipts validate;17 validator regression tests pass with
one optional skip. Both new receipts also pass local artifact size/hash
checks. No engine build/CTest run is claimed for this unchanged-source reuse.

Payload root:
`.tmp/base-acceptance/icl-state-repro-cmp50hx-20261124/run-001/`.
The final inventory covers101 files/4391828bytes excluding itself; the
earlier pre-seal inventory is preserved. Executed runner/helpers, finalizer,
its transitive local sources and tests are preserved under
`evidence-tools/`. `plan-only-001/` is separate. Ignored payloads are not
transferred or backed up by Git. Separate tracked
[RU-stress](native-icl-state-repro-rustress-cmp50hx-20261124.json) and
[Base](native-icl-state-repro-base-cmp50hx-20261124.json) receipts identify
the exact current evidence without replacing earlier listening judgments.

## ICL preparation: established facts and limits

Independent read-only source/data audit and `preparation-audit.json` establish:

* `reference.txt` is nonempty and exactly equals the registry transcript,
  171 Unicode characters. Its semantic alignment with the actual WAV has
  **not** been independently assessed in this stage.
* The prepared codebook-major `[16,226]` int32 reference is exactly the
  integer conversion of the original retained `ref-codes.bin`; all values
  are integer codes in0..2046. The2048-value f32 speaker vector is exactly
  the original `spk-emb.bin`. This verifies transfer, not new extraction.
* The actual reference has422400 mono24kHz samples /17.6s. The documented
 12000-sample trailing silence gives
  `floor((422400 + 12000) / 1920) = 226`. No off-by-one was found here.
* Actual GGUF vocabulary151676, merges151291, token types, language tables
  and the selected text-special metadata have identical encoded payloads
  between Base and RU-stress. The read-only audit also found matching codec
  specials, including EOS2150 and language IDs RU2069/EN2050. There is no
  demonstrated tokenizer-contract mismatch between these two files.
* Historical Ладно. logs explicitly show `N_text=4`, `T_ctx=236`,
  `ref_T=226`; sampled c0 is1720 twice, then EOS2150 at step2. Input is not
  empty. EOS is permitted after the unchanged minimum2; no EOS guard is
  active in this experiment.

No confirmed preparation defect was found. This is **not** a declaration
that preparation/extraction/forward computation is fully correct.

### Source boundaries checked

At engine `4e47ed2`, `tests/eos_research_probe.cpp:620-629,718-725`
loads/passes reference codes and speaker data; `tests/run_eos_research.py:314-328`
exports the original dump without transposing codebooks.
`src/prompt-builder.h:210-264` sums the matching codebook embeddings.
The longer native reference wrapper uses `[3:-5]`; the shorter Python
wrapper uses `[3:-2]`, preserving the same intended text body. The wrapper
difference alone is not a demonstrated defect.

Native prefill clears KV (`src/talker-forward.h:1018`), uses positions
`n_past+i` (:694-705) and causal mask `k <= q_pos` (:709-726). Single
nonpadded upstream requests use all-ones attention and `cumsum-1` positions;
the three equal mrope axes agree structurally with the native NEOX collapse.
The native prompt-prefix cache is disabled for ICL/reference speaker
conditioning (`src/prompt-builder.h:589`). These are static consistency
checks, not runtime KV/logit parity.

The Python source inspected is `Qwen3-TTS-streaming`
`25cc5886a753035ac3ed9d4000440b2e842e5e56`,
`qwen_tts/core/models/modeling_qwen3_tts.py:2278-2329,2461-2467,2509-2521`
and `qwen_tts/inference/qwen3_tts_model.py:345-349`. No Python inference was
run and no new weights were downloaded.

## Most useful next comparison: keep full ICL, change only text geometry

Native full ICL currently implements aligned text/audio geometry, matching
upstream `generate_icl_prompt(non_streaming_mode=False)`
(`src/prompt-builder.h:671-743`). Native speaker-only instead uses a full-text
prefix (:649-669). Thus the speaker-only ablation changes **three** things:
AR reference, decoder reference availability, and text layout. Its good
short outputs do not establish which change matters.

The source checkpoint implementation also has
`non_streaming_mode=True`: it places the complete reference/request text
before reference codec embeddings, retaining full ICL and returning the same
trailing padding embedding. That alternate input geometry is not currently
represented by the native ICL path. The smallest next causal comparison is
an opt-in implementation of that geometry, holding reference, decoder,
checkpoint, text, seed and sampling fixed. Preserve existing aligned controls
and compare upstream where practical. The name describes **text conditioning**,
not a requirement to buffer all generated PCM; audio delivery must still be
qualified separately for streaming.

This is an investigation target, **not a tested fix**. Exact merged-checkpoint
runtime parity, extraction parity, transcript alignment and a training-specific
short-ICL contract remain unknown. Q8 native versus unquantized PyTorch is
not automatically arithmetic equivalence. Do not change production defaults
or remove ICL based on this audit.

## Listening and handoff

`comparison-exact/` contains the actual reference and all five new WAVs with
source/copy hashes in its selection manifest. New listening remains not_run;
the user has already assessed the byte-identical historical outputs in the
expansion receipt. There is no need to solicit a redundant listening pass to
establish a new improvement: **no new audio candidate was produced**.
The earlier empty-word/partial-word/voice-drift observations remain scoped
to their exact artifacts; positive Base words remain scoped too.

No successful EOS remedy, speech-quality improvement, speedup, streaming
qualification or release acceptance is claimed. Full-ICL remains the target;
Base+ICL remains a comparator, not an automatic replacement for RU-stress.
Draft PR332 and engine PR50 remain Draft; no merge, tag or release.
