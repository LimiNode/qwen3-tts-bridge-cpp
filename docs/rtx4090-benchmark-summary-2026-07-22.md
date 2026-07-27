# RTX 4090 Benchmark Summary - 2026-07-22

This document preserves the current real-GPU findings for later README and
release-report work. All local bridge metrics use:

```text
RTF = elapsed synthesis time / generated audio duration
```

With this convention, lower is better and `RTF < 1.0` is faster than real-time.
Some external projects report the inverse (`audio duration / elapsed time`),
where higher is better. Convert before comparing tables.

## Machine

- GPU: NVIDIA GeForce RTX 4090, 49140 MiB VRAM.
- NVIDIA driver: 591.86.
- Driver model: WDDM.
- CPU: 2 x Intel Xeon E5-2696 v4, 22 cores / 44 threads each,
  2.20 GHz nominal max clock.
- Windows power plan: `Maximum Performance`.
- HAGS registry override: `HwSchMode` not set.
- OS: Windows.
- Main bridge runtime: Python 3.11.9, PyTorch `2.11.0+cu126`,
  Torchaudio `2.11.0+cu126`, `triton-windows==3.7.1.post27`.
- Flash-attn experiment runtime: Python 3.12.10, PyTorch `2.10.0+cu130`,
  Torchaudio `2.10.0+cu130`, `triton-windows==3.6.0.post26`,
  `flash-attn==2.8.3+cu130torch2.10`.
- Faster Qwen experiment runtime: Python 3.12.10,
  `faster-qwen3-tts==0.3.2`, `qwen-tts==0.1.1`, PyTorch
  `2.11.0+cu130`, Torchaudio `2.11.0+cu130`.
- Faster Qwen torch/CUDA control runtime: Python 3.12.10,
  `faster-qwen3-tts==0.3.2`, `qwen-tts==0.1.1`, PyTorch
  `2.10.0+cu128`, Torchaudio `2.10.0+cu128`.
- Faster Qwen clean PR stack runtime: Python 3.12.10,
  `faster-qwen3-tts==0.3.2` from `v0.3.2` plus PR #108-#112
  cherry-picks, PyTorch `2.10.0+cu128`, CUDA runtime `12.8`.

## CustomVoice Bridge Path

Model:

```text
models/Qwen3-TTS-12Hz-0.6B-CustomVoice
```

Speaker:

```text
ryan
```

Text:

```text
This is a GPU validation WAV.
```

### C++ WAV Smokes

| Runtime / mode | Key parameters | First audio | Synthesis | Audio | RTF | Notes |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| Python 3.11 torch 2.11 cu126 | `dtype auto` | 6179 ms | 23970 ms | 3838 ms | 6.25 | baseline, not real-time |
| Python 3.11 torch 2.11 cu126 | `dtype auto`, `attn_implementation sdpa` | 6086 ms | 32239 ms | 6077 ms | 5.31 | still not real-time |
| Python 3.11 torch 2.11 cu126 | `dtype bfloat16`, `attn_implementation sdpa` | 6636 ms | 26263 ms | 4236 ms | 6.20 | no improvement |
| Python 3.11 torch 2.11 cu126 | `enable_streaming_optimizations`, no warmup | 46611 ms | 49814 ms | 3754 ms | 13.27 | first request pays compile cost |
| Python 3.11 torch 2.11 cu126 | `enable_streaming_optimizations`, warmup synthesis, `emit=4`, `window=40` | 338 ms | 3858 ms | 3997 ms | 0.97 | best C++ baseline on main runtime |
| Python 3.12 torch 2.10 cu130 flash-attn | `enable_streaming_optimizations`, warmup synthesis, `emit=4`, `window=40` | 364 ms | 4460 ms | 4237 ms | 1.05 | flash-attn imports, no warning |
| Python 3.12 torch 2.10 cu130 flash-attn | `dtype bfloat16`, `flash_attention_2`, `matmul high`, `use_fast_codebook`, `no-cuda-graphs`, `emit=4`, `window=80` | 339 ms | 4069 ms | 4078 ms | 1.00 | author-like flags, C++ single-request smoke |

`dtype float16` failed in this environment with a CUDA device-side assert and
should not become a default without a separate root-cause pass.

### Python Persistent-Worker Benchmarks

| Runtime / mode | Request | First audio | Completed | Audio | Chunks | RTF |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Python 3.11 baseline | 1 | 6240 ms | 18263 ms | 3114 ms | n/a | 5.87 |
| Python 3.11 baseline | 2 | 3126 ms | 28431 ms | 5917 ms | n/a | 4.80 |
| Python 3.11 optimized, no warmup | 1 | 46961 ms | 50164 ms | 3595 ms | n/a | 13.95 |
| Python 3.11 optimized, no warmup | 2 | 738 ms | 23311 ms | 22557 ms | n/a | 1.03 |
| Python 3.11 optimized, warmup | 1 | 717 ms | 4005 ms | 3997 ms | n/a | 1.00 |
| Python 3.12 flash-attn, optimized, warmup, `emit=4`, `window=40` | 1 | 406 ms | 4232 ms | 3997 ms | 13 | 1.06 |
| Python 3.12 flash-attn, optimized, warmup, `emit=4`, `window=40` | 2 | 397 ms | 5366 ms | 5197 ms | 17 | 1.03 |
| Python 3.12 flash-attn, optimized, warmup, `emit=4`, `window=40` | 3 | 399 ms | 15830 ms | 15678 ms | 49 | 1.01 |
| Python 3.12 flash-attn, author-like flags, `emit=4`, `window=80` | 1 | 326 ms | 3064 ms | 3839 ms | 12 | 0.80 |
| Python 3.12 flash-attn, author-like flags, `emit=4`, `window=80` | 2 | 320 ms | 2746 ms | 3278 ms | 11 | 0.84 |
| Python 3.12 flash-attn, author-like flags, `emit=4`, `window=80` | 3 | 321 ms | 3255 ms | 3918 ms | 13 | 0.83 |

The author-like flag set was:

```text
--dtype bfloat16
--attn-implementation flash_attention_2
--matmul-precision high
--use-fast-codebook
--no-cuda-graphs
--enable-streaming-optimizations
--warmup-synthesis
--emit-every-frames 4
--decode-window-frames 80
```

## Direct Base Voice-Clone Path

Script:

```text
scripts/qwen-voice-clone-direct-benchmark.py
```

This bypasses the C++ bridge and worker protocol. It directly calls the
upstream Qwen streaming fork's `stream_generate_voice_clone()`.

Model:

```text
Qwen/Qwen3-TTS-12Hz-1.7B-Base
```

Reference audio:

```text
https://qianwen-res.oss-cn-beijing.aliyuncs.com/Qwen3-TTS-Repo/clone_2.wav
```

Reference text:

```text
Okay. Yeah. I resent you. I love you. I respect you. But you know what? You blew it! And thanks to you.
```

### Short Target

Text:

```text
Я твой робот. Я твой работник.
```

| Method | First chunk | Total | Audio | RTF | Chunks |
| --- | ---: | ---: | ---: | ---: | ---: |
| standard | n/a | 20.97 s | 3.03 s | 6.91 | 0 |
| streaming_baseline | 2.06 s | 13.37 s | 2.24 s | 5.97 | 7 |
| warmup_1 | 231.16 s | 233.18 s | 2.88 s | 80.96 | 9 |
| warmup_2 | 0.28 s | 2.39 s | 2.96 s | 0.81 | 10 |
| warmup_3 | 0.28 s | 3.66 s | 4.64 s | 0.79 | 15 |
| optimized_1 | 0.28 s | 1.78 s | 2.16 s | 0.82 | 7 |
| optimized_2 | 0.29 s | 2.03 s | 2.48 s | 0.82 | 8 |

### Longer Target

Text:

```text
Я твой робот. Я твой работник. Мы запрограммированы делать всё, что ты захочешь. Мы твои слуги, мы твои работники.
```

| Method | First chunk | Total | Audio | RTF | Chunks |
| --- | ---: | ---: | ---: | ---: | ---: |
| streaming_baseline | 3.45 s | 46.77 s | 7.76 s | 6.03 | 25 |
| warmup_1 | 47.70 s | 49.42 s | 2.32 s | 21.30 | 8 |
| warmup_2 | 0.29 s | 2.88 s | 3.60 s | 0.80 | 12 |
| warmup_3 | 0.28 s | 3.49 s | 4.48 s | 0.78 | 14 |
| optimized_1 | 0.28 s | 6.53 s | 8.40 s | 0.78 | 27 |
| optimized_2 | 0.27 s | 5.92 s | 7.76 s | 0.76 | 25 |

The direct Base voice-clone path works, and it is slightly faster than the
bridge CustomVoice Python harness after warmup. It still does not reproduce the
upstream screenshot's `0.08 s` first chunk and `0.20-0.25` local RTF.

## Direct Faster-Qwen3-TTS Path

Script:

```text
scripts/faster-qwen-direct-benchmark.py
```

This bypasses the bridge and the upstream streaming fork. It uses
`faster-qwen3-tts`, which replaces the dynamic-cache decode path with static
buffers and manual CUDA Graph replay.

The temporary environment is ignored by git:

```text
.venv-faster-qwen
```

Initial `pip install faster-qwen3-tts` pulled CPU-only `torch 2.13.0+cpu` on
Windows. The environment was then corrected to:

```powershell
.\.venv-faster-qwen\Scripts\python.exe -m pip install --force-reinstall `
    --index-url https://download.pytorch.org/whl/cu130 `
    torch==2.11.0+cu130 `
    torchaudio==2.11.0+cu130
```

CUDA check after reinstall:

```text
torch 2.11.0+cu130
CUDA 13.0
NVIDIA GeForce RTX 4090
```

### Short Base Voice Clone

Command:

```powershell
.\.venv-faster-qwen\Scripts\python.exe scripts\faster-qwen-direct-benchmark.py `
    --runs 3 `
    --text "Я твой робот. Я твой работник." `
    --language Russian `
    --output-dir tmp\faster-qwen-direct-short
```

| Method | First chunk | Total | Audio | Local RTF | Inverse RTF | Chunks |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| run_1 | 9.49 s | 10.55 s | 2.64 s | 4.00 | 0.25 | 5 |
| run_2 | 0.42 s | 1.16 s | 2.56 s | 0.45 | 2.20 | 4 |
| run_3 | 0.42 s | 1.19 s | 2.48 s | 0.48 | 2.08 | 4 |

### Longer Base Voice Clone, `chunk_size=4`

Command:

```powershell
.\.venv-faster-qwen\Scripts\python.exe scripts\faster-qwen-direct-benchmark.py `
    --runs 3 `
    --chunk-size 4 `
    --text "Я твой робот. Я твой работник. Мы запрограммированы делать всё, что ты захочешь. Мы твои слуги, мы твои работники." `
    --language Russian `
    --output-dir tmp\faster-qwen-direct-long-chunk4
```

| Method | First chunk | Total | Audio | Local RTF | Inverse RTF | Chunks |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| run_1 | 9.13 s | 13.41 s | 8.24 s | 1.63 | 0.61 | 26 |
| run_2 | 0.34 s | 4.34 s | 8.40 s | 0.52 | 1.93 | 27 |
| run_3 | 0.34 s | 4.33 s | 8.56 s | 0.51 | 1.98 | 27 |

### Longer Base Voice Clone, `x_vector_only`

Command:

```powershell
.\.venv-faster-qwen\Scripts\python.exe scripts\faster-qwen-direct-benchmark.py `
    --runs 3 `
    --chunk-size 8 `
    --x-vector-only `
    --text "Я твой робот. Я твой работник. Мы запрограммированы делать всё, что ты захочешь. Мы твои слуги, мы твои работники." `
    --language Russian `
    --output-dir tmp\faster-qwen-direct-long-xvec
