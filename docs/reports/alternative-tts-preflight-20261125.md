# Alternative TTS models: metadata and environment preflight

- Date: 2026-11-25.
- Status: metadata checked; isolated environments created; inference not run.
- Scope: task C in the [research continuation](tts-research-findings-and-next-stage-20261125.md).
- No weights, vocoder/codec weights, CUDA wheels or source packages downloaded.
- No production backend, worker environment, model pin or license approval changed.

## Official identities checked

The Hugging Face model API with `?blobs=true` and the exact-revision model
cards were read over HTTPS. The revisions match the earlier candidate audit.
License entries below are model-card declarations, not a complete dependency
or commercial-use review. The LFS hashes are remote metadata, not locally
verified downloaded weights.

| Candidate | Revision | Main weights | Bytes / remote LFS SHA-256 |
| --- | --- | --- | --- |
| [ESpeech RL-V2](https://huggingface.co/ESpeech/ESpeech-TTS-1_RL-V2) | `f582b6e5897fe8a5835059405a8439d13bdf7684` | `espeech_tts_rlv2.pt` | 2,697,096,939 / `2422df03cd4e939411edae06ab063b89340f70a6dee8cdeab812c4add1bdaa6c` |
| [MOSS Local v1.5](https://huggingface.co/OpenMOSS-Team/MOSS-TTS-Local-Transformer-v1.5) | `be7766a6735b98bd793f7c79fb720b4d0f5d13b8` | `model.safetensors` | 9,100,859,544 / `608f1ff64bc6caa9be836060fc7c78a15c4658c4a07b8d73c78d6f70d1b39c23` |

Pinned cards:
[ESpeech](https://huggingface.co/ESpeech/ESpeech-TTS-1_RL-V2/blob/f582b6e5897fe8a5835059405a8439d13bdf7684/README.md),
[MOSS](https://huggingface.co/OpenMOSS-Team/MOSS-TTS-Local-Transformer-v1.5/blob/be7766a6735b98bd793f7c79fb720b4d0f5d13b8/README.md).
Both declare Apache-2.0. ESpeech declares Russian, not demonstrated English
quality. MOSS lists Russian and English among 31 languages.

## Environments actually prepared

Two standard, independent Python 3.11.9 x64 virtual environments were created:

- `.tmp/tts-alternatives-20261125/envs/espeech/`
- `.tmp/tts-alternatives-20261125/envs/moss/`

Both environment executables start, report their separate `sys.prefix`, and
have no Torch installation (`importlib.util.find_spec('torch')` returns None).
They are scaffolds, not dependency-complete or model-ready runtimes. The
MOSS card recommends Python 3.12; using the currently available 3.11 scaffold
has not been qualified and is not represented as following that recommendation.
The existing worker/source environments were not changed. Future pip/HF/temp
caches must also stay under the repository, with no duplicate global download.

## ESpeech requirements and test boundary

The pinned card uses F5-TTS `DiT`, dim1024/depth22/heads16, the repository's
vocabulary, F5 `load_vocoder`, `preprocess_ref_audio_text` and `infer_process`.
Its example installs unpinned f5-tts, Gradio, RUAccent, Transformers, Torch,
Torchaudio and huggingface_hub. Those packages/vocoder weights must be resolved
and pinned before execution; the example is not a lockfile.

Stress uses `+` before the vowel (card example `прив+ет`). The example skips
automatic RUAccent processing when a text already contains `+`. Preserve
explicit inputs and any effective rewritten reference/output text. For a
controlled accent comparison, do not silently apply a second accentizer.
The example warns reference audio should be no longer than 12 seconds:
use an explicitly declared shorter Kraftwerk reference with matching transcript,
not the 17.6-second Qwen reference under an allegedly identical setup.

The example returns `final_wave` after `infer_process`, not an incremental
PCM callback. It also offloads models to CPU after each GUI call. Neither
within-sentence streaming nor warm persistent latency is established by this
example. The stock underlying inference entry point can be tested without
starting the Gradio server; record any warm-residency harness adaptation.
Vocoder identity, transitive runtime budget, SM75 support and real VRAM remain
not checked. English is a separate unsupported/experimental evaluation, not
silently assumed from a Russian-only card.

## MOSS requirements and test boundary

The pinned card recommends Transformers5.0.0 or recent Qwen3-capable versions,
and says the source project's runtime pins Torch/Torchaudio2.9.1+cu128. It
uses `AutoModel`/`AutoProcessor` with `trust_remote_code=True`, and a separate
`OpenMOSS-Team/MOSS-Audio-Tokenizer-v2`. Remote code and tokenizer weights
must be audited/pinned independently before loading. No remote code was executed.

The example chooses BF16 on CUDA and only selects optional FlashAttention2
when compute capability is at least8. CMP 50HX is SM75, has no native BF16
support and does not satisfy that FA2 gate. SDPA is the documented CUDA
fallback, but merely choosing SDPA does not qualify the example's BF16 path
on SM75. An explicitly documented FP16/FP32 control may be needed; no failure,
compatibility verdict or memory measurement is invented before testing.
RTX4090 requirements are not equivalent to a run on that hardware.

The codec is fixed to12 codebooks, 48kHz stereo. Keep the returned channel
shape, not the mono assumptions of the Qwen WAV helper. The basic example
calls `model.generate` to completion and then `processor.decode`; it alone
does not demonstrate incremental PCM. The card refers streaming to the
separate SGLang-Omni runtime, whose requirements and granularity still need
audit. Do not install or expose a network service as a shortcut. Russian IPA
syntax/control remains to be verified from the documented processing path;
the card's capability claim is not an executed pronunciation test.

## Disk and runtime decision

At initial preflight, E: had approximately11.32GiB free. The two main weight
files alone total11,797,956,483 bytes (about10.99GiB), before vocoder/tokenizer,
Torch/CUDA dependencies, caches, staging, results or the2GiB reserve. Thus
both complete setups cannot be safely downloaded together in that free space.
After local research builds/environments, observed free space is about10.92GiB;
recheck before execution rather than treating either reading as a reservation.

No destructive cleanup or automatic weight download was attempted. Remaining
dependency/codec sizes are unknown, so no precise full-install budget or VRAM
fit is claimed. Next action: resolve those manifests without weights, size one
environment at a time, and agree a separate storage/GPU budget. A storage or
runtime limitation in task C does not block CPU preparation of A/B/D/E.

## Current comparison status

| Property | ESpeech | MOSS |
| --- | --- | --- |
| Exact model metadata/card | Checked | Checked |
| Isolated interpreter scaffold | Created, Python3.11.9 | Created, Python3.11.9;3.12 recommended |
| Resolved/pinned complete dependencies | Not run | Not run |
| Weight/codec download and hash verification | Not run | Not run |
| Stock inference, RU/EN quality, cloned voice | Not run | Not run |
| `+` / Russian IPA adherence | Not run | Not run |
| Streaming granularity, latency/RTF/VRAM | Not measured | Not measured |

These are preparation outcomes, not canonical model-acceptance receipts or
evidence that either alternative is faster, better or incompatible.
