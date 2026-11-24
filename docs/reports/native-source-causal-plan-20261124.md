# Matched-history native/source causal comparison

- Status: frozen before execution; bounded research, not speech acceptance.
- Date: 2026-11-24.
- Bridge base: `8ccdc515399b6c691a57566cad6098ce0b3e9174`.
- Native binary: retained Engine52 build `afa3df01417c90ff141dd54892eeb518d08580b0`,
  not the later source HEAD; SHA-256
  `6c86e4d69f0c0dbc26e35c360e0b6903dc976b0ad61aa3c34dbbaaa1bbe0f6fa`.

## Resumed execution amendment

The user authorized a new <=1800s window after the original enclosing window
expired during preparation. Preserve the original run001 preparation and its
not_run findings. Execute in new reference/source run002 directories, using
the versioned source runner `run_source_causal_v2.py` (SHA-256
`2486eafbf3ec02b85570d03b7bcbd7b38f545a9618c0fad2a4035b8fcb61b362`).
The coordinator starts one absolute monotonic deadline immediately before
reference extraction, serializes extraction, reference diagnostics/timings,
native dumps and then CPU source comparison, without resetting that deadline.
CPU source also has a600s inner watchdog; it does not overlap GPU timings.
The aggregate execution journal is repository-local
`.tmp/base-acceptance/reference-source-resumed-20261124/run-001/`.
Corpus files and the10-test source runner suite are frozen inputs. Verify the
actual nested/module eager attention path, not just a loader argument.

## Question and fixed boundary

Where do initial and early conditional Talker distributions diverge between
the exact local merged RU-stress checkpoint and its retained native Q8 GGUF?
Comparing the source on an already bad native history alone cannot explain
how that history arose. Compare the initial prompt, then every early decision
under identical complete 16-code histories, before comparing free trajectories.

Four cases are retained from the completed geometry experiment, unchanged:

| Label | Text | Language | Seed |
| --- | --- | --- | ---: |
| shortRU | `Ладно.` | russian | 2027 |
| shortEN | `All right.` | english | 2029 |
| longRU | `Сегодня мы проверили оборудование и записали результаты. Теперь можно спокойно завершить работу.` | russian | 2027 |
| longEN | `The equipment passed every check this morning. We can now finish the report and close the workshop.` | english | 2027 |

Use aligned full ICL, the unchanged full speaker embedding, reference transcript
and all 226 reference frames. No prefix cache, full-text geometry, top-1,
EOS guard, rollback, retry, seed search or reference replacement. Preserve the
Talker/Predictor stochastic sampler settings: temperature0.9, top-k50, top-p1,
Talker repetition1.05 and initial minimum2. No production defaults, ABI, QTB,
engine pin, package or release-status change; R1 remains NO-GO.

## Identities and interpretation

- Exact source checkpoint is existing legacy cache
  `.models/ru-stress-20261006/merged3/model.safetensors`, SHA-256
  `9742ba7f6ca86732875c4a910f8f60988183c525c84e99dd724f02424ee88fe0`.
  Its base/LoRA revisions and merge are recorded in
  [the conversion receipt](russian-stress-native-conversion.json).
- Native RU Q8 SHA-256
  `f4672741608d145fae169075cb0ec775a5382cbe9183eccb59c7ab9cc4797427`.
- Pinned cossim helper SHA-256
  `ac6c7de23cacab75c7c7a5317eda9994e3c19336832e56be3da9d0915852dca4`.
- Installed source `modeling_qwen3_tts.py` SHA-256
  `9c5b54d9435604c6cbfda0fbbaeb77d4c959b0f95592b00f40c507f5364ede38`;
  this is not asserted identical to the repository upstream checkout.
- Source runs CPU FP32/eager with Torch2.8.0+cpu, transformers4.57.3,
  safetensors0.8.0 and eight threads. No installs/downloads/model copies.

Source FP32 versus native Q8 is a checkpoint/quantization comparison, **not
equal-weight arithmetic parity**. A high-precision native control is not
available within the current disk budget; do not attribute a difference to
quantization versus native implementation from these two arms alone.

## Frozen sequence

1. After the coordinator grants exclusive CMP50HX GPU access, run exactly four
   native requests with tensor dumps, cap8frames, maxbatch1, deadline60s/request
   and total watchdog300s. Retain all dumps and verify complete code prefixes
   against corrected geometry run002, including both known short failures.
   A changed prefix is a reported diagnostic-path difference, not a repair.
2. Source reconstructs each identical text/reference prompt and uses the exact
   retained native speaker vector and reference codes. Compare token IDs,
   initial embeddings/overlays, initial raw logits, and early logits while
   forcing up to seven **complete** native 16-code frames. Keep raw and
   post-suppression/sampler quantities explicitly separate.
3. A forward-only control supplies exact native prefill and subsequent input
   embeddings to source Talker, isolating prompt/embedding construction from
   the conditional forward comparison. Compare raw logits under that input.
4. Separately run source free trajectories for the same four text/seed pairs,
   cap128newtokens. Retain complete codes and decisions, including failures.
   The pinned helper uses native Philox uniforms, but accumulation/order and
   distributions differ; equal seed does not imply equal RNG/trajectory or
   speech semantics. There is no claim that a longer code trajectory is speech.
5. Report the earliest supported divergence and unresolved alternatives; no
   forced-history result is presented as a free source synthesis success.

## Resource and artifact contract

Use the new repository-local payload tree
`.tmp/base-acceptance/native-source-causal-cmp50hx-20261124/run-001/`.
Keep prior geometry payloads frozen. The new runner/test files and plan are
hashed before execution; record model, helper, installed source, probe,
runtime DLL and conditioning identities before/after. GPU execution is only
under the coordinator's exclusive lease. CPU-only source work has a600s
owned-child watchdog. Preserve a512MiB disk reserve; cap new native payloads
at400MiB and source payloads at200MiB. Stop the owned process on a bound rather
than deleting old evidence. New diagnostic fragments are not listening files.
Tracked report owns the interpretation; local payloads alone do not update an
acceptance gate. No human-listening verdict or release qualification is added
by this numerical experiment.