```

| Method | First chunk | Total | Audio | Local RTF | Inverse RTF | Chunks |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| run_1 | 27.28 s | 31.10 s | 9.84 s | 3.16 | 0.32 | 16 |
| run_2 | 0.51 s | 3.85 s | 9.04 s | 0.43 | 2.35 | 15 |
| run_3 | 0.41 s | 3.62 s | 9.04 s | 0.40 | 2.50 | 15 |

### Faster-Qwen Interpretation

`faster-qwen3-tts` is the best lead so far:

- It makes the model load and graph warmup cheap after the HuggingFace cache is
  populated: about `17-24 s` model load and `4.2 s` explicit graph warmup in
  these runs.
- After the first synthesis request, it improves Base voice-clone throughput
  from the upstream direct path's local RTF `0.76-0.82` to about `0.40-0.52`.
- `chunk_size=4` lowers TTFA from about `0.42 s` to about `0.34 s`, but costs
  throughput.
- `x_vector_only` improves longer-text throughput to local RTF `0.40-0.43`, but
  TTFA stays around `0.41-0.51 s` in this direct setup.

It still does not match its README's reported RTX 4090 class of about
`156-174 ms` TTFA and inverse RTF `4.22-4.78`. The current local best observed
with this package is about `337 ms` first chunk and inverse RTF about `2.50`.
The remaining difference may involve exact package version, torch version,
model family, generation settings, cached speaker embeddings, or benchmark
methodology.

## Official Faster-Qwen3-TTS Benchmark

The current experiment branch was pushed successfully:

```text
origin/development-flash-attn-experiment
6c1e2cfd7e622977d29f6533dc620297bc9dde95
```

Clean external worktrees were created outside this repository:

```text
C:/_repoz/faster-qwen3-tts-v032   v0.3.2, commit a70afc0
C:/_repoz/faster-qwen3-tts-pr112  PR #112 stack, commit 2004275
```

Both runs used the unmodified upstream `benchmarks/throughput.py` with:

```text
MODEL_SIZE=1.7B
attn_implementation=eager
max_seq_len=2048
primary chunk_size=8
upstream ref_audio.wav and ref_text
upstream text
upstream warmup flow
```

Runtime:

```text
Python 3.12.10
torch 2.11.0+cu130
CUDA runtime 13.0
transformers 4.57.3
qwen-tts 0.1.1
GPU NVIDIA GeForce RTX 4090
NVIDIA driver 591.86
Driver model WDDM
```

The initial `v0.3.2` run imported from
`C:/_repoz/faster-qwen3-tts-v032/faster_qwen3_tts`. The PR #112 run imported
from `C:/_repoz/faster-qwen3-tts-pr112/faster_qwen3_tts`; its package metadata
reports version `0.2.6`, but the source path confirms the PR worktree.

PowerShell reported exit code 1 because the Python process wrote the external
`sox` warning to stderr, but both benchmark scripts reached completion, wrote
sample WAV files, and wrote JSON result files.

### Official v0.3.2

Raw output:

```text
tmp/faster-v032-throughput-1.7B.txt
C:/_repoz/faster-qwen3-tts-v032/bench_results_NVIDIA_GeForce_RTX_4090.json
```

Summary:

| Metric | Value |
| --- | ---: |
| Warmup | 17.32 s |
| TTFA, chunk 4 | 357 ms +/- 47 |
| TTFA, chunk 8 primary | 424 ms +/- 19 |
| TTFA, chunk 12 | 506 ms +/- 17 |
| Dynamic-cache baseline TTFA | 4523 ms +/- 154 |
| Dynamic-cache baseline inverse RTF | 0.150 +/- 0.003 |
| Fast path TTFA | 439 ms +/- 47 |
| Fast path inverse RTF | 2.507 +/- 0.053 |
| Fast path local RTF | 0.399 |

### Official PR #112 Stack

Raw output:

```text
tmp/faster-pr112-throughput-1.7B.txt
C:/_repoz/faster-qwen3-tts-pr112/bench_results_NVIDIA_GeForce_RTX_4090.json
```

Summary:

| Metric | Value |
| --- | ---: |
| Warmup | 16.48 s |
| TTFA, chunk 4 | 302 ms +/- 25 |
| TTFA, chunk 8 primary | 375 ms +/- 17 |
| TTFA, chunk 12 | 455 ms +/- 16 |
| Dynamic-cache baseline TTFA | 4338 ms +/- 58 |
| Dynamic-cache baseline inverse RTF | 0.154 +/- 0.001 |
| Fast path TTFA | 398 ms +/- 49 |
| Fast path inverse RTF | 2.589 +/- 0.056 |
| Fast path local RTF | 0.386 |

### Official Benchmark Interpretation

The official v0.3.2 benchmark reproduces the same class of result as the local
direct harness. This rules out the local harness as the main reason for the
gap.

The PR #112 stack helps, especially TTFA:

| Comparison | v0.3.2 | PR #112 | Delta |
| --- | ---: | ---: | ---: |
| Primary TTFA, chunk 8 | 424 ms | 375 ms | -49 ms |
| Fast path TTFA | 439 ms | 398 ms | -41 ms |
| Fast path inverse RTF | 2.507 | 2.589 | +3.3% |
| Fast path local RTF | 0.399 | 0.386 | -3.3% |

That is useful but not enough to reach the README's reported RTX 4090 class
of roughly `174 ms` TTFA and inverse RTF `4.22`.

At this stage, before the deeper profiling below, the working diagnosis was:

```text
official benchmark/config mismatch: unlikely
PR #112 hot-path fixes missing: only a partial cause
native Windows/WDDM or runtime launch overhead: leading hypothesis
torch/cu runtime difference: unlikely after 2.10/cu128 control
GPU clocks under load: still unrecorded
```

The later profiling below keeps that OS/launch-overhead hypothesis alive, but
also isolates codec decode and wrapper synchronization as a separate end-to-end
throughput loss.

### Official Torch 2.10/cu128 Control

The same `.venv-faster-qwen` environment was switched from `torch 2.11.0+cu130`
to:

```text
torch 2.10.0+cu128
torchaudio 2.10.0+cu128
CUDA runtime 12.8
```

The benchmark code stayed unchanged.

Official v0.3.2, `torch 2.10.0+cu128`:

| Metric | Value |
| --- | ---: |
| Warmup | 16.71 s |
| TTFA, chunk 4 | 350 ms +/- 40 |
| TTFA, chunk 8 primary | 417 ms +/- 15 |
| TTFA, chunk 12 | 499 ms +/- 14 |
| Dynamic-cache baseline TTFA | 4499 ms +/- 138 |
| Dynamic-cache baseline inverse RTF | 0.150 +/- 0.002 |
| Fast path TTFA | 417 ms +/- 13 |
| Fast path inverse RTF | 2.485 +/- 0.075 |
| Fast path local RTF | 0.402 |

Official PR #112 stack, `torch 2.10.0+cu128`:

| Metric | Value |
| --- | ---: |
| Warmup | 16.57 s |
| TTFA, chunk 4 | 310 ms +/- 36 |
| TTFA, chunk 8 primary | 378 ms +/- 15 |
| TTFA, chunk 12 | 459 ms +/- 14 |
| Dynamic-cache baseline TTFA | 4426 ms +/- 59 |
| Dynamic-cache baseline inverse RTF | 0.152 +/- 0.002 |
| Fast path TTFA | 372 ms +/- 3 |
| Fast path inverse RTF | 2.633 +/- 0.047 |
| Fast path local RTF | 0.380 |

Torch/CUDA comparison:

| Code | Torch/CUDA | Primary TTFA | Fast TTFA | Fast inverse RTF | Fast local RTF |
| --- | --- | ---: | ---: | ---: | ---: |
| v0.3.2 | 2.11/cu130 | 424 ms | 439 ms | 2.507 | 0.399 |
| v0.3.2 | 2.10/cu128 | 417 ms | 417 ms | 2.485 | 0.402 |
| PR #112 | 2.11/cu130 | 375 ms | 398 ms | 2.589 | 0.386 |
| PR #112 | 2.10/cu128 | 378 ms | 372 ms | 2.633 | 0.380 |

`torch 2.10/cu128` does not explain the gap to the published RTX 4090 result.
It is roughly equivalent to `torch 2.11/cu130` in these native Windows runs.
PR #112 remains modestly helpful in both runtimes.

### Clean v0.3.2 + PR #108-#112 Stack

The PR worktree used above reported package metadata `0.2.6`, so a clean
control stack was created from `v0.3.2` and the five upstream PR commits were
cherry-picked onto it:

```text
C:/_repoz/faster-qwen3-tts-v032-stack112-clean
base v0.3.2 a70afc0
PR commits: fc17e88, 7a843c2, 94e2219, 3653924, 2004275
local stack tip: afa6120
```

The clean stack reports `faster_qwen3_tts.__version__ == 0.3.2` and was
installed into `.venv-faster-qwen` with `pip install --no-deps -e`.

Official upstream benchmark, clean stack, `torch 2.10.0+cu128`:

| Metric | Value |
| --- | ---: |
| Warmup | 16.11 s |
| TTFA, chunk 4 | 299 ms +/- 26 |
| TTFA, chunk 8 primary | 373 ms +/- 14 |
| TTFA, chunk 12 | 451 ms +/- 14 |
| Dynamic-cache baseline TTFA | 4243 ms +/- 56 |
| Dynamic-cache baseline inverse RTF | 0.160 +/- 0.001 |
| Fast path TTFA | 397 ms +/- 57 |
| Fast path inverse RTF | 2.604 +/- 0.097 |
| Fast path local RTF | 0.384 |

This confirms that the PR stack is useful and reproducible, but still not
enough to reach the README's reported RTX 4090 result.

### Faster-Qwen Profiling

New diagnostic scripts:

```text
scripts/faster-qwen-profile-next.py
scripts/faster-qwen-profile-codec-split.py
scripts/faster-qwen-profile-adaptive-chunks.py
```

All profiling below used the clean stack, upstream benchmark text and
reference audio, `attn_implementation=eager`, `dtype=bfloat16`,
`max_seq_len=2048` unless noted, and `torch 2.10.0+cu128`.

Raw JSON artifacts for the corrected seed-controlled pass are committed under:

```text
docs/benchmark-artifacts/rtx4090-2026-07-22/
```

Per-`next(generator)` profile, wrapper streaming path, `chunk_size=8`:

| Position | Count | Wall median | Prefill median | AR median | Outside median | Audio |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| First | 20 | 369 ms | 125 ms | 160 ms | 84 ms | 640 ms |
| Steady | 174 | 222 ms | 0 ms | 157 ms | 66 ms | 640 ms |
| Final | 17 | 104 ms | 0 ms | 31 ms | 70 ms | 160 ms |

`outside_ms` is the wall time not accounted for by prefill or AR decode timing.
It is mostly wrapper and codec work, plus any synchronization not included in
the internal timing dict.

Raw-code versus codec split:

| Phase | Median |
| --- | ---: |
| Prepare generation | 6.2 ms |
| Raw code generation wall | 1854 ms |
| Raw code AR decode | 1719 ms |
| Raw code inverse RTF, waveform duration | 3.78 |
| Raw code inverse RTF, 12.5 Hz step estimate | 3.78 |
| Codec decode wall | 829 ms |
| Codec decode inverse RTF | 8.40 |

The earlier `3.98` raw-code inverse RTF used `steps / 12.0`, which is not
directly comparable to the upstream waveform-based benchmark. The corrected
metric uses actual decoded waveform samples, with a 12.5 Hz step estimate kept
only as a diagnostic cross-check.

The local AR decode-only path is numerically close to the README's reported
end-to-end inverse RTF `4.22`, but the local raw-code wall metric is still about
`3.78`. Codec decode, wrapper work, and synchronization explain a large
additional loss from raw code to the official end-to-end `2.60-2.63` class, but
they are not the only remaining gap to the author's result.

`max_seq_len` sweep with the same `chunk_size=8` profile:

| max_seq_len | First wall | First prefill | First AR | Steady wall | Steady AR |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2048 | 362 ms | 133 ms | 151 ms | 220 ms | 156 ms |
| 1024 | 365 ms | 138 ms | 148 ms | 219 ms | 156 ms |
| 768 | 370 ms | 128 ms | 151 ms | 221 ms | 157 ms |
| 512 | 365 ms | 125 ms | 152 ms | 217 ms | 156 ms |

Reducing `max_seq_len` does not materially improve this workload. Static cache
size is not the next obvious lever for the tested text length.

Adaptive decode experiment:

| Mode | First wall | First audio | Total inverse RTF | Total local RTF | Chunks |
| --- | ---: | ---: | ---: | ---: | ---: |
| Fixed wrapper `chunk_size=8` | 369 ms | 640 ms | 2.60 | 0.38 | about 10-12 |
| Adaptive `4 -> 12` corrected | 293 ms | 320 ms | 2.82 | 0.35 | 8.5 |

The adaptive script still asks the low-level generator to produce internal
4-step chunks, then combines them before codec decode. It is therefore an
experiment, not a production implementation. The corrected pass includes
`_prepare_generation()` in the first-chunk timer, flushes any remaining pending
frames after producer completion, marks the terminal output chunk after
`StopIteration`, and asserts `generated_steps == emitted_steps`. With those
guards, `4 -> 12` still improves TTFA and throughput together, which makes an
adaptive worker chunking policy worth prototyping behind an experimental flag
if this backend is integrated.

Unified schedule benchmark, same harness, same seed series, no codec hashing in
the timed performance path:

| Schedule | First median | First p95 | Inverse RTF | Min reserve margin | p05 reserve margin | Median reserve margin | Reserve violations |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Fixed 8 | 367 ms | 375 ms | 2.62 | 317 ms | 350 ms | 354 ms | 0 |
| Fixed 12 | 451 ms | 458 ms | 2.87 | 553 ms | 585 ms | 591 ms | 0 |
| `4 -> 12` | 293 ms | 300 ms | 2.82 | -82 ms | -52 ms | -46 ms | 1/run |
| `4 -> 8 -> 12` | 291 ms | 344 ms | 2.80 | -3 ms | 25 ms | 33 ms | 1 worst-case run |

The reserve margin uses a 50 ms transport/playback safety reserve. Negative
values mean the next chunk may arrive too late for a live bridge even though the
mean throughput is faster than real-time. `4 -> 12` is therefore not suitable as
a production schedule. `4 -> 8 -> 12` is the better next adaptive candidate, but
it still needs a true low-level variable scheduler and boundary-quality checks.

A separate 5-run correctness pass with `--hash-codecs` enabled produced
matching codec SHA-256 streams for fixed 8, fixed 12, `4 -> 12`, and
`4 -> 8 -> 12` under the same seed series. That confirms the schedule
comparison above is not comparing different sampled speech.

### Faster Backend Worker Smoke

The worker engine now has an explicit `runtime_backend` selector:

```text
upstream
faster
```

The `faster` path is wired for the bridge-supported CustomVoice and VoiceDesign
model families with fixed `chunk_size=config.emit_every_frames`. Adaptive
chunking remains disabled and experimental.

CustomVoice smoke through `QwenTtsEngine`, not the standalone benchmark:

| Metric | Value |
| --- | ---: |
| Model | `models/Qwen3-TTS-12Hz-0.6B-CustomVoice` |
| Speaker | `ryan` |
| Backend | `faster` |
| Chunk size | 8 |
| Load | 12.74 s |
| Warmup synthesis | 13.57 s |
| First PCM | 330 ms |
| Completed | 1.58 s |
| Audio | 3.92 s |
| Chunks | 7 |
| Inverse RTF | 2.48 |

This smoke confirms the fixed faster backend can serve a mode that the current
bridge protocol already supports. It is not yet a full worker or C++ bridge
benchmark; those remain the next validation levels.

Follow-up smoke validation levels:

| Level | Requests | First PCM boundary | Completed / synthesis | Audio | Chunks | RTF / inverse RTF |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Direct `QwenTtsEngine` | 1 | 330 ms | 1.58 s | 3.92 s | 7 | inverse `2.48` |
| Source worker IPC | 2 | 457 ms / 453 ms | 1.85 s / 1.84 s | 4.24 s / 4.72 s | 7 / 8 | RTF `0.44` / `0.39` |
| C++ example -> source worker | 1 | worker-internal 390 ms | 2.16 s | 5.28 s | 9 | RTF `0.41` |

The worker/C++ runs used a source-tree worker launcher, not the packaged
portable worker. The packaged benchmark still requires rebuilding the worker
distribution with the new source and ensuring `faster-qwen3-tts` is included in
the runtime environment.

These three smoke levels used different texts, request counts, and timing
boundaries. The `qwen_tts_save_wav` smoke above only captured the worker
`request_first_audio` metric printed during a C++ run; it did not timestamp
C++ `synthesize_async()` submit-to-`on_audio` callback latency. Do not infer IPC
or C++ callback overhead from the 330 ms, 453-457 ms, and 390 ms values until a
single-request latency ladder is run with identical text, speaker, warmups, and
measurement boundaries.

Latency ladder, same CustomVoice model, `speaker=ryan`, English text
`This is a faster backend latency benchmark.`, faster backend, fixed chunk size
8, 5 request warmups, 30 measured requests:

| Level | Boundary | First PCM median | First PCM p95 | Completed median | Completed p95 | local RTF median | inverse RTF median |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Direct `QwenTtsEngine` | call `synthesize_stream()` -> first yielded PCM bytes | 337.0 ms | 339.3 ms | 1.44 s | 1.77 s | 0.365 | 2.74 |
| Source worker IPC | client send -> first `AUDIO_PCM` frame, block reader | 341.3 ms | 347.5 ms | 1.35 s | 1.67 s | 0.362 | 2.76 |
| C++ callback benchmark | `synthesize_async()` submit -> first `on_audio` callback | 341.7 ms | 345.1 ms | 1.34 s | 1.62 s | 0.365 | 2.74 |

Artifacts:

```text
docs/benchmark-artifacts/rtx4090-2026-07-22/latency-ladder-direct-engine-faster-customvoice-chunk8-r30-v2.json
docs/benchmark-artifacts/rtx4090-2026-07-22/latency-ladder-source-worker-ipc-faster-customvoice-chunk8-r30-block-reader.json
docs/benchmark-artifacts/rtx4090-2026-07-22/latency-ladder-cpp-callback-faster-customvoice-chunk8-r30-paired.json
```

The earlier source-worker IPC artifact
`latency-ladder-source-worker-ipc-faster-customvoice-chunk8-r30.json` is
invalidated for performance analysis: its test harness read stdout through
`read(1)`, which inflated client-side parser overhead. The corrected block
reader uses 64 KiB stdout reads.

The paired C++ artifact joins C++ callback timing with worker telemetry by
`request_id`. The measured `transport_dispatch_residual_ms` was:

| Metric | Value |
| --- | ---: |
| median | 0.409 ms |
| p90 | 0.490 ms |
| p95 | 0.502 ms |
| max | 0.544 ms |

This is below the 5 ms threshold, so the stdio IPC / C++ dispatch track is
closed for now. Future performance work should not subtract medians from
separate runs; use paired request telemetry when transport cost matters.

Worker readiness semantics were also corrected: a no-op warmup now reports
`warmed_up=false`. For faster backend production startup, use
`--warmup-synthesis` with a valid speaker/instruction so CUDA graph capture is
paid before `ready`; otherwise the first real user request after `ready` may
include the graph-capture cost. In these ladder runs, the first benchmark warmup
request intentionally absorbed that lazy capture and was excluded from the 30
measured steady-state requests.

Ready warmup smoke, source worker through C++, faster CustomVoice, `speaker=ryan`,
`--warmup-synthesis`, no benchmark warmups, 5 measured requests:

| Metric | Value |
| --- | ---: |
| `engine_warmed_up.duration_ms` | 13.75 s |
| `worker_runtime_started.startup_ms` | 27.68 s |
| ready `warmed_up` | true |
| first user request TTFA | 433.0 ms |
| first user request completed | 2.26 s |
| TTFA median / p95 across 5 requests | 384.0 ms / 423.4 ms |

Artifact:

```text
docs/benchmark-artifacts/rtx4090-2026-07-22/cpp-faster-customvoice-ready-warmup-callback-r5.json
docs/benchmark-artifacts/rtx4090-2026-07-22/cpp-faster-customvoice-ready-warmup-callback-r5.stderr.txt
```

Portable packaging now has an explicit faster backend opt-in:

```powershell
.\scripts\setup-python-packaging.ps1 `
    -UseVenv `
    -InstallQwenFork `
    -InstallFasterQwen `
    -FasterQwenSourcePath C:\_repoz\faster-qwen3-tts-v032-stack112-clean

