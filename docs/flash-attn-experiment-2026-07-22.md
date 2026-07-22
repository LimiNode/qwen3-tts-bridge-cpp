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

The upstream benchmark screenshot supplied during the experiment reports these
RTX 5090 streaming numbers for the author path:

| Method | First chunk | Total | Audio | RTF | Chunks | Speedup |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| streaming_baseline | 0.38 s | 6.71 s | 6.32 s | 1.06 | 20 | 1.00x |
| optimized_short | 0.08 s | 1.51 s | 7.04 s | 0.21 | 22 | 4.97x |
| optimized_medium | 0.08 s | 1.82 s | 8.96 s | 0.20 | 28 | 5.23x |
| optimized_tiny | 0.08 s | 0.26 s | 1.04 s | 0.25 | 4 | 4.25x |
| optimized_short_repeat | 0.08 s | 1.33 s | 6.32 s | 0.21 | 20 | 5.05x |

Important differences from our first bridge runs:

- The author benchmark uses `Qwen/Qwen3-TTS-12Hz-1.7B-Base` with the voice
  clone API. The bridge run below uses the available
  `Qwen3-TTS-12Hz-0.6B-CustomVoice` model and `stream_generate_pcm`.
- The author explicitly uses `torch.bfloat16`,
  `attn_implementation="flash_attention_2"`,
  `torch.set_float32_matmul_precision("high")`, `use_fast_codebook=True`, and
  `use_cuda_graphs=False`.
- The author uses three warmup generations of different lengths. The bridge
  currently supports one configurable warmup synthesis.
- The author result is on RTX 5090. This machine has RTX 4090.

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

After exposing the missing bridge flags and re-running closer to the author's
runtime settings:

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
    --decode-window-frames 80 `
    --use-fast-codebook `
    --matmul-precision high `
    --attn-implementation flash_attention_2 `
    --dtype bfloat16 `
    --no-cuda-graphs
```

| Request | First audio | Completed | Audio duration | Chunks | RTF |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 326 ms | 3064 ms | 3839 ms | 12 | 0.80 |
| 2 | 320 ms | 2746 ms | 3278 ms | 11 | 0.84 |
| 3 | 321 ms | 3255 ms | 3918 ms | 13 | 0.83 |

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

C++ WAV smoke with the author-like flags:

- Output: `tmp/qwen-gpu-smoke-flash-fast-codebook.wav`.
- First audio: `339 ms`.
- Synthesis: `4069 ms`.
- Audio duration: `4078 ms`.
- RTF: `1.00`.
- Worker startup: `64698 ms`.
- Warmup synthesis: `49854 ms`, `107466` PCM bytes, 7 chunks.
- The worker confirmed `use_cuda_graphs=False`, fast codebook generation,
  decoder/talker/codebook predictor compilation, and no flash-attn missing
  warning.

## Conclusion

The Qwen README Windows flash-attn matrix is installable and functional on this
machine. It removes the Qwen `flash-attn is not installed` warning.

The first flash-attn-only run did not show a clear latency or RTF win over the
current Python 3.11 `torch 2.11.0+cu126` warmup baseline:

- Current baseline best C++ run: first audio about `338 ms`, RTF about `0.965`.
- Flash-attn C++ run: first audio about `364 ms`, RTF about `1.05`.

After adding the missed author-like flags, the Python harness improves to about
`320 ms` first audio and `0.80-0.84` RTF on the 0.6B CustomVoice model. The C++
smoke remains closer to `1.00` RTF for one request, so repeated C++ runs are
still needed before calling this a stable bridge-level speedup.

The remaining large gap to the author's `0.08 s` first chunk and `0.20-0.25`
RTF is likely not just flash-attn. The main unresolved differences are the
model family/API path (`1.7B-Base` voice clone vs `0.6B-CustomVoice`), warmup
strategy, and RTX 5090 vs RTX 4090 hardware.
