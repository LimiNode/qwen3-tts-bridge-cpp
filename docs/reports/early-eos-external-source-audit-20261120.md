# Early-EOS external-source audit and reference feasibility

Date: 2026-11-20. This is a source/read-only provenance audit, not a new
hardware acceptance run. No model, runtime, sampling default, dependency pin,
ABI or frozen R1 payload was changed. R1 remains **NO-GO**.

## Scope and conclusion

The comparison baseline is Bridge
`aa2770ec8aeb45d59f42c96c3a1f4f2dc52390d8` and
`LimiNode/qwentts.cpp@130cb99af9ae12d554962fd0920e08fb4268af01`, ABI 6.
The seeded CMP 50HX evidence belongs to
[PR #330](https://github.com/LimiNode/qwen3-tts-bridge-cpp/pull/330), evidence
HEAD `4dc9c38e24fdf0d65cbb0860042854b7670309b0`; it was not regenerated here.

None of the inspected external changes proves a fix for our seed-2/14
three-frame, 0.24-second trajectory. The useful transferable mechanisms are
terminal-result validation, bounded attempts and explicit partial-output
failure. They are not substitutes for a same-history forward comparison.
Identical merged RU-stress source weights are locally available and their hash
was verified, so the source-checkpoint comparison is feasible without a model
download. The subsequent bounded
[source-checkpoint probe](early-eos-source-checkpoint-probe-20261120.md)
reproduces an EOS-dominant bad-prefix state in FP32 CPU/SDPA; it is a separate
experiment, not strict equal-weight native/source arithmetic parity.

## Independently checked references

| Reference and frozen revision | Mechanism and inspected location | Applicability to the pinned native route |
| --- | --- | --- |
| [QwenLM/Qwen3-TTS #55](https://github.com/QwenLM/Qwen3-TTS/issues/55) | Japanese/Korean incomplete final-word report; [Russian comment](https://github.com/QwenLM/Qwen3-TTS/issues/55#issuecomment-3795212030). The issue is closed `not_planned` by `github-actions[bot]`, not closed with a verified corrective patch. | Corroborates reported symptoms in another stack, not their cause. It does not establish equivalence to a three-frame failure or validate our native forward. No ABI relevance. |
| [mlx-audio d2d02bf36148d68198fb3d314d65c4d4f5340752](https://github.com/Neywa-Labs/mlx-audio/commit/d2d02bf36148d68198fb3d314d65c4d4f5340752) | `_sample_token` and `_sample_token_batch` in `mlx_audio/tts/models/qwen3_tts/qwen3_tts.py`: remove pre-filter EOS-logit capture and post-top-k/top-p restoration; remove `eos_token_id` arguments at callers. Adds filter-bypass regressions. | Real sampler bug, but absent in local `src/sampling.h:202`: EOS has no post-filter exemption. Our saved seed-2 step-3 EOS is already raw rank 1, final probability about 0.9059, so removing an exemption cannot exclude it. Python/MLX patch, not a C-ABI patch to cherry-pick. |
| [vLLM-Omni #6728](https://github.com/vllm-project/vllm-omni/pull/6728), head `6ffdf1a8f1e47b01159b73b4cdd4c037e757dbba`, merged as `3adee400a03454d483a7c07018f4c65a5b8ab8f9` | `tts_adapters/qwen3_tts.py::apply_sampling_overrides/validate_generation` and `serving_speech.py::create_speech`: preserve actual stage-0 finish reason; reject `length`, default Base ceiling `min(configured, max(192, 12 * text_tokens))`; non-streaming retry once only without explicit seed or token limit. Streaming reports failure; structured routes flag already-emitted audio for discard. | Handles **missing/late EOS**, not early natural EOS. The text-scaled ceiling is not our premature-EOS detector. Result validation, explicit-control preservation and bounded retry are useful patterns. Its HTTP/SSE/WebSocket fields are not additions to QTB, nor a reason to expand our protocol/ABI. |
| [jinhwan000/qwen3-tts-1.7b-base-ov](https://huggingface.co/jinhwan000/qwen3-tts-1.7b-base-ov/tree/24de885d331b99dd987ddb82c6bee6be3f6359dd), revision `24de885d331b99dd987ddb82c6bee6be3f6359dd` | Pinned README, “Sentence ends (ICL clone, Korean)”: decoder trails Talker by three frames; at EOS, loud final 80 ms (RMS above -35 dBFS) triggers three-frame rewind and new sampling, up to two retries, retaining the quietest ending if none pass. Requires KV-length, input-row, repetition-mask and decoder-state restoration. | Addresses truncated **tails**, not established silent/early-prefix failure. It adds three rounds before first audio; reported latency table excludes that protection. The README/model repository ships IR parts, not the described C++/C# rewind scheduler source; this audit verified the documented algorithm, not that implementation. RMS alone is not evidence of text coverage. OpenVINO IR and scheduler are not ABI-6 drop-ins. |
| Official Qwen3-TTS `022e286b98fbec7e1e916cb940cdf532cd9f488e` | [`modeling_qwen3_tts.py:2044`](https://github.com/QwenLM/Qwen3-TTS/blob/022e286b98fbec7e1e916cb940cdf532cd9f488e/qwen_tts/core/models/modeling_qwen3_tts.py#L2044): `min_new_tokens=2`, normal sampling parameters, configured codec EOS; reserved codec IDs suppressed except EOS. | Confirms the source intent of local initial two-step EOS masking. It does not specify a text-completeness test or justify lengthening the minimum indiscriminately. Source inspection, not an installed-version inference/parity result. |
| [`LimiNode/qwentts.cpp`](https://github.com/LimiNode/qwentts.cpp/tree/130cb99af9ae12d554962fd0920e08fb4268af01) | Remote default `master` is still exact baseline `130cb99`; no open PR was returned at inspection. `suppress_initial_eos`, ordinary top-k/top-p sampler and separate upper-tail `eos-guard.h`. | No newer fork remedy to adopt. The upper-tail guard is separate from early-EOS recovery; it cannot protect the recorded three-frame case. Keep this runtime pinned. |
| Parent upstream [`ServeurpersoCom/qwentts.cpp`](https://github.com/ServeurpersoCom/qwentts.cpp/tree/2edb35f87b709a070b2d5379f77e5c52a1daa585), default `master` `2edb35f87b709a070b2d5379f77e5c52a1daa585` | Inspected current `src/sampling.h`, `src/pipeline-tts.cpp`, `src/qwen.h`, recent commit list and sampling/pipeline path histories. Recent changes include implicit-GEMM causal conv1d (`2edb35f`) and fused QKV/F16 cache (`76ec9de`). No matching early-EOS detector/recovery was found in those paths/history samples. | Performance candidates require separate measurement, not wholesale upstream replacement. Current upstream header also says ABI 6 but lacks the fork's `eos_guard_*` parameter tail: the shared version number is **not proof of layout/runtime interchangeability**. Preserve fork identity and manifest validation. |

Inspection of vLLM's PR body confirms that its authors report reproducing a
no-EOS trajectory in official Transformers. That is their experiment, not a
new local verification of those hardware/model results. Likewise, OpenVINO's
104 flagged cases and 97 improved endings are author-reported Korean results;
they are not performance or quality evidence for our RU-stress/CMP workload.

## Local source-checkpoint availability

Read-only `Get-FileHash -Algorithm SHA256` matched all of these files to the
tracked [conversion provenance](russian-stress-native-conversion.json).
The legacy ignored location is reported as found; no new model copy or
alternative model-discovery root was created.

| Local file below repository root | SHA-256 |
| --- | --- |
| `.models/ru-stress-20261006/merged3/model.safetensors` (3,857,413,776 bytes) | `9742ba7f6ca86732875c4a910f8f60988183c525c84e99dd724f02424ee88fe0` |
| `merged3/config.json` | `b4f01752d15a488abde3e1ab44723ae4f4b9e68a4037257b098b3737893cc1f9` |
| `merged3/generation_config.json` | `f1b90b4513f3b34c62851049e2492d7b4c5940daf1276f89c82b8ef04127f3aa` |
| `merged3/merges.txt` | `599bab54075088774b1733fde865d5bd747cbcc7a547c5bc12610e874e26f5e3` |
| `merged3/tokenizer_config.json` | `dc3c31c3bdaedd5016382bb3cbe07323026775ad51f5a4fb564505992ae4a670` |
| `merged3/vocab.json` | `ca10d7e9fb3ed18575dd1e277a2579c16d108e32f27439684afa0e10b1440910` |
| `.models/ru-stress-20261006/merged3/speech_tokenizer/model.safetensors` | `836b7b357f5ea43e889936a3709af68dfe3751881acefe4ecf0dbd30ba571258` |

The metadata rows abbreviate the same `.models/ru-stress-20261006/` prefix.
The tracked conversion receipt links this merged source to the retained
RU-stress Q8_0 Talker
`f4672741608d145fae169075cb0ec775a5382cbe9183eccb59c7ab9cc4797427`.
This audit did not reconvert or rehash that GGUF. The merged weights are
derived from Base revision `fd4b254389122332181a7c3db7f27e918eec64e3` and
RU-stress adapter SHA
`702338d0e81ef8d04715ebd19ebe5eaf43b83446c04ee37f1a9108a9235f2b99`.

The default `py -3.11` environment reports Torch 2.8.0, Transformers 4.57.3
and safetensors 0.8.0, with `qwen_tts` module discoverable. Only package
metadata/module presence was checked; no model import, CUDA inference,
runtime suitability or usable VRAM was established.

## Strongest next parity experiment

Reuse pinned `tests/debug-clone-cossim.py` and `tests/cossim_common.py` hooks
where practical: complete forced 16-codebook frames, reference-latent export,
Talker input/overlay decomposition, prefill and per-step logits already have
diagnostic owners. The existing clone driver hardcodes its checkpoint/output
defaults and requests FP32 eager; do not run it unchanged against the default
Base checkpoint and call that RU-stress parity.

1. Hash the exact effective UTF-8 text, transcript, voice reference, native
   package, model and forced first-three-frame histories. Preserve the
   seed-2/14 failures and normal controls. Compare both bad and good histories.
2. Separate prompt/reference construction from forward arithmetic. Export or
   supply the same reference codes and speaker embedding and compare text
   tokens, prompt rows, overlays and prefill inputs before attributing logits.
3. Use identical forced complete audio histories on each backend; free-running
   same-seed output differences conflate RNG, sampling and forward differences.
   Compare raw EOS logit/rank and nearby alternatives at steps 0–3, then apply
   identical suppression/filtering offline.
4. Distinguish **checkpoint agreement** from **arithmetic parity**: native
   Q8_0 versus the merged BF16 source expanded to FP32 includes quantization
   differences by construction. A decisive arithmetic control needs the same
   dequantized GGUF tensors in the reference or an appropriately matched
   native precision control. Do not interpret any nonzero tensor difference
   as a native defect; publish numerical metrics/tolerances and bisect the
   first meaningful mismatch.
5. Freeze precision, attention implementation and TF32 policy. Repeat native
   CMP/RTX and CPU where practical, with bounded first-four-step dumps, owned
   subprocess watchdogs and disk/VRAM preflight. The diagnostic hooks must pass
   a same-run transparency check; saved diagnostics are not inherently inert.

This audit itself does not run a forward comparison. The subsequent linked
probe compares same-history PyTorch/native logits, but does not establish
strict equal-weight arithmetic, CPU/CUDA or CMP/RTX parity. Those remain
attribution boundaries between model/conditioning, quantization and native
numerical/forward behavior.

## Recovery implications

Keep native forward/sampling correctness in qwentts.cpp. Keep attempt control,
PCM commit boundary, cancellation, deadlines and exactly-once terminalization
in the native worker/Bridge. A conservative bounded startup gate can protect
uncommitted PCM; it cannot retract PCM already handed to the consumer.
After commit, report partial-output failure instead of silently replaying the
phrase. Explicit seed replacement requires opt-in; retries share one request
deadline and bounded memory budget.

A selective first-frame classifier remains a hypothesis, not an established
algorithm. EOS probability at step 3 is unavailable at step 1, and quiet PCM
alone is not a text-completeness test. Any criterion must be evaluated on
held-out texts/seeds and legitimate short utterances; longer output or natural
EOS alone is not successful spoken-text recovery.

## Retained source payloads

Downloaded reference JSON/source snapshots are ignored payloads below
`.tmp/base-acceptance/streaming-eos-research-20261120/references/` in the
primary repository. No model files were downloaded. Exact source revisions
are in the comparison table; API issue/comments are point-in-time snapshots.
Key payload SHA-256 values:

```text
e59bd14a706a74884f0372c3ce7b4e6ced58994fc299687cd97f9c357664e1ea qwen-issue55.json
00a8dd33a09de3a0b30179b7b848ab62e5f1258ea1eafe857b1c4d7c72ad687b qwen-issue55-comments.json
cda0bc6c5e7fe442f8ec1e261319c396c3e5a4be3a5997eaef3cda9140adeaa3 mlx-d2d02bf-commit.json
de76953fdc9961be613fd2521a45dd2645b56b770cafc15b078a5aa56771b740 vllm-pr6728.json
219ceef63a9568a3261bef28d46b0f6be1a8ee339e1143dbb2343148b6232159 vllm-pr6728-files.json
51aec2d6d9917bda9c4bf04e2744d2fccb6a23beb26da3182d7a1e97d375b6b5 vllm-qwen-adapter-6ffdf1.py
d2e3ebe816ca5ce7ffd5afdef5a6596b73629a1016861b05382b114c45ccb99f vllm-serving-speech-6ffdf1.py
578e8aae4c250691c9122543de6c4839f3b5f7d343e261f7cbcfd13ecec0cd8e openvino-README-24de885d.md
25c42656bcf810f06ef6bc1839bd7083f3c8cfedac3a147c4060b4262b1c96a0 qwen-official-model-022e286.py
9812a8b428efffcfe3d832409f3eae092cb3be90bfeefbf141f75df0320e2241 qwentts-upstream-sampling-2edb35f.h
f827f7a4df366f5ecc1a586ad59cf4525071ba527231e1fdc6f0463a0203d7fc qwentts-upstream-pipeline-2edb35f.cpp
08841d6299809754b2f6e4dbfce0bd1035ea351fcc51a0b437aeb39b48d79a97 qwentts-upstream-qwen-2edb35f.h
```

Quality review: one report owns the external-source comparison and provenance
lookup; no duplicate runtime implementation, classifier, dependency or status
promotion was introduced. No new hardware/listening gate was completed.