.\scripts\package-python-worker.ps1 `
    -UseVenv `
    -IncludeQwenFork `
    -IncludeFasterQwen `
    -FasterQwenSourcePath C:\_repoz\faster-qwen3-tts-v032-stack112-clean
```

`package-python-worker.ps1 -DryRun -IncludeQwenFork -IncludeFasterQwen` now
resolves both source trees and the staged isolation probe imports
`faster_qwen3_tts` when requested. This avoids relying on editable `.pth` links
from the packaging environment.

A real non-DryRun portable worker build was also performed with
`-Clean -IncludeQwenFork -IncludeFasterQwen`. It built and staged local wheels
for the bridge worker, the Qwen fork, and `faster-qwen3-tts`, then passed:

```text
scripts/test-portable-python-worker.ps1 -UseVenv
dist/QwenTTSBridge/worker-python/python/python.exe -P -s -c "import faster_qwen3_tts, qwen_tts, torch"
```

Portable runtime versions:

| Package | Version |
| --- | --- |
| Python | 3.11.9 |
| torch | 2.11.0+cu126 |
| faster-qwen3-tts | 0.3.2 |

Real packaged faster CustomVoice validation:

| Level | Requests | TTFA median | TTFA p95 | Completed median | local RTF median | residual p95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Portable worker Python harness | 5 | 407.0 ms | 450.1 ms | 1.76 s | 0.419 | N/A |
| Portable worker C++ callback | 5 | 402.1 ms | 414.8 ms | 1.70 s | 0.419 | 0.519 ms |

Artifacts:

```text
docs/benchmark-artifacts/rtx4090-2026-07-22/latency-ladder-portable-worker-faster-customvoice-chunk8-r5.json
docs/benchmark-artifacts/rtx4090-2026-07-22/latency-ladder-portable-cpp-faster-customvoice-chunk8-r5.json
```

This validates the packaged faster backend functionally, but it is not the
fastest runtime matrix: the portable environment currently uses torch
`2.11.0+cu126`, while the best source-tree benchmark above used
`.venv-faster-qwen` with torch `2.10.0+cu128`.

2026-07-23 follow-up hardening:

- `verify_packaged_worker.py` now accepts `--expect-warmed-up auto|true|false`.
  In `auto`, mock expects `true`, Qwen without `--warmup-synthesis` expects
  `false`, and Qwen with real synthesis warmup expects `true`.
- Qwen synthesis warmup now fails startup if a warmup pass produces zero chunks
  or zero bytes.
- `--warmup-synthesis-passes` allows representative multi-pass startup warmup.
  The worker emits both aggregate `engine_warmed_up` and per-pass
  `engine_warmup_pass` metrics.
- `benchmark_packaged_worker_restart.py` measures first user request latency
  across fresh worker processes.
- Portable packaging now refuses dirty source trees by default, supports
  `-AllowDirtySources` for local diagnostic builds, retains exact wheels under
  `worker-python/wheels`, and writes a richer `build-manifest.json` with
  Python/tool versions, torch CUDA metadata, staged `pip freeze`, wheel hashes,
  source commits, and sanitized source path labels.

A fresh portable worker build at bridge commit
`891ac444c843ee20ad46b72ed3d63d02db1a26e2` produced retained wheels:

| Wheel | SHA-256 |
| --- | --- |
| `qwen_tts_bridge_worker-0.2.0-py3-none-any.whl` | `5d230825e2007d4dabbeea55e71647b1fbba1cb6f3ba8f08e828e58303e049cc` |
| `qwen_tts-0.0.4-py3-none-any.whl` | `6e93be5ea8e5284cd8e5a7d65f1361561abf281814aaf538aaf1a01c3b3980b3` |
| `faster_qwen3_tts-0.3.2-py3-none-any.whl` | `b7429f3e15a0c2e43b9f769f2552bb5cb95cd90f3db106fb218bf252a3c7a31c` |

The rebuilt packaged worker passed the mock packaged smoke and imported
`faster_qwen3_tts`, `qwen_tts`, and torch from the staged runtime:

```text
faster=0.3.2; torch=2.11.0+cu126; cuda=12.6
```

Restart-based first-user-after-ready benchmark, source worker on the same
torch `2.11.0+cu126` runtime, fixed chunk size 8, two synthesis warmup passes,
20 fresh worker processes:

| Metric | Median | p95 | Max |
| --- | ---: | ---: | ---: |
| first PCM | 425.7 ms | 485.2 ms | 486.2 ms |
| completed | 1.85 s | 2.26 s | 2.35 s |
| local RTF | 0.475 | 0.499 | 0.505 |
| inverse RTF | 2.105 | 2.246 | 2.359 |

This does **not** meet the tentative acceptance target of first-user p95 within
20 ms of steady-state p95. The same-runtime steady-state source worker run
below measured first PCM p95 `422.5 ms`, so restart p95 is about `+62.6 ms`.
Two-pass warmup improves honesty and reproducibility, but it still does not
fully guarantee steady-state first-user latency.

Source-vs-portable parity, same torch `2.11.0+cu126` runtime shape, two startup
warmup synthesis passes, 5 request warmups, 30 measured requests:

| Level | TTFA median | TTFA p95 | Completed median | Completed p95 | local RTF median |
| --- | ---: | ---: | ---: | ---: | ---: |
| Source worker | 404.2 ms | 422.5 ms | 1.54 s | 1.96 s | 0.409 |
| Portable worker | 408.5 ms | 431.5 ms | 1.52 s | 2.07 s | 0.410 |

Portable TTFA and median local RTF are within the 5% parity target. Packaging is
not a meaningful performance bottleneck in this controlled comparison.

Artifacts:

```text
docs/benchmark-artifacts/rtx4090-2026-07-22/restart-first-user-source-worker-faster-customvoice-chunk8-r20.json
docs/benchmark-artifacts/rtx4090-2026-07-22/parity-source-worker-faster-customvoice-chunk8-r30.json
docs/benchmark-artifacts/rtx4090-2026-07-22/parity-portable-worker-faster-customvoice-chunk8-r30.json
dist/QwenTTSBridge/worker-python/build-manifest.json
dist/QwenTTSBridge/worker-python/wheels/
```

Paired restart probes, same source worker and torch `2.11.0+cu126`, fixed
seed `4242`, four user requests per fresh worker process:

| Run | Processes | First TTFA median | First TTFA p95 | Steady TTFA median | Steady TTFA p95 | First-minus-steady median | First-minus-steady p95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| unrestricted | 50 | 414.3 ms | 467.3 ms | 363.1 ms | 412.4 ms | 51.8 ms | 86.2 ms |
| bounded warmup pass 2 to 2 chunks | 20 | 443.3 ms | 478.3 ms | 398.2 ms | 415.6 ms | 54.7 ms | 75.9 ms |
| affinity CPUs 0-21 | 20 | 415.2 ms | 464.7 ms | 362.1 ms | 404.4 ms | 53.6 ms | 71.2 ms |
| affinity CPUs 22-43 | 20 | 428.3 ms | 449.6 ms | 374.0 ms | 392.8 ms | 54.9 ms | 57.8 ms |

The paired result confirms two effects rather than a single vague "cold
process" penalty:

- The first user request after two synthesis warmup passes still costs roughly
  `+50 ms` over the median of requests 2-4 in the same worker process.
- Steady requests also have placement-sensitive tails. CPU affinity reduces
  the worst steady-state tail in this sample, especially on CPUs `22-43`, but
  it does not remove the first-request delta.
- Bounding the second synthesis warmup to only two chunks saves about one
  second of startup work, but worsens first-user TTFA. Keep bounded warmup
  experimental; two full warmup passes remain the safer default for latency
  measurements.

Runtime A/B on the same paired restart shape did not find a `torch 2.10/cu128`
win for CustomVoice:

| Runtime | Python | Processes | First TTFA median | First TTFA p95 | Steady TTFA median | Steady TTFA p95 | First-minus-steady median |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| torch `2.11.0+cu126` | 3.11.9 | 50 | 414.3 ms | 467.3 ms | 363.1 ms | 412.4 ms | 51.8 ms |
| torch `2.10.0+cu128` | 3.12.10 | 20 | 432.5 ms | 478.2 ms | 378.7 ms | 418.5 ms | 55.5 ms |

The earlier direct benchmark control already made the runtime gap unlikely.
This paired worker control reinforces that conclusion: switching the product
worker from `2.11/cu126` to `2.10/cu128` is not an obvious latency fix.

First-frame pipeline instrumentation was added to the restart benchmark after
commit `5177566`. A 5-process / 4-requests source-worker probe on
`torch 2.11.0+cu126` measured:

| Pipeline metric | Median | p95 | Max |
| --- | ---: | ---: | ---: |
| client first-audio minus worker first PCM ready | 1.04 ms | 1.23 ms | 1.27 ms |
| client first-audio minus worker first frame enqueued | 0.94 ms | 1.14 ms | 1.17 ms |
| client first-audio minus worker first frame flushed estimate | 0.66 ms | 0.77 ms | 0.92 ms |
| first frame output writer | 0.23 ms | 0.41 ms | 0.56 ms |

This rules out first-frame stdio/framing delivery as the main source of the
`+50 ms` first-user-after-ready penalty. The remaining latency is already
present when the worker sees the first PCM chunk as ready, so the next useful
optimization target is inside the engine path before first PCM, not the
worker-to-client transport.

2026-07-23 startup-thread A/B:

The first-user penalty was traced to startup warmup running on a different host
thread than production inference. The benchmark used `30` fresh worker
processes, `4` requests per process, `--seed-mode fixed`, `--warmup-seed 4242`,
and the retained `faster_qwen3_tts-0.3.2` wheel installed in
`.venv-packaging`.

| Startup mode | Load thread | Warmup thread | Request thread | First TTFA median | First TTFA p95 | Steady TTFA median | Steady TTFA p95 | First-minus-steady median | First-minus-steady p95 |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `main` | main | main | `qtb-engine` | 425.1 ms | 475.1 ms | 378.1 ms | 419.4 ms | 52.5 ms | 65.5 ms |
| `engine_warmup` | main | `qtb-engine` | `qtb-engine` | 378.5 ms | 420.3 ms | 396.0 ms | 414.6 ms | 3.0 ms | 17.8 ms |
| `engine_load_warmup` | `qtb-engine` | `qtb-engine` | `qtb-engine` | 370.0 ms | 421.4 ms | 382.8 ms | 417.5 ms | 1.4 ms | 15.1 ms |

Both engine-thread startup variants meet the acceptance target of
first-user-minus-steady p95 `<= 20 ms`. The most important change is moving
synthesis warmup into the same `qtb-engine` thread that handles user requests.
Moving model load there as well is slightly better in this sample, but the
large effect is already present in `engine_warmup`.

First-chunk phase metrics also improved the diagnosis. The non-engine
transport/dispatch residual stayed around `1 ms`, while the old `main` startup
mode had a much larger first-chunk codec/wrapper residual tail:

| Startup mode | Transport/dispatch residual median | First prefill median | First AR decode median | First codec/wrapper residual median |
| --- | ---: | ---: | ---: | ---: |
| `main` | 1.04 ms | 140.6 ms | 156.3 ms | 74.8 ms |
| `engine_warmup` | 1.05 ms | 140.7 ms | 156.0 ms | 71.5 ms |
| `engine_load_warmup` | 1.05 ms | 142.1 ms | 156.3 ms | 72.0 ms |

The phase medians are close; the paired distribution is the decisive signal.
The production default should move Qwen synthesis warmup to the engine thread
before spending effort on codec rewrites for first-user latency.

2026-07-23 warmup-depth matrix:

After `auto` was changed to resolve Qwen startup to `engine_warmup`, the next
probe tested whether extra startup warmup passes further reduce the
first-user-after-ready tail. Each row used `30` fresh worker processes,
`4` requests per process, fixed request seed `4242`, fixed warmup seed `4242`,
`emit_every_frames=8`, the source worker on `.venv-packaging`, and the retained
`faster_qwen3_tts-0.3.2` wheel. No explicit `--engine-startup-mode` was passed;
the runtime metrics confirm `auto -> engine_warmup` for Qwen.

| Warmup shape | Startup median | First TTFA median | First TTFA p95 | Steady TTFA median | Steady TTFA p95 | First-minus-steady median | First-minus-steady p90 | First-minus-steady p95 | Slow deltas `>20 ms` |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 full synthesis | 28.78 s | 360.2 ms | 413.9 ms | 357.4 ms | 411.4 ms | 2.1 ms | 5.8 ms | 20.6 ms | 2 / 30 |
| 1 full + 1 chunk | 29.43 s | 371.8 ms | 424.1 ms | 373.2 ms | 419.1 ms | 0.9 ms | 30.8 ms | 40.6 ms | 5 / 30 |
| 1 full + 2 chunks | 29.57 s | 368.4 ms | 427.3 ms | 368.8 ms | 420.4 ms | 2.2 ms | 16.6 ms | 21.2 ms | 3 / 30 |
| 2 full syntheses | 30.48 s | 367.1 ms | 425.8 ms | 367.7 ms | 421.9 ms | 1.2 ms | 14.5 ms | 31.3 ms | 3 / 30 |

The extra bounded and full passes do not improve the tail in this sample.
The lowest-cost production candidate is therefore `engine_warmup` with one
representative full synthesis warmup. It is slightly over the tentative
`<= 20 ms` p95 target here (`20.6 ms`), but the excess is one borderline
sample, while additional passes made the tail worse. Keep multi-pass and
bounded warmup as experimental controls until a larger randomized confirmatory
run says otherwise.

The follow-up `100`-process confirmation kept the same one-full-synthesis
`auto -> engine_warmup` shape and added observable partial/progress artifacts
outside git while running. Runtime provenance was clean at bridge commit
`95aef9f`, and the installed `faster_qwen3_tts` package was correctly reported
as a retained wheel rather than as a bridge source checkout:

```text
faster_qwen3_tts-0.3.2-py3-none-any.whl
sha256 b7429f3e15a0c2e43b9f769f2552bb5cb95cd90f3db106fb218bf252a3c7a31c
```

| Run shape | Processes | Startup median | First TTFA median | First TTFA p95 | Steady TTFA median | Steady TTFA p95 | First-minus-steady median | First-minus-steady p90 | First-minus-steady p95 | Slow deltas `>20 ms` |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 full synthesis, fixed seed | 30 | 28.78 s | 360.2 ms | 413.9 ms | 357.4 ms | 411.4 ms | 2.1 ms | 5.8 ms | 20.6 ms | 2 / 30 |
| 1 full synthesis, fixed seed | 100 | 28.57 s | 362.8 ms | 386.3 ms | 361.3 ms | 374.5 ms | 1.2 ms | 12.7 ms | 22.4 ms | 6 / 100 |
| 1 full synthesis, varied seed step 1009 | 30 | 28.15 s | 362.2 ms | 393.5 ms | 358.0 ms | 377.7 ms | 2.7 ms | 13.4 ms | 30.2 ms | 3 / 30 |
| 1 full synthesis, fixed per-run seed step 1009, warmup seed steps too | 100 | 28.50 s | 367.3 ms | 420.8 ms | 363.2 ms | 414.0 ms | 3.3 ms | 32.4 ms | 46.8 ms | 15 / 100 |
| 1 full synthesis, fixed per-run seed step 1009, warmup seed fixed | 100 | 28.96 s | 365.2 ms | 423.5 ms | 364.4 ms | 412.9 ms | 1.6 ms | 41.6 ms | 45.5 ms | 21 / 100 |

The `r100` result confirms the direction but not the strict acceptance target.
Moving warmup to the engine thread removes the old systematic `+50 ms` first
request penalty, but rare first-user tails remain. The paired phase deltas
point mostly at prefill/setup variance (`p95 +22.4 ms`) with codec/wrapper
residual still a smaller but persistent median cost (`+4.6 ms`). Treat
one-pass `engine_warmup` as the best current product default, not as the end of
the latency investigation. The varied-seed control makes that conclusion
stronger: different reproducible per-run seeds raised the first-minus-steady
p95 to `30.2 ms`, again with the largest paired tail in prefill/setup.

The later clean varied-seed `r100` controls used `--seed-mode fixed` so each
worker process kept one seed across warmup and all four user requests, while
the process seed advanced by `1009`. Whether the warmup seed advanced with the
process or stayed fixed at `4242`, the first-minus-steady p95 landed around
`45-47 ms`. The new provenance guard confirmed the installed
`faster_qwen3_tts` archive hash matched the retained wheel hash. The paired
correlation between total first-minus-steady delta and prefill delta was strong
in both runs (`r=0.87` and `r=0.89`), while transport/dispatch p95 stayed under
`0.3 ms`. That makes seed-dependent prefill/setup variance the next target; a
warmup-seed mismatch is not enough to explain the remaining tail.

Input-shape matrix, one fixed medium full synthesis warmup, fixed seed within
each process, per-process seed step `1009`, and deterministic shuffled schedule
`input-shape-r50-each-seed20260723.jsonl`:

| Shape | Text chars | Processes | Startup median | First TTFA median | First TTFA p95 | Steady TTFA median | Steady TTFA p95 | First-minus-steady median | First-minus-steady p90 | First-minus-steady p95 | Slow deltas `>20 ms` |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| short | 20 | 50 | 28.79 s | 360.3 ms | 409.6 ms | 355.0 ms | 403.5 ms | 4.7 ms | 11.5 ms | 19.2 ms | 3 / 50 |
| medium | 43 | 50 | 28.79 s | 403.3 ms | 424.1 ms | 392.3 ms | 412.3 ms | 2.5 ms | 24.7 ms | 39.2 ms | 7 / 50 |
| long | 161 | 50 | 28.79 s | 400.8 ms | 431.5 ms | 372.2 ms | 412.0 ms | 18.3 ms | 51.8 ms | 53.1 ms | 17 / 50 |
| very_long | 391 | 50 | 28.79 s | 378.2 ms | 422.1 ms | 365.3 ms | 410.2 ms | 5.3 ms | 24.1 ms | 43.3 ms | 8 / 50 |

The larger shuffled matrix confirms that prompt shape can expose first-user
tails, but not as a simple monotonic function of character count. The overall
correlation between total first-minus-steady delta and text characters was only
`r=0.05`, while total delta vs prefill delta stayed high at `r=0.85`.
The `long` shape was the worst case here (`17 / 50` slow deltas, p95
`53.1 ms`), even though `very_long` had more characters. That points again to
the model/backend prefill path and generated prompt/cache behavior rather than
to C++ transport, Python framing, or raw text length alone.

Artifacts:

```text
docs/benchmark-artifacts/rtx4090-2026-07-22/paired-restart-source-worker-faster-customvoice-chunk8-r50x4-seed4242.json
docs/benchmark-artifacts/rtx4090-2026-07-22/paired-restart-source-worker-faster-customvoice-chunk8-r20x4-seed4242-capture-full-bounded2.json
docs/benchmark-artifacts/rtx4090-2026-07-22/paired-restart-source-worker-faster-customvoice-chunk8-r20x4-seed4242-affinity-0-21.json
docs/benchmark-artifacts/rtx4090-2026-07-22/paired-restart-source-worker-faster-customvoice-chunk8-r20x4-seed4242-affinity-22-43.json
docs/benchmark-artifacts/rtx4090-2026-07-22/paired-restart-source-worker-faster-customvoice-chunk8-r20x4-seed4242-torch210-cu128.json
docs/benchmark-artifacts/rtx4090-2026-07-22/paired-restart-source-worker-faster-customvoice-chunk8-r5x4-seed4242-pipeline.json
docs/benchmark-artifacts/rtx4090-2026-07-22/paired-restart-source-worker-faster-customvoice-chunk8-r30x4-seed4242-fixed-main-startup.json
docs/benchmark-artifacts/rtx4090-2026-07-22/paired-restart-source-worker-faster-customvoice-chunk8-r30x4-seed4242-fixed-engine-warmup.json
docs/benchmark-artifacts/rtx4090-2026-07-22/paired-restart-source-worker-faster-customvoice-chunk8-r30x4-seed4242-fixed-engine-load-warmup.json
docs/benchmark-artifacts/rtx4090-2026-07-22/paired-restart-source-worker-faster-customvoice-chunk8-r30x4-seed4242-auto-warmup1full.json
docs/benchmark-artifacts/rtx4090-2026-07-22/paired-restart-source-worker-faster-customvoice-chunk8-r30x4-seed4242-auto-warmup1full-plus1chunk.json
docs/benchmark-artifacts/rtx4090-2026-07-22/paired-restart-source-worker-faster-customvoice-chunk8-r30x4-seed4242-auto-warmup1full-plus2chunks.json
docs/benchmark-artifacts/rtx4090-2026-07-22/paired-restart-source-worker-faster-customvoice-chunk8-r30x4-seed4242-auto-warmup2full.json
docs/benchmark-artifacts/rtx4090-2026-07-22/paired-restart-source-worker-faster-customvoice-chunk8-r100x4-seed4242-auto-warmup1full.json
docs/benchmark-artifacts/rtx4090-2026-07-22/paired-restart-source-worker-faster-customvoice-chunk8-r30x4-varseed4242-step1009-auto-warmup1full.json
docs/benchmark-artifacts/rtx4090-2026-07-22/paired-restart-source-worker-faster-customvoice-chunk8-r100x4-seed4242-step1009-fixed-auto-warmup1full.json
docs/benchmark-artifacts/rtx4090-2026-07-22/paired-restart-source-worker-faster-customvoice-chunk8-r100x4-seed4242-step1009-warmupseed4242-fixed-auto-warmup1full.json
docs/benchmark-artifacts/rtx4090-2026-07-22/input-shape-r50-each-seed20260723.jsonl
docs/benchmark-artifacts/rtx4090-2026-07-22/paired-restart-source-worker-faster-customvoice-chunk8-r50each-shuffled-shapes-seed20260723-fixed-auto-warmup1medium.json
docs/benchmark-artifacts/rtx4090-2026-07-22/paired-restart-source-worker-faster-customvoice-chunk8-r10x4-shape-short-seed4242-auto-warmup1full.json
docs/benchmark-artifacts/rtx4090-2026-07-22/paired-restart-source-worker-faster-customvoice-chunk8-r10x4-shape-medium-seed4242-auto-warmup1full.json
docs/benchmark-artifacts/rtx4090-2026-07-22/paired-restart-source-worker-faster-customvoice-chunk8-r10x4-shape-long-seed4242-auto-warmup1full.json
```

Updated diagnosis after profiling:

```text
official benchmark/config mismatch: unlikely
PR #112 hot-path fixes missing: ruled out as main cause
torch/cu runtime difference: unlikely after 2.10/cu128 control
max_seq_len/cache size: unlikely for this workload
codec decode and wrapper synchronization: confirmed meaningful overhead
first-frame stdio/framing delivery: ruled out as main first-user TTFA cause
first-user-after-ready latency: caused primarily by main-thread warmup mismatch
engine-thread one-pass synthesis warmup: best current default, but p95 target
  still misses slightly in r100
