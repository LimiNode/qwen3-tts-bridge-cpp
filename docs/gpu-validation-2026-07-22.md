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
cmake -S . -B build\default -DCMAKE_BUILD_TYPE=Release
cmake --build build\default --config Release
ctest --test-dir build\default --output-on-failure
```

Results:

- C++ tests: 8/8 passed.
- Packaged mock worker smoke: passed.
- Packaged Qwen protocol smoke: passed with CUDA worker, `dtype auto`, speaker `ryan`.
- C++ `qwen_tts_save_wav` real Qwen smoke: passed and wrote `tmp/qwen-gpu-smoke.wav`.
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

Persistent-worker benchmark results from `tests/python/benchmark_packaged_worker.py`:

| Mode | Request | First audio | Completed | Audio duration | RTF |
| --- | ---: | ---: | ---: | ---: | ---: |
| baseline | 1 | 6240 ms | 18263 ms | 3114 ms | 5.87 |
| baseline | 2 | 3126 ms | 28431 ms | 5917 ms | 4.80 |
| `enable_streaming_optimizations` | 1 | 46961 ms | 50164 ms | 3595 ms | 13.95 |
| `enable_streaming_optimizations` | 2 | 738 ms | 23311 ms | 22557 ms | 1.03 |

Notes:

- The worker logs warn that `flash-attn` is not installed and the model falls back to the manual PyTorch path.
- Installing `triton-windows` removes the PyTorch `triton not found` warning in this environment, but it does not remove the Qwen `flash-attn is not installed` warning and did not make the baseline real-time.
- Calling the Qwen fork's `enable_streaming_optimizations()` hook through the worker is the first mode observed to approach real-time after the initial compile-heavy request. The worker should remain persistent and should run a warmup synthesis before user-facing requests if this mode is enabled.
- The baseline is functionally correct on a real RTX 4090, but it is not real-time yet. Best observed RTF in this pass was about `5.31`.
- `float16` should not be used as the default for this model/runtime combination until the CUDA assert is understood.
- Generated models, packaged worker output, venvs, and WAV files are ignored by git.
