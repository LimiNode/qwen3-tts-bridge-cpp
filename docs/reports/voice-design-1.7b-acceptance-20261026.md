# VoiceDesign 1.7B acceptance gate — 2026-10-26

Status: **NOT RUN — model artifact unavailable in the evidence environment**.
This is an acceptance inventory and reproducible gate definition, not a model
quality result. No VoiceDesign model weights, WAV, or private runtime files are
committed.

## Target profile

| Field | Required value | Current evidence |
| --- | --- | --- |
| Model family | VoiceDesign | pending real-model run |
| Model | `Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign` | expected source; revision not captured |
| Backend | Python worker with `qwen_tts_save_wav` | wrapper path is present and tested with mock worker |
| Device | CMP 50HX, CUDA 12.8, driver 581.94 | available hardware profile; no VoiceDesign inference receipt |
| Language | Russian | gate input |
| Voice control | non-empty natural-language instruction | gate input |
| Real-time claim | none | offline WAV acceptance only |

The model revision, downloaded-file SHA-256 values, worker/runtime versions,
and effective engine profile must be filled from the actual run. The expected
model name alone is not provenance.

## Required run

Use the existing `scripts/start-voice-design-save-wav.ps1` wrapper and the
existing `qwen_tts_save_wav` executable. Keep all generated artifacts outside
Git (for example under `E:\stage-a-voice-design-evidence`). A valid run must
record:

1. model source revision and SHA-256 manifest;
2. Python, PyTorch, CUDA, worker, and bridge executable versions;
3. GPU/device and runtime profile;
4. exact UTF-8 text and instruction (including their SHA-256 values);
5. startup, first PCM, total inference, and output-duration timings separately;
6. terminal outcome (`natural_eos` or an explicit, classified failure);
7. WAV format, non-zero PCM byte count, and file SHA-256;
8. a repeated request in the same worker and a restart-subset request;
9. bounded wall-clock and finite-memory observations;
10. human listening results for intelligibility, pronunciation, and adherence to
    the requested voice description.

The run must not be reported as streaming or real-time merely because the
worker exposes a chunk callback. Current Base evidence is slower than
real-time on this hardware, so VoiceDesign acceptance remains offline.

## Acceptance decision matrix

| Gate | Required result | Current result |
| --- | --- | --- |
| Real VoiceDesign model loads | pass | **NOT RUN** |
| Instruction reaches the model unchanged | pass | mock plumbing only |
| Non-empty PCM and valid PCM16 WAV | pass | mock wrapper regression only |
| Natural EOS or explicit classified failure | pass | **NOT RUN** |
| Repeated request / restart subset | pass | **NOT RUN** |
| Bounded time and finite memory | pass | **NOT RUN** |
| Human intelligibility and instruction adherence | pass | **NOT RUN** |
| Native VoiceDesign GGUF | separate capability row; do not infer from Python | **NOT RUN** |

Until the real-model row is complete, beta documentation must keep VoiceDesign
conditional and must not substitute the accepted Base 1.7B receipt.
