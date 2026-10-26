# VoiceDesign 1.7B acceptance — 2026-10-26

Status: **CONDITIONAL PASS — natural EOS receipt now passes; human listening
and native GGUF remain open.**

The pinned corrective release of `faster-qwen3-tts` exposes the VoiceDesign
generation trace. A real CMP 50HX run produced non-empty Russian PCM, passed
strict natural-EOS validation, and preserved the previous WAV bytes. This is
an offline acceptance result; it does not establish a real-time claim or
perceptual quality.

## Provenance

| Field | Exact value |
| --- | --- |
| Model | `Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign` |
| Model revision | `5ecdb67327fd37bb2e042aab12ff7391903235d3` |
| Model manifest | 13/13 repository files hashed with SHA-256 |
| Main model SHA-256 | `391e8db219f292c515297cdceeb43e4eae67cdde35fa57e79a6a8a532fca0522` |
| Speech tokenizer SHA-256 | `836b7b357f5ea43e889936a3709af68dfe3751881acefe4ecf0dbd30ba571258` |
| Tested bridge commit | `713f3a4bdafed86338260f99b4fe49e1ca659433` |
| Tested bridge tree | `b46acd6551f92de05482b0505e2e03c5fcfcee9d` |
| Faster runtime used for the CMP receipt | `bd28393708c64812a1cf67d14e0c71cd95d01204` |
| Faster runtime release pin after upstream merge | `4bdcd3f8d57fabbdc605152c7958e095321a4e46` |
| Python runtime | Python 3.11.9, `qwen-tts` 0.0.4, PyTorch 2.8.0+cu128 |
| GPU | NVIDIA CMP 50HX, 20 GiB, compute capability 7.5 |
| Driver / CUDA | 581.94 / 12.8 |

No model weights, WAV files, private runtime files, or local absolute paths
are committed. The machine-readable receipt beside this report contains the
complete 13-file model manifest and all timing/hash values.

## Fixed request

The run used Russian text, a non-empty natural-language VoiceDesign
instruction, fixed seed `1002`, and mono PCM16/s16le at 24 kHz. The exact
effective UTF-8 inputs were:

```text
text: Привет! Я рада тебя видеть.
instruction: Мягкий, спокойный женский голос с естественной русской артикуляцией.
```

Their SHA-256 values are in the JSON receipt.

## Results

| Measurement | Upstream full audio | Faster streaming |
| --- | ---: | ---: |
| Model load | 20,637.430 ms | 20,904.470 ms |
| First PCM | 44,596.735 ms | 8,571.927 ms |
| Synthesis | 44,597.164 ms | 12,054.387 ms |
| Audio duration | 5,256.875 ms | 2,376.875 ms |
| RTF | 8.484 | 5.072 |
| PCM chunks | 1 | 4 |
| PCM bytes | 252,330 | 114,090 |

The faster strict-EOS receipt is:

```text
termination_reason=eos
hit_eos=true
codec_frame_count=30
audio_chunks=4
PCM bytes=114090
WAV SHA256=f481905c64bca5e738c756c262313a4553fc5366bf32cb3af3c6a524789f52ae
```

The output is byte-identical to the pre-corrective faster run. Persistent
two-request repeat, restart subset, valid PCM16 WAV, bounded timeout, and
finite-memory checks remain PASS. The upstream repeat produced the same PCM
SHA-256 for both requests under the fixed seed.

The historical evidence is retained in full in the receipt rather than
replaced by the corrective result. This includes the two persistent-worker
request timings and PCM hashes, WAV sizes, CUDA allocated/reserved/max-reserved
measurements, and the original trace failure:

```text
without trace: completed
with trace before corrective: failed
error: model_error/synthesis_failed: faster backend did not produce a generation trace
```

The corrected trace is explicitly identified as `voice_design_streaming_v1`;
the safety-limit flags are recorded as false for this EOS run. A codec-token
SHA was not present in the saved hardware receipt and is intentionally not
invented.

## Acceptance decision

| Gate | Result |
| --- | --- |
| Real VoiceDesign model loads | **PASS** |
| Exact Russian text and non-empty instruction reach the worker | **PASS** |
| Non-empty PCM and valid PCM16 WAV | **PASS** |
| Persistent repeat / restart subset | **PASS** |
| Bounded time and finite memory | **PASS** |
| Natural EOS with generation trace | **PASS** |
| Human intelligibility and instruction adherence | **NOT RUN** |
| Native VoiceDesign GGUF | **NOT RUN** |
| Real-time/live-playback support | **NOT CLAIMED** |

VoiceDesign therefore remains conditional for beta release until the preserved
WAV artifact receives explicit human listening and the separate native-GGUF
gate is addressed. The dependency corrective is tracked independently in
`LimiNode/faster-qwen3-tts#4`.