extra bounded/full warmup passes: rejected as latency defaults
CPU affinity: helps steady-state tails but is not a complete fix
prefill/setup variance: next first-user latency target after startup-thread fix,
  especially under varied seeds; clean r100 controls show p95 around 45-47 ms
  and strong total-delta vs prefill-delta correlation
long prompt shape: confirmed worst of the shuffled r50-per-shape matrix, but
  total delta does not correlate strongly with raw character count
prefill/setup and raw AR still need separate work to reach author's end-to-end
native Windows/WDDM plus older CPU launch overhead: still plausible for raw AR gap
GPU clocks under sustained benchmark load: still not recorded cleanly
adaptive 4->12 playback reserve: failed, keep experimental only
adaptive 4->8->12 playback reserve: promising but not production-safe yet
```

WSL status:

```text
wsl -l -v
Windows Subsystem for Linux has no installed distributions.
```

Native Windows/WDDM remains a useful control hypothesis for the remaining raw
AR gap. It is no longer the first product blocker: fixed faster backend
integration, codec scheduling, and prefill measurement can proceed on Windows
while a WSL2/Linux A/B is prepared separately.

## External Research

The most relevant new lead is `andimarafioti/faster-qwen3-tts`.

Key points from its README and blog:

- It states that its fast path is the upstream Qwen dynamic-cache path replaced
  by `StaticCache` plus manual `torch.cuda.CUDAGraph` replay.
- It describes Qwen3-TTS decode as two autoregressive transformers per step
  with hundreds of small CUDA kernel launches, where CPU launch overhead can
  dominate.
- Its README currently reports RTX 4090 numbers with the inverse RTF
  convention: 0.6B baseline `0.82` / TTFA `800 ms` vs CUDA Graphs `4.78` /
  TTFA `156 ms`; 1.7B baseline `0.82` / TTFA `850 ms` vs CUDA Graphs `4.22` /
  TTFA `174 ms`.
- Converted to this document's local RTF convention, the reported CUDA Graphs
  throughput is roughly `0.21-0.24`, while the baseline is about `1.22`.
- It recommends precomputing voice-clone speaker embeddings. In x-vector-only
  mode this avoids reference audio at runtime and reduces the prompt path.

NVIDIA's CUDA Graph guidance lines up with that explanation:

- CUDA graphs are most useful when GPU utilization is low and many small
  kernels are launched.
- PyTorch automatic CUDA graphs through `torch.compile(mode="reduce-overhead")`
  can fragment into many small graphs and handle dynamic shapes by capturing new
  graphs. Manual capture can be faster when the workload can be made static.

Observed local worker logs also support this hypothesis. The optimized upstream
fork still warns about dynamic CUDAGraph shape churn:

```text
CUDAGraph supports dynamic shapes by recording a new graph for each distinct input size.
```

## Current Interpretation

Flash-attn is not the main missing multiplier. It removes the import warning
and helps a little when combined with bf16, matmul precision, fast codebook, and
the author's no-manual-cuda-graphs setting. It does not by itself produce the
reported `0.08 s` / `0.20 RTF` class of result.

The bigger gap appears to be the inference engine shape:

```text
upstream Qwen streaming fork
    dynamic cache + torch.compile + automatic/fragmented CUDA graph behavior

