# Same-history RU-stress source-checkpoint early-EOS probe

Date: 2026-11-20. Research only. R1 remains **NO-GO**; no hardware,
listening, recovery or release gate is promoted by this experiment. The
frozen runtime, models, dependency pins and prior seed evidence were not
modified. No audio was decoded or published.

## Measured result

The retained failing seed-2 history also produces EOS-dominant next-token
logits in the original merged source checkpoint, running FP32 PyTorch on CPU.
The normal seed-1 history does not. Both complete three-frame histories were
forced verbatim, including all 16 codebooks, before evaluating the fourth
Talker decision (zero-based step 3).

| History at step 3 | Retained native Q8/CUDA | Source FP32, reconstructed inputs | Source FP32, exact retained native inputs |
| --- | --- | --- | --- |
| Seed 2, failing prefix | EOS logit 15.804861; rank 1; raw probability 0.824654 | 15.918203; rank 1; 0.841397 | 15.918782; rank 1; 0.841685 |
| Seed 1, normal prefix | EOS logit 5.780709; rank 126; raw probability 0.00009311 | 5.797756; rank 122; 0.00010323 | 5.794064; rank 122; 0.00010329 |

Probabilities in this table are a diagnostic softmax at temperature 1 over
permitted audio IDs 0–2047 plus EOS 2150, **before** repetition penalty,
temperature 0.9 and top-k/top-p. Rank counts all raw vocabulary logits.
They are not the final production sampling probabilities.

For seed 2, the next unforced reference sampler draw was subsequence 48,
uniform `0.32810038328170776`, selected token **2150 (EOS)**. For seed 1,
subsequence 48, uniform `0.09177681803703308`, selected ordinary token **320**.
This is a reference harness using pinned Philox and vocabulary-order
accumulation, not unmodified upstream `torch.multinomial`.

The experiment supports an EOS-favouring model state conditioned on the bad
history, rather than an error unique to the native sampler. It does **not**
prove a universal model defect or strict native/source arithmetic parity:
native uses Q8_0, source uses original checkpoint tensors expanded to FP32,
and their arithmetic/attention implementations differ. Nor does it identify
why the stochastic trajectory first entered that history. In particular, it
does not rule out quantization changing earlier free-running choices.

## Frozen identities and environment

Native comparison evidence is the existing Bridge
`aa2770ec8aeb45d59f42c96c3a1f4f2dc52390d8`,
`LimiNode/qwentts.cpp@130cb99af9ae12d554962fd0920e08fb4268af01`, ABI 6,
CMP 50HX UUID `GPU-40361931-6cb5-ac58-a059-5ba3e70986fb`, from the
seeded sweep and replay retained for PR #330. Those native outputs were
read, not rerun by this probe. Source/output payloads are relative to the
primary repository root, not the task worktree.

| Item | Exact identity |
| --- | --- |
| Source weights | `.models/ru-stress-20261006/merged3/model.safetensors`, 3,857,413,776 bytes; SHA-256 `9742ba7f6ca86732875c4a910f8f60988183c525c84e99dd724f02424ee88fe0` |
| Native derived RU-stress Talker | Q8_0 SHA-256 `f4672741608d145fae169075cb0ec775a5382cbe9183eccb59c7ab9cc4797427` per tracked conversion provenance; no reconversion here |
| Host | Intel Xeon E5-2696 v3, 18 cores / 36 logical processors; PyTorch limited to 8 threads |
| Interpreter | `C:\Users\User\AppData\Local\Programs\Python\Python311\python.exe` |
| Packages | Torch 2.8.0 **CPU-only**, Transformers 4.57.3, safetensors 0.8.0 |
| Precision / attention | FP32; actual Talker **SDPA**, actual code predictor **SDPA**; TF32 disabled |
| Installed modeling source | `qwen_tts/core/models/modeling_qwen3_tts.py`, SHA-256 `9c5b54d9435604c6cbfda0fbbaeb77d4c959b0f95592b00f40c507f5364ede38` |
| Diagnostic helper | Pinned `external/cpp/qwentts.cpp/tests/cossim_common.py`, SHA-256 `ac6c7de23cacab75c7c7a5317eda9994e3c19336832e56be3da9d0915852dca4` |

