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

| Level | Boundary | First PCM median | First PCM p95 | Completed median | Completed p95 | RTF median |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Direct `QwenTtsEngine` | call `synthesize_stream()` -> first yielded PCM bytes | 344.0 ms | 349.7 ms | 1.37 s | 1.95 s | 0.369 |
| Source worker IPC | client send -> first `AUDIO_PCM` frame | 447.6 ms | 456.1 ms | 1.44 s | 1.91 s | 0.384 |
| C++ callback benchmark | `synthesize_async()` submit -> first `on_audio` callback | 381.0 ms | 392.6 ms | 1.41 s | 1.83 s | 0.377 |

Artifacts:

```text
docs/benchmark-artifacts/rtx4090-2026-07-22/latency-ladder-direct-engine-faster-customvoice-chunk8-r30.json
docs/benchmark-artifacts/rtx4090-2026-07-22/latency-ladder-source-worker-ipc-faster-customvoice-chunk8-r30.json
docs/benchmark-artifacts/rtx4090-2026-07-22/latency-ladder-cpp-callback-faster-customvoice-chunk8-r30.json
```

The worker and C++ layers are now measured with the right external boundaries,
but the model sampling seed is not controlled through the bridge protocol yet,
so this ladder should be read as a reproducible product-level observation, not
as exact per-layer overhead arithmetic. The source worker run also contains a
single first-audio outlier at 647 ms. A short C++ timestamp smoke after adding
worker writer metrics showed the first audio frame queue/write/flush path itself
is tiny: first frame enqueue -> write start was about 0.08-0.11 ms and write
start -> flush was about 0.10-0.26 ms on that run.

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
from the packaging environment. A full packaged faster benchmark is still
pending because it requires building a fresh portable worker distribution with
the selected CUDA/Torch/faster-qwen environment.

Updated diagnosis after profiling:

```text
official benchmark/config mismatch: unlikely
PR #112 hot-path fixes missing: ruled out as main cause
torch/cu runtime difference: unlikely after 2.10/cu128 control
max_seq_len/cache size: unlikely for this workload
codec decode and wrapper synchronization: confirmed meaningful overhead
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

## Sources

- `external/python/Qwen3-TTS-streaming/examples/test_streaming_optimized.py`
- `external/python/Qwen3-TTS-streaming/examples/test_model_12hz_base.py`
- https://github.com/andimarafioti/faster-qwen3-tts
- https://github.com/andimarafioti/faster-qwen3-tts/blob/main/BLOG.md
- https://docs.nvidia.com/dl-cuda-graph/latest/torch-cuda-graph/torch-integration.html
- https://docs.nvidia.com/dl-cuda-graph/torch-cuda-graph/best-practices.html
- https://huggingface.co/docs/transformers/perf_torch_compile
