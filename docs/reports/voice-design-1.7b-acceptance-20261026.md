# VoiceDesign 1.7B acceptance — 2026-10-26

Status: **PARTIAL PASS — real synthesis works; EOS evidence and human listening
remain open**.

The official VoiceDesign checkpoint loaded and produced non-empty Russian WAV
audio on the CMP 50HX through both the upstream full-audio path and the pinned
faster streaming path. The run also covered two requests in one persistent
worker and independent worker restarts. It does not establish a real-time
claim, natural EOS, perceptual quality, or native-GGUF support.

No model weights, WAV files, private runtime files, or local absolute paths are
committed. The machine-readable receipt beside this report contains the exact
hash manifest and measurements.

## Provenance

| Field | Exact value |
| --- | --- |
| Model | `Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign` |
| Model revision | `5ecdb67327fd37bb2e042aab12ff7391903235d3` |
| Model manifest | 13/13 repository files hashed with SHA-256 |
| Main model SHA-256 | `391e8db219f292c515297cdceeb43e4eae67cdde35fa57e79a6a8a532fca0522` |
| Speech tokenizer SHA-256 | `836b7b357f5ea43e889936a3709af68dfe3751881acefe4ecf0dbd30ba571258` |
| Tested bridge tree | `b46acd6551f92de05482b0505e2e03c5fcfcee9d` |
| Equivalent merged bridge commit | `713f3a4bdafed86338260f99b4fe49e1ca659433` |
| Faster runtime pin | `90b596d2ffa41eb2da173db92e6f896df11b19cb` |
| Python runtime | Python 3.11.9, `qwen-tts` 0.0.4, PyTorch 2.8.0+cu128 |
| GPU | NVIDIA CMP 50HX, 20 GiB, compute capability 7.5 |
| Driver / CUDA | 581.94 / 12.8 |

The tested branch commit and merged commit have the same Git tree. The C++
probe was rebuilt from that tree; its SHA-256 is recorded in the JSON receipt.

## Fixed request

```text
language: Russian
text: Привет! Я рада тебя видеть.
instruction: Мягкий, спокойный женский голос с естественной русской артикуляцией.
seed: 1002 (fixed worker seed for repeat evidence)
format: PCM16 s16le, 24 kHz, mono
```

The repeat receipt preserves the effective UTF-8 text and instruction. Their
UTF-8 SHA-256 values are recorded in the JSON report.

## Results

| Measurement | Upstream full audio | Faster streaming |
| --- | ---: | ---: |
| Model load | 20,637.430 ms | 20,904.470 ms |
| Worker startup | 20,639.076 ms | 20,906.039 ms |
| First PCM | 44,596.735 ms | 8,571.927 ms |
| Synthesis | 44,597.164 ms | 12,054.387 ms |
| Audio duration | 5,256.875 ms | 2,376.875 ms |
| RTF | 8.484 | 5.072 |
| PCM chunks | 1 | 4 |
| PCM bytes | 252,330 | 114,090 |
| Peak CUDA reserved | 5,253,365,760 bytes | 5,242,880,000 bytes |

Both WAV files passed the existing wrapper's RIFF/PCM16, sample-rate, channel,
and non-empty-data checks. Their hashes remain in the receipt while the audio
files themselves remain outside Git.

The upstream persistent-worker repeat produced two successful requests:

| Request | First PCM | Completed | Audio | RTF | PCM SHA-256 |
| --- | ---: | ---: | ---: | ---: | --- |
| 1 | 35,741.789 ms | 35,742.461 ms | 4,216.875 ms | 8.476 | `c7cc8ce397910d3d2a4030ed091b558942988504dec79586b3013a0afd060781` |
| 2 | 34,708.172 ms | 34,708.824 ms | 4,216.875 ms | 8.231 | `c7cc8ce397910d3d2a4030ed091b558942988504dec79586b3013a0afd060781` |

The identical PCM hash is expected for the fixed seed. Separate upstream and
faster launches provide the restart subset. Memory remained finite, and all
bounded runs terminated within their configured timeout.

## Natural-EOS blocker

The strict EOS gate remains fail-closed:

- the upstream `qwen-tts` 0.0.4 VoiceDesign API returns full audio without a
  generation trace, so completion cannot prove why generation stopped;
- the faster backend streams four chunks and completes when trace collection is
  disabled;
- with `--collect-generation-trace`, the same faster VoiceDesign path fails with
  `model_error/synthesis_failed: faster backend did not produce a generation
  trace`.

The pinned faster runtime records termination metadata for other generation
paths but does not populate `last_generation_trace` for VoiceDesign streaming.
The bridge must not relabel iterator completion or a final PCM chunk as natural
EOS. A separate dependency corrective is required.

## Acceptance decision

| Gate | Result |
| --- | --- |
| Real VoiceDesign model loads | **PASS** |
| Exact Russian text and non-empty instruction reach the worker | **PASS** |
| Non-empty PCM and valid PCM16 WAV | **PASS** |
| Repeated request in one worker | **PASS** |
| Restart subset | **PASS** |
| Bounded time and finite memory | **PASS** |
| Natural EOS | **BLOCKED — missing VoiceDesign generation trace** |
| Human intelligibility and instruction adherence | **NOT RUN** |
| Native VoiceDesign GGUF | **NOT RUN** |
| Real-time/live-playback support | **NOT CLAIMED** |

VoiceDesign therefore remains conditional for the beta. The next technical
step is a narrow faster-runtime trace fix followed by this exact EOS probe; the
next product gate is explicit human listening of the preserved WAV artifact.