The installed modeling file was compared with official source revision
`022e286b98fbec7e1e916cb940cdf532cd9f488e`. The observed diff is attention
capability flags and attention-forwarding changes in `from_pretrained`;
the inspected forward bodies are unchanged. It is not byte-identical source.

An initial owned CUDA attempt failed during model loading with
`AssertionError: Torch not compiled with CUDA enabled`; no CUDA forward or
VRAM measurement occurred. Its exact driver, invocation, identity and
stderr remain preserved separately. The usable probe was deliberately
labelled `cpu-v1`, not reported as a GPU result.

The driver requested `attn_implementation="eager"`, but the installed custom
`from_pretrained` did not propagate that request to the nested models. The
effective configs recorded after generation are **SDPA**. Consequently the
historical `identity.json`/`identity.attention` field describing the requested
`eager` setting is not authoritative; `results.json.actual_attention` and this
report state what actually ran. No evidence was overwritten to hide this
metadata discrepancy. An explicit eager run has not been claimed.

## Conditioning and method

Effective text, exactly 126 UTF-8 bytes:

```text
МГУ находится в Москве. Инженер проверил USB-порт, GPS и новый процессор.
```

Text SHA-256:
`d917e809733280d0fcc4603828e8253593839a22e29161216868f18ef4ba8a5e`.
Voice: `kraftwerk_robot_ru_bootstrap_fidelity`, ICL clone, language `russian`.
The full reference transcript and its effective prompt inputs are captured in
each run identity, rather than inferred from the WAV filename.

1. Verify the source weight hash against tracked
   [conversion provenance](russian-stress-native-conversion.json). Load all
   model/tokenizer data offline; neither downloads nor model writes occur.
2. Import the pinned diagnostic helper with exactly one in-memory path-only
   adaptation: its assumed sibling `../../Qwen3-TTS` checkout is replaced by
   the existing installed `qwen_tts` package parent. No helper/model files
   are edited. Reuse its hooks, binary dump codec and Philox stream.
3. Reconstruct the source prompt with the official tokenization path. All
   **30 target prompt token IDs match** the retained native input. Supply
   the exact retained native 2048-component speaker embedding and
   226-by-16 reference codes; no source audio encoder rerun introduces a
   different reference latent.
4. Force exactly the retained first three complete 16-codebook frames using
   the helper's opt-in diagnostic seam. Assert these frames appear unchanged
   in the source output. Limit generation to four Talker decisions. Both
   bad and good histories are tested; seed identity governs the Philox draw
   but the first three frames are forced, not free-running reproductions.
5. Capture raw source prefill and next-step logits, prompt embeddings,
   trailing text/pad and each next-input vector, and compare them with the
   retained native dumps. All measured logits are finite.
6. Remove diagnostic forward hooks, start a fresh KV cache, then feed the
   **exact native prefill and three native next-input vectors** directly
   through the source Talker model and codec head. This removes input
   reconstruction differences; it does not remove Q8/source weight or
   arithmetic differences.

Generation settings are Talker/predictor sampling enabled, temperature 0.9,
top-k 50, top-p 1.0, repetition penalty 1.05; official initial EOS masking
is retained. No custom minimum-duration, EOS suppression, retry or duration
heuristic was added. The forward-only control performs no sampling.

The capped `max_new_tokens=4` call returns three fully materialized codebook
frames for **both** histories because the last selected first-codebook token
is not followed by its predictor forward at the cap. Thus
`source_codes_frames=3` alone is **not** evidence of natural EOS. EOS evidence
is the unforced final sampler choice and raw logits above. No full reference
utterance, waveform or speech-completeness claim follows from this cap.

## Numeric checks

For seed 2, raw EOS progression:

