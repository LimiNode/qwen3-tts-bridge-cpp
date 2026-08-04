# Portable Qwen Technical Validation - 2026-08-04

## Scope

This is a technical validation of the portable Python worker. It establishes
that the packaged runtime can load a real Qwen CustomVoice model on the pinned
RTX 4090 host and exchange streamed PCM over the bridge protocol. It is not a
public beta-release claim and does not assess cloned-voice identity.

## Inputs

| Input | Value |
| --- | --- |
| Bridge source | `03b796e0786317e0748abafe25b8301353dddc3d` |
| Qwen source | `408236366b7cab3567e57c6b9183303e1f3700d9` |
| FasterQwen source | `1cc599e37f982f0e4dc8e37da5ffc946d00d85f4` |
| Model | `Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice` |
| Model revision | `85e237c12c027371202489a0ec509ded67b5e4b5` |
| Python | CPython 3.11.9 |
| Torch | `2.11.0+cu126` |
| CUDA runtime | 12.6 |
| GPU | NVIDIA GeForce RTX 4090, compute capability 8.9 |
| NVIDIA driver | 591.86 |
| Runtime tree manifest SHA-256 | `2cf03594219df21217d46a2f51220652b45d1f6252c1557e4ef6ee771a7c58dc` |

The staged package was approximately 5.05 GB across 34,977 files. Model
weights remained external and were verified by a separate content manifest.

## Procedure And Result

1. Built the portable Python worker from clean worker, Qwen, and FasterQwen
   source trees with `-IncludeQwenFork -IncludeFasterQwen`.
2. Ran `qwen_tts_doctor.cmd` with the CustomVoice model manifest,
   `--require-cuda`, and a minimum compute capability of 8.0.
3. Ran the packaged worker through `verify_packaged_worker.py` using the
   `faster` backend, CUDA, BF16, SDPA, eager prefill, no compilation, and no
   CUDA graphs.

Both gates passed. The doctor verified the complete staged Python tree and the
external model files before model startup. The Qwen smoke produced streamed PCM
through `qwen_tts_worker.cmd`; the source development environment was used only
to run the verifier, not by the staged worker process.

The MinGW `qwen_tts_save_wav.exe` example was also rebuilt and run against the
same staged runtime using the mock engine. It wrote and validated a 24 kHz,
mono, 16-bit WAV containing 4,800 PCM bytes. This confirms the native bridge
can launch the staged private interpreter and exchange framed audio; it does
not yet make that executable part of the staged distribution.

## Boundary

The result proves a portable worker runtime on this pinned host. It does not
yet produce a self-contained end-user folder because native C++ executables and
their MinGW DLLs are not staged beside the worker. The next packaging milestone
is that one-folder native bundle, followed by a clean-machine validation. The
separate four-profile cloned-voice identity study remains intentionally
deferred until the technical release path is complete.
