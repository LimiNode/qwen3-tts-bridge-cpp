# GPU Validation Notes - 2026-07-22

Machine:

- GPU: NVIDIA GeForce RTX 4090, 49140 MiB VRAM.
- NVIDIA driver: 591.86.
- Python: 3.11.9 via Python install manager.
- Packaging venv: `.venv-packaging`.
- PyTorch: `2.11.0+cu126`.
- CUDA reported by PyTorch: `12.6`.
- Triton: `triton-windows 3.7.1.post27`, importable as `triton 3.7.1`.
- Model: `models/Qwen3-TTS-12Hz-0.6B-CustomVoice`.
- HuggingFace source: `Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice`, revision `85e237c12c027371202489a0ec509ded67b5e4b5`.
- Speaker: `ryan`.

Setup and baseline checks completed:

```powershell
git submodule update --init --recursive
py install -y 3.11
.\scripts\setup-python-packaging.ps1 -UseVenv -InstallQwenFork
.\.venv-packaging\Scripts\python.exe -m pip install --force-reinstall --index-url https://download.pytorch.org/whl/cu126 torch==2.11.0+cu126 torchaudio==2.11.0+cu126
.\.venv-packaging\Scripts\python.exe -m pip install triton-windows==3.7.1.post27
.\scripts\package-python-worker.ps1 -UseVenv -Clean -IncludeQwenFork
.\scripts\test-portable-python-worker.ps1
.\scripts\benchmark-packaged-qwen-worker.ps1 -UseVenv -ModelPath models\Qwen3-TTS-12Hz-0.6B-CustomVoice -Speaker ryan -Requests 2
cmake -S . -B build\default -DCMAKE_BUILD_TYPE=Release
cmake --build build\default --config Release
ctest --test-dir build\default --output-on-failure
```

Results:

- C++ tests: 8/8 passed.
- Packaged mock worker smoke: passed.
- Packaged Qwen protocol smoke: passed with CUDA worker, `dtype auto`, speaker `ryan`.
- C++ `qwen_tts_save_wav` real Qwen smoke: passed and wrote `tmp/qwen-gpu-smoke.wav`.
- C++ `qwen_tts_save_wav` optimized warmup smoke: passed and wrote `tmp/qwen-gpu-smoke-warmup-metrics.wav`.
- WAV verification: `184210` PCM bytes, 24000 Hz, mono, 16-bit.

Observed timings from C++ WAV smoke:

| Mode | Output | First audio | Total synthesis | Audio duration | RTF | Result |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| `dtype auto` | `tmp/qwen-gpu-smoke.wav` | 6179 ms | 23970 ms | 3838 ms | 6.25 | passed |
| `dtype auto`, with `triton-windows` staged | `tmp/qwen-gpu-smoke-triton.wav` | 11438 ms | 142661 ms | 27916 ms | 5.11 | passed |
| `dtype auto`, `attn_implementation sdpa` | `tmp/qwen-gpu-smoke-sdpa.wav` | 6086 ms | 32239 ms | 6077 ms | 5.31 | passed |
| `dtype bfloat16`, `attn_implementation sdpa` | `tmp/qwen-gpu-smoke-sdpa-bf16.wav` | 6636 ms | 26263 ms | 4236 ms | 6.20 | passed |
| `dtype float16`, `attn_implementation sdpa` | `tmp/qwen-gpu-smoke-sdpa-fp16.wav` | n/a | 3123 ms | 0 ms | n/a | failed with CUDA device-side assert |
| `dtype auto`, `enable_streaming_optimizations` | `tmp/qwen-gpu-smoke-optimized.wav` | 46611 ms | 49814 ms | 3754 ms | 13.27 | passed, but first request pays compile cost |
| `dtype auto`, `enable_streaming_optimizations`, warmup synthesis, `emit=4`, `window=40` | `tmp/qwen-gpu-smoke-warmup-metrics.wav` | 338 ms | 3858 ms | 3997 ms | 0.97 | passed |