faster-qwen3-tts
    StaticCache + fixed-shape buffers + manual CUDA Graph replay
```

That means the next meaningful experiment is not another flash-attn matrix.
There are now two separate tracks:

- Product track: prototype a fixed `faster-qwen3-tts` worker backend behind a
  feature flag, while keeping the existing Qwen backend available. Keep
  adaptive chunking behind a separate experimental flag. `4 -> 12` failed the
  50 ms playback-reserve check; `4 -> 8 -> 12` is the next candidate to test
  with a true low-level scheduler and boundary-quality checks.
- Root-cause track: compare native Windows/WDDM with WSL2/Linux using the same
  official benchmark to find whether CPU launch overhead and driver model
  explain the remaining raw-code gap to the author's RTX 4090 numbers.

## 2026-07-24 Faster Prefill Profiling Smoke

The retained local `faster_qwen3_tts-0.3.2` wheel was rebuilt from
`C:/_repoz/faster-qwen3-tts-v032-stack112-clean` commit `8152612` for the v2
smoke below. A later local faster commit, `f98242e`, updates the profiler
contract to schema v3 with `profile_path=fast|parity`, path-specific
`profile_complete`, explicit missing values as `null`, finite/nonnegative
validation flags, stream-consistency reporting, `prefill_gpu_partition_error_ms`,
and outer NVTX ranges named `qtb_profile_first_user_request` and
`qtb_profile_steady_request`. `prefill_gpu_accounting_error_ms` remains a
temporary compatibility alias for `prefill_gpu_partition_error_ms`.
The faster patch series and a small git bundle from upstream base `afa6120` to
`f98242e` are saved under
`docs/benchmark-artifacts/rtx4090-2026-07-22/faster-qwen3-tts-telemetry-patch/`;
no new full source ZIP is added for v3.
The previous retained wheel SHA256 was
`3f81c8cd1eca91d203913d6befb4ee11d2aa8e38e8c593206bedc8df8db63b03`.
The v3 retained wheel SHA256 is
`b45c21193cad723456fdcb12d8cdad7afb3eeec0bf04c124e5406f6183d43696`.
The bridge now fails restart benchmarks if the installed faster distribution
does not match the retained wheel, so these numbers are tied to the wheel kept
in `dist/QwenTTSBridge/worker-python/wheels/`.

Smoke parameters:

```text
model: models/Qwen3-TTS-12Hz-0.6B-CustomVoice
runtime: source worker, Python .venv-packaging, faster backend
GPU: RTX 4090, native Windows
text: I am your robot. I am your worker.
speaker: ryan
chunk size: 8 frames
warmup: 1 full synthesis pass, seed 4242
run shape: 1 fresh worker x 2 requests
profiling: --profile-prefill
```

Saved artifacts:

- `docs/benchmark-artifacts/rtx4090-2026-07-22/prefill-profile-source-worker-faster-customvoice-chunk8-sampling-r1x2.json`
- `docs/benchmark-artifacts/rtx4090-2026-07-22/prefill-profile-source-worker-faster-customvoice-chunk8-greedy-r1x2.json`
- `docs/benchmark-artifacts/rtx4090-2026-07-22/prefill-profile-v2-source-worker-faster-customvoice-chunk8-sampling-r1x2.json`
- `docs/benchmark-artifacts/rtx4090-2026-07-22/prefill-profile-v2-nvtx-source-worker-faster-customvoice-chunk8-sampling-r1x1.json`
- `docs/benchmark-artifacts/rtx4090-2026-07-22/prefill-profile-v3-source-worker-faster-customvoice-chunk8-sampling-r1x2.json`

Results:

| Mode | First audio, request 1 | First audio, steady | Completed, request 1 | Completed, steady | RTF, request 1 | RTF, steady | text tokens | talker prefill length |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| sampling | 371.793 ms | 354.488 ms | 1681.779 ms | 1665.302 ms | 0.3786 | 0.3749 | 18 | 21 |
| greedy (`--no-sample`) | 346.011 ms | 344.166 ms | 1541.753 ms | 1494.255 ms | 0.3892 | 0.3772 | 18 | 21 |

First-request GPU subphase samples:

| Mode | talker forward GPU | prefill KV GPU | first sample GPU | bridge/dispatch residual | paired delta | accounting error |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| sampling | 136.771 ms | 5.251 ms | 1.250 ms | 1.138 ms | 17.304 ms | 0.129 ms |
| greedy (`--no-sample`) | 121.936 ms | 4.412 ms | 0.322 ms | 1.065 ms | 1.845 ms | 0.031 ms |

Interpretation: this is a diagnostic smoke, not a stable performance table.
It does prove that token counts and talker prefill length now come from the real
faster path instead of fallback retokenization, and that request-to-client
transport/dispatch overhead is around 1 ms for the first chunk in this setup.
The coarse `prefill_ms` bucket is now split enough to show that talker forward
dominates the prefill subphase for this prompt.

The v2 smoke confirms the previously updated profiler schema on the real faster path:
`profile_complete=true`, `profile_schema_version=2`, `prefill_total_gpu_ms`
`147.868`, component sum `147.868`, and accounting error approximately `0 ms`.
The NVTX-enabled wheel also passed a real `r1x1` smoke with `--profile-prefill`.
The v3 smoke confirms the path-specific schema on the real faster path:
`profile_schema_version=3`, `profile_path=fast`, `profile_complete=true`,
`events_complete=true`, `components_finite=true`,
`components_nonnegative=true`, `all_component_streams_equal=true`, request role
`first_user` for request 1, request role `steady` for request 2, and
`prefill_gpu_partition_error_ms` approximately `0 ms`. The saved v3 smoke has
2/2 profiled first chunks complete and stream-consistent; first TTFA was
`427.732 ms`, steady TTFA was `373.957 ms`. This is still a smoke, not a
performance distribution.
`nsys` and `ncu` were not available in `PATH` during the earlier v2 pass, so an
actual Nsight trace is still pending.

A small profile overhead control was also recorded:

- `docs/benchmark-artifacts/rtx4090-2026-07-22/profile-overhead-off-source-worker-faster-customvoice-chunk8-r5x4.json`
- `docs/benchmark-artifacts/rtx4090-2026-07-22/profile-overhead-on-source-worker-faster-customvoice-chunk8-r5x4.json`

Both runs used 5 fresh workers x 4 measured requests, sampling, fixed seed
4242, one full synthesis warmup, and no GPU polling.

| Mode | first TTFA p50 | first TTFA p95 | steady TTFA p50 | steady TTFA p95 | paired delta p50 | paired delta p95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| profile off | 356.059 ms | 405.552 ms | 352.811 ms | 406.624 ms | 4.121 ms | 8.329 ms |
| profile on | 356.495 ms | 409.418 ms | 354.174 ms | 402.557 ms | 5.052 ms | 9.438 ms |

This small control does not show a large profiling overhead. The paired-delta
p95 difference is about `1.1 ms`; first TTFA p95 differs by about `3.9 ms` on
only five fresh workers, so a larger shuffled run is still needed before using
it as a hard acceptance result.

A randomized three-way overhead control was then run with 50 fresh workers per
condition and 4 requests per worker:

- `A_pristine`: upstream faster commit `afa6120`, profile off
- `B_telemetry_profile_off`: telemetry faster commit `f98242e`,
  `profile_prefill=false`
- `C_telemetry_profile_on`: telemetry faster commit `f98242e`,
  `profile_prefill=true`

Saved artifact directory:

- `docs/benchmark-artifacts/rtx4090-2026-07-22/profile-overhead-control-v3-r50x4-randomized-runs/summary.json`

| Comparison | first TTFA median delta | first TTFA p95 delta | steady TTFA median delta | steady TTFA p95 delta | paired delta median delta | paired delta p95 delta |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| B - A | -2.952 ms | +5.295 ms | -2.956 ms | +0.357 ms | +0.360 ms | +3.616 ms |
| C - B | +4.974 ms | -7.606 ms | +2.015 ms | +0.274 ms | -0.796 ms | -12.176 ms |

This r50 control does not show a large overhead, but it does not pass the
strict preliminary thresholds either: B-A first TTFA p95 is `+5.295 ms` versus a
`<=5 ms` target, and C-B first TTFA median is `+4.974 ms` versus a `<=2 ms`
target. Because the profile-on cost is visible in the first-request median, the
next production r100 baseline should not be treated as an acceptance baseline
until either the profiling cost is accepted as small enough for diagnostics or
the v3 profiler is trimmed further.

Nsight Systems was checked after the r50 control. NVIDIA's official download
page listed Nsight Systems `2026.4.1` for Windows x86_64, with local CLI/GUI
support on Windows 10+ hosts. The official MSI URL from
`https://developer.nvidia.com/tools-downloads.json` was:

