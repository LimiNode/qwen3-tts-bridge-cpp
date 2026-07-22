# Flash-Attn Experiment - 2026-07-22

Branch: `development-flash-attn-experiment`.

Goal: test the Windows runtime matrix recommended by the vendored
Qwen3-TTS streaming fork and compare it with the Python 3.11 warmup baseline.

## Environment

- Python: `3.12.10`.
- Virtual environment: `.venv-qwen-flash`.
- PyTorch: `2.10.0+cu130`.
- Torchaudio: `2.10.0+cu130`.
- CUDA reported by PyTorch: `13.0`.
- Triton: `triton-windows==3.6.0.post26`, importable as `triton 3.6.0`.
- Flash-attn: `flash-attn==2.8.3+cu130torch2.10`.
- Model: `models/Qwen3-TTS-12Hz-0.6B-CustomVoice`.
- Speaker: `ryan`.

Install commands:

```powershell
py install -y 3.12
py -3.12 -m venv .venv-qwen-flash
.\.venv-qwen-flash\Scripts\python.exe -m pip install --index-url https://download.pytorch.org/whl/cu130 torch==2.10.0+cu130 torchaudio==2.10.0+cu130
.\.venv-qwen-flash\Scripts\python.exe -m pip install "triton-windows<3.7"
.\.venv-qwen-flash\Scripts\python.exe -m pip install "https://github.com/mjun0812/flash-attention-prebuild-wheels/releases/download/v0.7.12/flash_attn-2.8.3%2Bcu130torch2.10-cp312-cp312-win_amd64.whl"
.\.venv-qwen-flash\Scripts\python.exe -m pip install -e worker -e external\python\Qwen3-TTS-streaming
```

Import checks passed:

```text
torch 2.10.0+cu130, CUDA 13.0, cuda available: true
triton 3.6.0
flash_attn 2.8.3
flash_attn.flash_attn_interface.flash_attn_varlen_func import: passed
```

## Results

Benchmark command shape:

```powershell
.\.venv-qwen-flash\Scripts\python.exe tests\python\benchmark_packaged_worker.py `
    tmp\qwen_tts_worker_flash.cmd `
    --engine qwen `
    --model-path models\Qwen3-TTS-12Hz-0.6B-CustomVoice `
    --speaker ryan `
    --text "This is a GPU validation WAV." `
    --requests 3 `
    --timeout-seconds 1200 `
    --enable-streaming-optimizations `
    --warmup-synthesis `
    --warmup-speaker ryan `
    --warmup-text "Warmup." `
    --emit-every-frames 4 `
    --decode-window-frames 40
```

Persistent worker results:

| Request | First audio | Completed | Audio duration | Chunks | RTF |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 406 ms | 4232 ms | 3997 ms | 13 | 1.06 |
| 2 | 397 ms | 5366 ms | 5197 ms | 17 | 1.03 |
| 3 | 399 ms | 15830 ms | 15678 ms | 49 | 1.01 |

C++ WAV smoke:

- Output: `tmp/qwen-gpu-smoke-flash.wav`.
- WAV verification: `203384` PCM bytes, 24000 Hz, mono, 16-bit.
- First audio: `364 ms`.
- Synthesis: `4460 ms`.
- Audio duration: `4237 ms`.
- RTF: `1.05`.
- Worker startup: `62506 ms`.
- `flash-attn is not installed` warning: not observed.
- SoX warning was observed on stderr, but synthesis still completed. The 12Hz
  CustomVoice path used here did not require the external `sox` executable for
  this smoke.

## Conclusion

The Qwen README Windows flash-attn matrix is installable and functional on this
machine. It removes the Qwen `flash-attn is not installed` warning.

It did not show a clear latency or RTF win over the current Python 3.11
`torch 2.11.0+cu126` warmup baseline:

- Current baseline best C++ run: first audio about `338 ms`, RTF about `0.965`.
- Flash-attn C++ run: first audio about `364 ms`, RTF about `1.05`.

This suggests the optimized streaming path is now dominated more by
`torch.compile`/CUDA graph behavior, decode cadence, and generation loop
overhead than by the specific flash-attn import. Keep this as an experimental
branch until repeated runs or a packaged Python 3.12 path show a consistent
advantage.