Persistent-worker benchmark results from `tests/python/benchmark_packaged_worker.py`:

| Mode | Request | First audio | Completed | Audio duration | RTF |
| --- | ---: | ---: | ---: | ---: | ---: |
| baseline | 1 | 6240 ms | 18263 ms | 3114 ms | 5.87 |
| baseline | 2 | 3126 ms | 28431 ms | 5917 ms | 4.80 |
| `enable_streaming_optimizations` | 1 | 46961 ms | 50164 ms | 3595 ms | 13.95 |
| `enable_streaming_optimizations` | 2 | 738 ms | 23311 ms | 22557 ms | 1.03 |
| `enable_streaming_optimizations`, warmup synthesis before `ready` | 1 | 717 ms | 4005 ms | 3997 ms | 1.00 |

Streaming parameter sweep with `enable_streaming_optimizations` and warmup
synthesis before `ready`:

| `emit_every_frames` | `decode_window_frames` | First audio | Completed | Audio duration | Chunks | RTF |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 4 | 80 | 389 ms | 3688 ms | 3678 ms | 12 | 1.00 |
| 2 | 80 | 218 ms | 5091 ms | 4879 ms | 31 | 1.04 |
| 8 | 80 | 812 ms | 5507 ms | 5118 ms | 8 | 1.08 |
| 4 | 40 | 376 ms | 3085 ms | 3198 ms | 10 | 0.96 |
| 4 | 120 | 390 ms | 4238 ms | 4239 ms | 14 | 1.00 |
| 2 | 40 | 218 ms | 4264 ms | 4238 ms | 27 | 1.01 |

Six-request stability run with `enable_streaming_optimizations`, warmup
synthesis, `emit_every_frames=4`, and `decode_window_frames=40`:

| Request | First audio | Completed | Audio duration | Chunks | RTF |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 400 ms | 3487 ms | 3116 ms | 10 | 1.12 |
| 2 | 402 ms | 5775 ms | 5356 ms | 17 | 1.08 |
| 3 | 437 ms | 4396 ms | 3997 ms | 13 | 1.10 |
| 4 | 474 ms | 4443 ms | 3997 ms | 13 | 1.11 |
| 5 | 473 ms | 6822 ms | 6316 ms | 20 | 1.08 |
| 6 | 474 ms | 3486 ms | 2957 ms | 10 | 1.18 |

Notes:

- The worker logs warn that `flash-attn` is not installed and the model falls back to the manual PyTorch path.
- Installing `triton-windows` removes the PyTorch `triton not found` warning in this environment, but it does not remove the Qwen `flash-attn is not installed` warning and did not make the baseline real-time.
- Calling the Qwen fork's `enable_streaming_optimizations()` hook through the worker is the first mode observed to approach real-time after the initial compile-heavy request. With `--warmup-synthesis`, the worker pays the compile/synthetic synthesis cost before `ready`; the first user-facing request reached `first_audio_ms ~= 717` and `RTF ~= 1.00` in the best current run.
- `emit_every_frames=4` and `decode_window_frames=40` is the best current throughput candidate. `emit_every_frames=2` gives the lowest first-audio latency, but it emits many more chunks.
- C++ example startup timeout must be increased for warmup-before-ready mode. The optimized warmup WAV run used `--startup-timeout-ms 1200000`, reported worker `startup_ms ~= 79119`, and then completed the first user request with `first_audio_ms ~= 338` and `RTF ~= 0.965`.
- A six-request persistent-worker run did not show progressive latency degradation. After shutdown, no Python worker process remained and `nvidia-smi` reported about `1074 MiB` used VRAM with low GPU utilization.
- The baseline is functionally correct on a real RTX 4090, but it is not real-time yet. Best observed RTF in this pass was about `5.31`.
- `float16` should not be used as the default for this model/runtime combination until the CUDA assert is understood.
- Generated models, packaged worker output, venvs, and WAV files are ignored by git.