```text
https://developer.nvidia.com/downloads/assets/tools/secure/nsight-systems/2026_4/NsightSystems-2026.4.1.174-3856861.msi
```

The first `Invoke-WebRequest` attempt timed out after writing a partial
`451,986,258` byte file; the server-reported `Content-Length` was
`560,553,984` bytes. `curl.exe -C -` resumed the download to the expected
size. Silent MSI installation then failed with exit code `1603`; the MSI log
reported: `Setup requires Administrator privileges to install.` Administrative
extract with `msiexec /a` also failed with `1603`. A 7-Zip extraction exposed
MSI payload files including `nsys.exe`, but a flattened scratch copy did not
produce a runnable CLI.

Nsight Systems was later installed manually with administrator privileges.
`nsys --version` reported `2026.4.1.174-264138568610v0`. Two NVTX-bounded
traces were captured with `--trace=cuda,nvtx,wddm --sample=none`; WDDM and CPU
context-switch traces were disabled by Nsight because administrator or
Performance Log Users privileges are still required for those providers in the
profiling process. CUDA+NVTX traces were captured successfully:

- `docs/benchmark-artifacts/rtx4090-2026-07-22/nsight-systems-v3/first-user-prefill.nsys-rep`
- `docs/benchmark-artifacts/rtx4090-2026-07-22/nsight-systems-v3/steady-prefill.nsys-rep`
- `docs/benchmark-artifacts/rtx4090-2026-07-22/nsight-systems-v3/summary.json`

The traces were intentionally captured only around the prefill NVTX ranges, not
the whole benchmark process. `--capture-range-end=stop-shutdown` stops the
target after the captured range, so the redirected stdout files contain Nsight
capture logs rather than complete benchmark JSON reports.

| Trace | outer NVTX range | talker-forward NVTX | CUDA runtime API | CUDA API calls | CUDA GPU kernels+mem | non-GPU/gap bucket |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| first user | 183.198 ms | 173.882 ms | 85.069 ms | 2,982 | 5.966 ms | 177.232 ms |
| steady | 172.315 ms | 163.435 ms | 81.048 ms | 2,982 | 6.014 ms | 166.300 ms |
| first - steady | +10.884 ms | +10.448 ms | +4.021 ms | 0 | -0.048 ms | +10.932 ms |

Interpretation: the first-vs-steady prefill delta is not explained by more GPU
kernel execution. Kernel+mem time is about `6 ms` in both traces. The delta is
inside the host/API/queue/gap region around `talker.forward`: CUDA runtime API
time increases by about `4 ms`, while the broader non-GPU/gap bucket increases
by about `10.9 ms`. This makes a low-level scheduler or graph/compiled prefill
track more plausible than tuning individual CUDA kernels for this particular
first-user tail.

Follow-up `cuda_kern_exec_*` analysis of the same SQLite exports confirmed the
launch-bound shape more directly:

| Trace | launch API calls | launch API sum | CUDA API interval union | kernel count | kernel sum | kernel p95 | talker-forward kernels |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| first user | 2,748 | 82.440 ms | 85.069 ms | 2,748 | 5.936 ms | 0.0074 ms | 2,582 |
| steady | 2,748 | 78.730 ms | 81.048 ms | 2,748 | 5.984 ms | 0.0075 ms | 2,582 |

`non-GPU/gap bucket` should be read as `host_or_unattributed_wall_ms`, not as a
pure queue measurement: it includes CUDA API time, CPU framework dispatch,
possible driver/runtime waits, gaps between API calls, and profiler overhead.
Nsight queue delay from matched correlation IDs did not explain the delta on
these two samples.

### Profile Cleanup And R100

The faster telemetry patch was extended to separate CUDA-event prefill timing
from NVTX ranges:

- `profile_prefill=true` records CUDA events and writes timing fields.
- `profile_nvtx=true` emits NVTX ranges for Nsight capture.
- The mass diagnostic runs use `profile_prefill=true`, `profile_nvtx=false`.
- Profile-off requests now report `profile_status=disabled` instead of looking
  like incomplete profiles.
- Benchmark provenance can now require a condition-specific
  `--expected-faster-wheel-sha256`.

New faster telemetry state:

```text
faster-qwen3-tts telemetry cleanup commit: 71fa0fd
retained cleanup wheel SHA256: 0b3aa64a592daa4d573b500455c27d87df54cdfd41219217bf153ffb2c94d0dc
patch series: faster-qwen3-tts-telemetry-patch/0001-0005-prefill-profile-telemetry-cleanup-series.patch
patch series SHA256: 374937d27ba58762092a7978ff5c82b28871e24b38630b8d6aeb2afcd8a3b8cc
git bundle: faster-qwen3-tts-telemetry-patch/faster-qwen3-tts-afa6120-to-71fa0fd.bundle
git bundle SHA256: 85b5d68076b7bb330b9c98cbd6af708b75fdd6d1b7dc7c358e9dc6f88b2774e7
```

The old randomized `r50` was reanalyzed without new GPU runs. The original
`+5.295 ms` `B-A p95` value is a difference of independent condition p95s, not
`p95(B-A)` per-run overhead. Bootstrap CIs are wide enough that this should not
block diagnostic profiling:

| Comparison | Observed median diff | Bootstrap 95% CI | Observed p95 diff | Bootstrap 95% CI |
| --- | ---: | ---: | ---: | ---: |
| B-A first TTFA | -2.952 ms | [-42.151, +18.654] ms | +5.295 ms | [-8.911, +18.781] ms |
| C-B first TTFA | +4.974 ms | [-17.761, +15.824] ms | -7.606 ms | [-23.064, +4.975] ms |
| B-A paired delta | +0.360 ms | [-1.311, +2.227] ms | +3.616 ms | [-17.355, +27.110] ms |
| C-B paired delta | -0.796 ms | [-2.780, +1.330] ms | -12.176 ms | [-33.376, +14.886] ms |

A short B/C smoke after cleanup used the new wheel and `profile_nvtx=false`.
The profile-on condition completed `40/40` first-chunk profiles with
stream-consistency `40/40`.