| Step | Native Q8 EOS logit / rank / probability | Source reconstructed EOS logit / rank / probability | Source exact native inputs EOS logit / rank / probability |
| --- | --- | --- | --- |
| 0 | 12.554852 / 6 / 0.0174506 | 12.647317 / 6 / 0.0188301 | 12.650885 / 6 / 0.0189931 |
| 1 | 12.811306 / 6 / 0.0391221 | 12.794127 / 6 / 0.0367612 | 12.801260 / 6 / 0.0372742 |
| 2 | 6.522797 / 46 / 0.00009548 | 6.622763 / 45 / 0.00009717 | 6.622836 / 45 / 0.00009756 |
| 3 | 15.804861 / 1 / 0.824654 | 15.918203 / 1 / 0.841397 | 15.918782 / 1 / 0.841685 |

At step 3 both implementations have the same leading five raw token IDs:
`2150, 619, 164, 362, 251`. Native logits are respectively
`15.804861, 13.470520, 12.240520, 11.747870, 11.667660`.
This is not an EOS token artificially restored after filtering: it is already
the strongest raw candidate. See the separate
[external-source audit](early-eos-external-source-audit-20261120.md) for why
the MLX post-filter EOS fix does not apply to this observation.

Native/source reconstructed prefill embeddings have relative L2 error
`0.00481748`, cosine `0.99998840`, maximum absolute error `0.00205314`.
For the failing prefix the next-input relative L2 errors are approximately
`0.00362, 0.00399, 0.00427`. They are not byte-equal, as expected from Q8
versus source embeddings. The exact-native-input control reaches the same
EOS-dominant conclusion after eliminating this discrepancy. This experiment
does not establish a general acceptable numerical tolerance for the backend.

## Reproduction, payload integrity and limits

Owned-child invocation from the primary repository root:

```powershell
py -3.11 -B -u .tmp/base-acceptance/streaming-eos-research-20261120/parity/launch.py
```

The launcher sequentially records and runs `probe.py --seed 2` then
`probe.py --seed 1`, using `-B -u`; per-child watchdog 270 seconds, shared
budget 570 seconds, owned-tree termination on timeout. Both completed with
exit 0 and no timeout. The output directories are exclusive-create: preserve
them and choose a new versioned destination before any rerun. Loader/hash
time is not a native or CUDA performance measurement.

Exact commands, environment overrides, times, driver hashes, JSON results,
input/logit dumps and failed-CUDA evidence are retained in
`.tmp/base-acceptance/streaming-eos-research-20261120/parity/`.
An inventory covers 129 files / 27,994,000 bytes at capture; no model blob
is included. SHA-256 values:

```text
e1028aae49a5e7e6c91ff74263997adcb20b074b6298ea4f691658198b253b2b probe.py
8e159172370c6712c01292c29352e86d7a0ba925f7cd4f15af67fe0ea3e5841e launch.py
7062035bcad4f17d55b6f8905e4df414cae354ef55f41d000420b75e471c1349 seed-2-cpu-v1/results.json
8bccc104ae9b4fab68193417692b2d8889e4970029db3c7d8fc6aa8c7ab34bbb seed-1-cpu-v1/results.json
64206235a2ec5c8b241cb4c36805585a6d2e40ada22ae9e3f92871235293fa3c sha256-inventory-cpu-v1.json
```

The research scripts/dumps are ignored local payloads, not shipped runtime or
a new CLI surface. They require the installed package and retained checkpoint
and must not be presented as a clean-machine reproduction bundle. The
tracked report preserves the useful result without promoting an acceptance
receipt; no acceptance gate changed and no listener assessed an artifact.

Remaining attribution/control work: source free-running and matched-weight
native/reference controls; explicit effective eager versus SDPA; CPU/CUDA and
CMP/RTX comparison; earlier-history sensitivity across more texts and seeds.
Candidate recovery still needs independent speech coverage and legitimate
short-utterance tests. The bounded probe cannot validate a duration heuristic
or a production early-EOS detector.