The main diagnostic `r100` then ran with `profile_prefill=true`,
`profile_nvtx=false`, 100 fresh workers, and four requests per worker.
Validation was clean: `400/400` profiles complete, `400/400` streams
consistent, and all used the new wheel SHA.

| Run | first TTFA median | first TTFA p95 | steady TTFA median | steady TTFA p95 | paired delta median | paired delta p95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| diagnostic r100, profiled | 367.719 ms | 423.344 ms | 365.681 ms | 416.137 ms | 2.818 ms | 27.931 ms |
| production r30, profile off | 375.377 ms | 417.717 ms | 384.442 ms | 411.271 ms | 2.335 ms | 18.668 ms |

The `r100` result strongly supports the talker-forward hypothesis for positive
first-minus-steady tails:

- positive paired deltas over `20 ms`: `12/100`;
- all `12/12` positive outliers are declassified below the `20 ms` threshold
  after removing positive talker-forward delta;
- conditional positive outlier total delta p50/p95/max:
  `25.735 / 51.350 / 52.471 ms`;
- conditional positive talker-forward delta p50/p95/max:
  `20.671 / 40.001 / 43.705 ms`;
- conditional positive unexplained residual p50/p95/max:
  `7.053 / 13.370 / 15.502 ms`;
- conditional talker-forward attribution fraction min/p50/p95/max:
  `0.449 / 0.773 / 0.892 / 0.908`;
- attribution fraction counts: `>=50%` in `11/12`, `>=80%` in `5/12`.

These conditional figures come from
`diagnostic-r100-profile-cleanup-v3/analysis-cleanup.json`, a derived
reanalyzer artifact built from the saved `r100` report. The analyzer also adds
per-real-steady-row residuals so future reports do not have to rely only on the
older synthetic steady median row. Across `300` first-vs-steady pairs, the
positive unexplained residual p95 is `8.625 ms` and the signed unexplained
residual p95 is `8.990 ms`.

This makes `talker.forward` the right optimization target for TTFA tails. The
result does not mean every request is faster when profiled; absolute TTFA from
the profiled run remains diagnostic-only, while production TTFA should be read
from profile-off control runs.

Terminology note: worker events now emit `*_stream_elapsed_ms` aliases for the
CUDA Event intervals. The older `*_gpu_ms` names are retained for backward
compatibility with saved artifacts, but they should be read as stream elapsed
time between recorded events, not as summed kernel execution time.

### Exact-Shape Prefill Compile Prototype

An experimental faster-qwen3-tts branch was created at commit `f08260d`
(`feat(prefill): add exact-shape compile backend switch`) and then extended to
diagnostic commit `f3b979c`
(`test(prefill): add diagnostic compile backends`). The bridge now passes a
faster-only `--prefill-backend` switch through to the packaged worker:
`eager`, `compile_backend_eager`, `compile_backend_aot_eager`,
`compile_inductor_default`, `compile_default`, or
`compile_reduce_overhead`.

The first prototype deliberately does not implement buckets. It caches
`torch.compile(..., fullgraph=true, dynamic=false)` by exact tensor shape and
reports `prefill_backend_requested`, `prefill_backend_used`, and
`prefill_compile_fallback` in first-chunk metrics. The default remains `eager`.

With same-shape synthesis warmup, the `r10` profile-off production control
showed a large latency win for `compile_reduce_overhead`:

| Condition | First TTFA median/p95 | Steady TTFA median/p95 | First prefill median/p95 | Steady prefill median/p95 |
| --- | ---: | ---: | ---: | ---: |
| eager, profile off | `391.653 / 413.613 ms` | `372.017 / 407.316 ms` | `161.767 / 181.532 ms` | `146.104 / 179.161 ms` |
| compile_reduce_overhead, profile off | `274.279 / 294.758 ms` | `233.914 / 244.649 ms` | `43.147 / 48.091 ms` | `8.650 / 13.034 ms` |

The profile-on diagnostic run confirms the target moved:

| Condition | First talker-forward median/p95 | Steady talker-forward median/p95 | Fallbacks |
| --- | ---: | ---: | ---: |
| eager, profile on | `152.208 / 173.688 ms` | `128.720 / 173.398 ms` | `0/40` |
| compile_reduce_overhead, profile on | `37.372 / 40.214 ms` | `3.308 / 4.240 ms` | `0/40` |

This is the strongest performance result so far: production first TTFA improves
by about `30%` and steady TTFA by about `37%` in this small same-shape `r10`
control. However, it is not production-safe yet. This is not only a tensor
parity issue: the compiled greedy run changes the end-to-end output length.

| Condition | PCM bytes | Chunks | Audio duration |
| --- | ---: | ---: | ---: |
| eager, profile off | `232162` | `8` | `4836.708 ms` |
| compile_reduce_overhead, profile off | `175046` | `6` | `3646.792 ms` |

The compiled output is about `24.6%` shorter. Therefore completion time and
RTF/inverse-RTF are not apples-to-apples for this experiment, even though TTFA
and prefill timing remain useful diagnostics. A direct prefill-only parity probe
showed exact eager/eager repeatability, but compiled prefill differed from eager
(`logits_last_max_abs=0.2578125`, `past_hidden_max_abs=0.546875`) for both
compile modes. The correct status is: exact-shape compiled prefill fails
end-to-end semantic parity because greedy codec/EOS trajectory and waveform
duration change. Keep the backend experimental and do not use it as a
production opt-in until greedy codec sequence, EOS position, and waveform
duration parity pass.

A committed parity ladder was added in
`scripts/qwen_prefill_compile_parity.py`. It snapshots prefill tensors
immediately after each call, compares logits, hidden state, K/V cache tensors,
top-token summaries, codec tokens, EOS frame, and waveform hashes, and writes
JSON artifacts under
`docs/benchmark-artifacts/rtx4090-2026-07-22/prefill-compile-parity-ladder/`.
The ladder shows that the BF16 mismatch starts before Inductor-specific
lowering: even `torch.compile(..., backend="eager")` differs from raw eager.

| Artifact | Dtype / control | Key result |
| --- | --- | --- |
| `bf16-ladder-r2.json` | BF16 default precision | `compile_backend_eager` and `compile_backend_aot_eager` already differ from eager by `logits_last_max_abs=0.21875`, `past_hidden_max_abs=1.0`; Inductor modes differ by `0.2578125` / `0.546875`. Each backend is repeat-stable with itself. |
| `bf16-precision-control-prefill-r2.json` | BF16, TF32 disabled, matmul precision `highest` | mismatch remains: backend-eager/aot-eager `0.2509765625` logits max abs; Inductor modes `0.25`. |
| `fp32-prefill-r2.json` | FP32, TF32 disabled, matmul precision `highest` | compiled prefill nearly matches raw eager: logits max abs `1.9073486328125e-05`. |
| `bf16-generation-eos-r1.json` | BF16 full greedy generation control | `compile_reduce_overhead` still fails semantic parity. Direct harness eager produced `46` frames / `87765` samples / `3656.875 ms`; compiled produced `50` frames / `95445` samples / `3976.875 ms`; first codec divergence was frame `0`, codebook `5`. |

The FP32 control makes the current best interpretation narrower: the prototype
is probably failing because of BF16 compiled-graph numerics in the talker
prefill path, not because the cached exact-shape call is accidentally reusing
the wrong tensors. However, the same-model 32-frame generation ladder also
showed that a second raw-eager generation call can change codec tokens while
keeping frame count and duration fixed. That separate repeat/state issue must
be isolated before any bucketed compile or product-facing speed work resumes.

After this diagnostic commit, the portable worker was rebuilt from clean
sources at bridge commit `fbdfa2e`, Qwen fork commit `25cc588`, and
faster-qwen3-tts commit `f3b979c`. The staged mock worker smoke passed, the real
CustomVoice FasterQwen eager smoke passed, and the packaged
`compile_backend_eager` path also passed a startup/protocol smoke. That last
result only proves the diagnostic backend is packaged and callable; it does not
change the correctness verdict above.

Follow-up review found an important flaw in the semantic ladder: the prior
`do_sample=False` path was not fully greedy. FasterQwen constructed its
residual `PredictorGraph` with `do_sample=True`, so the first talker codebook
used argmax but the remaining predictor codebooks still sampled. The FasterQwen
prototype was extended to commit `0272258`
(`fix(predictor): honor greedy mode for residual codebooks`) by constructing a
separate `PredictorGraph(do_sample=False)` and selecting it whenever a request
uses `do_sample=False`. The bridge parity harness now uses the same selector
when it calls `fast_generate_streaming` directly.

With true greedy predictor behavior:

| Artifact | Key result |
| --- | --- |
| `true-greedy-predictor/eager-repeat-r3.json` | raw eager x3 is now deterministic: codec hash, frame count, EOS, audio sample count, and waveform hash all match. |
| `true-greedy-predictor/bf16-ladder-r2.json` | BF16 compiled backends still fail semantic parity. `compile_backend_eager` and `compile_backend_aot_eager` keep frame/sample count but diverge at frame `1`, codebook `8`; Inductor modes diverge at frame `0`, codebook `15` and change frame/sample count. |
| `true-greedy-predictor/bf16-precision-control-ladder-r2.json` | Disabling TF32 and reduced-precision reductions does not restore BF16 parity. |
| `true-greedy-predictor/fp32-ladder-r2.json` | FP32 true-greedy semantic parity passes for `compile_backend_eager`, `compile_backend_aot_eager`, and `compile_inductor_default`; prefill tensor deltas remain tiny (`logits_last_max_abs=1.9073486328125e-05`). |

A first hook-based localization pass was added in
`scripts/qwen_prefill_module_parity.py`. For BF16 raw eager vs
`compile_backend_eager`, the first visible layer-0 difference is at
`model.layers.0.self_attn.o_proj` (`max_abs=0.00048828125`,
`rmse=3.2677187846275046e-05`); it then amplifies through the layer-0 MLP to
`model.layers.0` `max_abs=0.03125`. In FP32, the same first visible location is
near machine noise (`max_abs=4.172325134277344e-07`). No obvious
`torch.compiler.is_compiling()` / `torch._dynamo.is_compiling()` branch was
found in the FasterQwen or vendored Qwen model path. The next target is inside
the layer-0 attention output path: attention probabilities/context, `o_proj`,
and possible BF16 reduction/order differences.

### Fail-Closed Greedy And Attention Micro-Bisect

The FasterQwen patch stack was extended to commit `9f1c801`
(`fix(predictor): fail closed without greedy graph`). `do_sample=False` now
raises if the separate greedy predictor graph is missing, instead of silently
falling back to the sampling predictor graph. The bridge artifact directory
contains a fresh patch series and bundle under
`faster-qwen-fail-closed-greedy-predictor-patch/`.

The parity harness now records explicit frame accounting for every generated
run: requested token budget, emitted steps, final chunk metadata, all EOS
positions, and a derived `stop_reason`. A short `r1` control confirms the
existing verdict while making stop behavior auditable:

| Artifact | Backend | Codec / frame result | Stop accounting |
| --- | --- | --- | --- |
| `frame-accounting/bf16-ladder-r1.json` | `compile_backend_eager` | codec differs, same `64` frames / `122325` samples | `max_new_tokens`, no EOS |
| `frame-accounting/bf16-ladder-r1.json` | `compile_inductor_default` | codec differs, shorter `62` frames / `118485` samples | `short_without_eos`, no EOS |
| `frame-accounting/fp32-ladder-r1.json` | `compile_backend_eager` | codec, frame count, samples, and EOS equal eager | `max_new_tokens`, no EOS |
| `frame-accounting/fp32-ladder-r1.json` | `compile_inductor_default` | codec, frame count, samples, and EOS equal eager | `max_new_tokens`, no EOS |

An attention micro-bisect script was added at
`scripts/qwen_prefill_attention_micro_parity.py`. It recomputes selected
layer-0 attention checkpoints directly, with no forward hooks inside the
compiled graph, and supports an experimental `--attention-core-fp32` mode for
the QK/softmax/PV core. The current micro results are useful but not yet
definitive:

| Artifact | Key result |
| --- | --- |
| `attention-micro-bisect/bf16-layer0-attention-scores-only-compile-backend-eager.json` | layer-0 raw eager vs `compile_backend_eager` attention scores match exactly (`max_abs=0.0`). |
| `attention-micro-bisect/bf16-layer0-attention-softmax-only-compile-backend-eager.json` | recomputing through the checkpoint function first differs at `softmax_probs` (`max_abs=0.244140625`). |
| `attention-micro-bisect/fp32-layer0-attention-softmax-only-compile-backend-eager.json` | the same checkpoint-function softmax difference appears even in FP32 (`max_abs=0.244284987449646`). |
| `attention-micro-bisect/materialized-scores-softmax-control.json` | softmax on already materialized scores matches raw vs compiled exactly in both BF16 and FP32 (`max_abs=0.0`). |
| `attention-micro-bisect/bf16-attention-core-fp32-selected-compile-backend-eager.json` | forcing the attention core to FP32 does not remove the checkpoint-function difference (`softmax_probs max_abs=0.24424684047698975`). |

The cautious interpretation is that the hook-based `o_proj` boundary is still a
real first visible mismatch, but the new micro-bisect has not proven that
softmax itself is the root cause. Because a materialized softmax control is
exact and an FP32 attention-core island does not fix the checkpoint-function
diff, this stage did not promote any FP32-island runtime patch. The next
correctness step should inspect the compiled FX/AOT graph or build an even
smaller exported repro around the layer-0 attention function before trying a
product-facing mixed-precision workaround.

The isolated C++ transport stress requested by review also passed:
`ctest --test-dir build\default -R stdio_transport_test --repeat until-fail:100
--output-on-failure` completed `100/100` iterations in `449.94 s`. This did not
reproduce the earlier one-off full-suite failure, so the current status is
"observed once in full CTest, not reproduced in isolated 100x stress".

### Single-Pass Mask Bisection And Partial Compile Fix

The attention bisection harness was rewritten to produce one single-pass
layer-0 trace. All reported checkpoints now come from one sequential execution,
and the report includes the previously missing `causal_mask` /
`scores_masked` boundary plus a materialized stage ladder.

This closed the first bisection step. In BF16 raw eager vs
`compile_backend_eager`, the first divergent value is `causal_mask`, not
softmax or `o_proj`: raw eager skips the mask (`None`, normalized to zeros in
the diagnostic), while Dynamo tracing through Transformers
`create_causal_mask` materializes a boolean 0/1 mask. Qwen's eager attention
path then adds that boolean mask to attention scores, which changes logits.

| Artifact | Key result |
| --- | --- |
| `attention-single-pass-bisect/bf16-layer0-mask-focus-v2-compile-backend-eager.json` | first trace diff is `causal_mask` (`max_abs=1.0`); materialized ladder first diff is `causal_mask_build`. |
| `attention-single-pass-bisect/bf16-layer0-inductor-force-mask-skip.json` | after forcing the same mask skip, Inductor's next BF16 trace diff is `scores` (`max_abs=0.125`); materialized ladder first diff is `qkv/q_norm` (`max_abs=0.03125`). |
| `attention-single-pass-bisect/fp32-layer0-inductor-force-mask-skip.json` | FP32 Inductor after mask skip is near numerical noise (`scores max_abs=3.337860107421875e-06`). |

The FasterQwen patch stack was extended to commit `2d04337`
(`fix(prefill): preserve mask skip under compile`). During compiled prefill
tracing, if the prefill has no padding and no sliding window, the wrapper
temporarily makes Qwen's module-level `create_causal_mask` return `None`, which
matches raw eager behavior without tracing Transformers'
data-dependent `padding_mask.all()` branch. The profile reports
`prefill_compile_force_mask_skip=true` when this path is used.

This is a real correctness fix for the non-Inductor compiled backends:

| Artifact | Backend | Result |
| --- | --- | --- |
| `mask-skip-compile-fix/bf16-compile-backend-eager-r1-v2.json` | `compile_backend_eager` | real compiled backend, no fallback, prefill max diff `0.0`, codec/frame/EOS parity passes. |
| `mask-skip-compile-fix/bf16-compiled-ladder-r2-v2.json` | `compile_backend_eager` | repeat-stable, prefill max diff `0.0`, true-greedy codec parity passes. |
| `mask-skip-compile-fix/bf16-compiled-ladder-r2-v2.json` | `compile_backend_aot_eager` | repeat-stable, prefill max diff `0.0`, true-greedy codec parity passes. |
| `mask-skip-compile-fix/bf16-compiled-ladder-r2-v2.json` | `compile_inductor_default` / `compile_reduce_overhead` | still not correctness-safe: prefill max diff `0.203125`; generation stops by true EOS at emitted frame `51` instead of eager reaching `max_new_tokens=64`. |

The current product-facing gate is therefore narrower and more useful:
`compile_backend_eager` and `compile_backend_aot_eager` are correctness-clean in
this true-greedy BF16 control, while Inductor/reduce-overhead remain
experimental. The next optimization step is to isolate and test a minimal BF16
Inductor fix around layer-0 `q_norm`/QKV, or measure whether `aot_eager`
provides enough speedup to be worth a guarded opt-in before returning to
`reduce-overhead`.

### Production Mask Mode And Device Profiles

The proof-of-cause mask fix was replaced with an explicit API-level mask mode.
The Qwen submodule now has commit `f75125e`
(`fix(talker): allow explicit prefill mask skip`), adding
`skip_prefill_causal_mask` to the talker model and forwarding wrapper. The
FasterQwen branch now has commit `d515c2d`
(`fix(prefill): use explicit mask skip mode`), which passes a static
`prefill_mask_mode` into the compiled prefill graph and includes that mode in
the compile cache key. The previous global monkeypatch of
`create_causal_mask` is gone.

The mask decision is now fail-closed and metadata-driven:

| Case | Mode |
| --- | --- |
| single CustomVoice prefill, all tokens valid, no sliding window | `skip` |
| missing metadata | `explicit` |
| padded attention mask | `explicit` |
| batch size other than `1` | `explicit` |
| sliding-window model | `explicit` |

This also removes the CUDA `.all().item()` synchronization from the request
critical path. A small smoke confirmed the mask selector and `_run_talker_prefill`
bool forwarding without requiring pytest in the local environments.

The real-model BF16 controls still pass with the production mask mode:

| Artifact | Result |
| --- | --- |
| `production-mask-mode/bf16-compile-backend-eager-r1.json` | `compile_backend_eager` uses the real compiled backend, `fallback=false`, `prefill_mask_mode=skip`, prefill diff `0.0`, codec/frame/termination parity passes. |
| `production-mask-mode/bf16-safe-compile-ladder-r2.json` | `compile_backend_eager` and `compile_backend_aot_eager` remain exact over `2` repeats; both have prefill diff `0.0` and true-greedy semantic parity. |

The parity and micro-bisect reports now include runtime hardware metadata:
Torch version, CUDA version, GPU name, compute capability, and total VRAM. The
current RTX 4090 results are therefore explicitly tagged as
`device_profile=rtx4090`. Older GPUs, including the available-but-not-installed
CMP 50HX class, should be treated as a future `compat` profile rather than
assuming the RTX 4090 defaults. Before enabling product defaults on such cards,
run a separate gate for FP16/FP32 behavior, VRAM headroom, compile availability,
and fallback behavior.

### Paired Nsight Follow-Up

The worker now emits an outer `qtb_profile_first_steady_pair` NVTX range when
`profile_nvtx=true`, spanning request 1 and request 2 in one worker process.
Twenty paired Nsight captures were collected. They did not catch a positive
first-minus-steady prefill delta over `20 ms`; several traces instead showed a
negative delta where the first prefill range was shorter than the steady range.

This means the event-based `r100` can be treated as the stronger evidence for
positive tail attribution, while paired Nsight remains useful structural
evidence but has not yet directly captured a positive p95-tail sample. The
current interpretation should stay careful: positive tails are explained by
CUDA-event talker-forward deltas in `r100`; Nsight proves the launch-bound
shape of ordinary captures but has not yet independently captured a positive
tail process.

### Shape Warmup Matrix

A small 8-run shape matrix was added to compare a fixed medium warmup against
per-shape warmup:

- `docs/benchmark-artifacts/rtx4090-2026-07-22/input-shape-prefill-profile-r2-each-seed20260724.jsonl`
- `docs/benchmark-artifacts/rtx4090-2026-07-22/shape-prefill-profile-source-worker-faster-customvoice-chunk8-r8x2-sampling-mediumwarmup.json`
- `docs/benchmark-artifacts/rtx4090-2026-07-22/shape-prefill-profile-source-worker-faster-customvoice-chunk8-r8x2-sampling-shapewarmup.json`

Both runs used sampling, `--profile-prefill`, `seed=4242`, one synthesis warmup,
and two measured requests per fresh worker. The per-shape warmup run used the
new benchmark flag `--warmup-from-run-shape`.

| Matrix | slow positive deltas over 20 ms | first-audio range, request 1 | steady first-audio range | bridge/dispatch residual |
| --- | ---: | ---: | ---: | ---: |
| fixed medium warmup | 4 / 8 | 352.2-424.4 ms | 344.7-613.2 ms | 1.04-1.26 ms |
| per-shape warmup | 2 / 8 | 360.9-420.9 ms | 359.3-412.6 ms | 1.14-1.39 ms |

This suggests that shape-matched warmup may reduce some cold first-request
variance, but the sample is intentionally small and one fixed-warmup steady
request was itself an outlier (`very_long_b`, 613.2 ms). Treat this as a
directional diagnostic. A larger shuffled matrix with request-time GPU polling
is still needed before changing product defaults.

### Mask Contract Hardening And Inductor RMS/RoPE Follow-Up

The explicit prefill mask mode was hardened so `skip` is no longer selected
from a bare `prefill_attention_mask_all_valid=true`. FasterQwen now records the
CPU-side mask provenance as `prefill_mask_decision_source` and requires
`constructed_all_ones`, batch size `1`, no sliding window, and a supported
attention implementation before selecting `skip`. The real CustomVoice path
currently reports the actual talker attention implementation as `sdpa`, even
when the diagnostic CLI argument is `--attn-implementation eager`; therefore
the supported set for the proven path is `eager` / `sdpa`, while other
implementations remain fail-closed.

The Qwen submodule also rejects unsafe direct `skip_prefill_causal_mask` calls:
decode/single-token calls, caller-provided `cache_position`, caller-provided
KV-cache, sliding-window attention, and unvalidated attention implementations
raise before the causal mask is skipped.

| Artifact | Result |
| --- | --- |
| `production-mask-contract-hardening/bf16-compile-backend-eager-r1.json` | `compile_backend_eager` keeps `prefill_mask_mode=skip`, prefill diff `0.0`, codec/EOS/frame parity passes. |
| `production-mask-contract-hardening/bf16-safe-compile-ladder-r2.json` | `compile_backend_eager` and `compile_backend_aot_eager` remain exact over `2` repeats. |
| `production-mask-contract-hardening/bf16-inductor-default-r1.json` | Inductor remains blocked: prefill diff `0.203125`, codec differs, frame count differs. |

The Inductor BF16 bisection then tested the suspected Q/K normalization path
without changing product code. `.contiguous()` and manual FP32 RMS reduction do
not remove the materialized `q_norm` / `k_norm` differences. `F.rms_norm` and
`aten.rms_norm` do remove the isolated Q/K RMSNorm differences, but the full
layer trace then first diverges at `q_rope` / `k_rope`, and that propagates to
attention scores and softmax. Applying contiguous or FP32 variants around RoPE
did not remove the RoPE difference.

Current interpretation: Inductor rollout is still correctness-blocked, but the
root cause has moved from the old mask bug to a BF16 Inductor lowering issue
covering RMSNorm and then multimodal RoPE. A product patch should not be
promoted from these diagnostics yet; the next useful experiment is an explicit
eager island or compile-disable boundary around RMSNorm+RoPE, followed by the
same true-greedy semantic gate.

## Sources

- `external/python/Qwen3-TTS-streaming/examples/test_streaming_optimized.py`
- `external/python/Qwen3-TTS-streaming/examples/test_model_12hz_base.py`
- https://github.com/andimarafioti/faster-qwen3-tts
- https://github.com/andimarafioti/faster-qwen3-tts/blob/main/BLOG.md
- https://docs.nvidia.com/dl-cuda-graph/latest/torch-cuda-graph/torch-integration.html
- https://docs.nvidia.com/dl-cuda-graph/torch-cuda-graph/best-practices.html
- https://huggingface.co/docs/transformers/perf_torch_compile
