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

### Verified Mask Contract And Standalone RoPE Repro

The mask contract was tightened one more step. FasterQwen now derives
`prefill_mask_decision_source` from the real local talker attention-mask builder
while it still has `original_lengths`, rather than reconstructing provenance
later from a synthetic one-element length tensor. Verified skip also passes
`attention_mask=None` into Qwen; explicit mode remains the only mode that passes
a real mask tensor. The Qwen submodule rejects direct
`skip_prefill_causal_mask=True` calls that still provide an `attention_mask`.

The SDPA gate now has explicit artifacts:

| Artifact | Result |
| --- | --- |
| `mask-contract-sdpa-gate/bf16-sdpa-explicit-compile-backend-eager-r1.json` | Raw eager explicit matches raw eager skip semantically, but compiled explicit remains unsafe (`prefill diff 0.21875`, codec differs). |
| `mask-contract-sdpa-gate/bf16-sdpa-skip-compile-backend-eager-r1.json` | Verified skip is exact: compiled prefill diff `0.0`, codec/waveform/frame parity passes. |

This closes the mask track for the current all-valid CustomVoice path: padded or
unknown masks remain explicit and therefore do not opt into the compiled
verified-skip path.

A standalone RoPE repro was added in `scripts/qwen_rope_inductor_repro.py`. It
captures real layer-0 `q_norm`, `k_norm`, `cos`, and `sin` tensors, then runs a
small multimodal RoPE function across backends. In BF16, eager,
`compile_backend_eager`, and `compile_backend_aot_eager` are exact, while
Inductor first diverges at `q_rope` (`max_abs 0.03125`) and then `scores`
(`max_abs 0.0625`). The primitive ladder shows `cos/sin` mixing,
`rotate_half`, and the individual multiply terms are exact; the first visible
difference is the BF16 add that produces `q_rope` / `k_rope`. The same repro in
FP32 is exact under Inductor.

The automatic PyTorch accuracy minifier was attempted with
`TORCHDYNAMO_REPRO_AFTER=dynamo` and `TORCHDYNAMO_REPRO_LEVEL=4`, but it failed
inside the minifier/guard machinery on this graph (`Expected tensors only, but
got list`, followed by an internal shape-guard error). The standalone repro is
therefore the current portable minifier substitute.

The simple eager-island compatibility route was also checked using an
experimental `compile_inductor_graphbreak` backend. It did not restore prefill
parity:

| Variant | Prefill max diff |
| --- | ---: |
| Inductor graphbreak baseline | `0.203125` |
| graphbreak + RMSNorm compile-disable | `0.22265625` |
| graphbreak + RMSNorm and RoPE compile-disable | `0.25` |

So the next useful optimization path is not a simple graph-break wrapper around
RMSNorm/RoPE. A better candidate is a smaller custom-op or explicit
decomposition around the BF16 RoPE add, tested first in the standalone repro and
only then promoted back into the full true-greedy gate.

### Strict RMSNorm/RoPE Inductor Compatibility Gates

The FasterQwen compiled-prefill safety boundary was tightened after the SDPA
gate proved that compiled explicit masks are still unsafe. Non-eager prefill
backends now reject `prefill_mask_mode=explicit` and require the verified
`skip` path. The intentional safety smoke exits with
`UnsupportedPrefillConfiguration` and does not write a benchmark artifact:
compiled explicit masks are blocked before model execution.

The standalone RoPE repro now has stricter custom-op modes:

| Artifact | Result |
| --- | --- |
| `strict-rope-repro/bf16-rope-current.json` | current BF16 Inductor RoPE still first differs at `q_rope` (`max_abs 0.03125`). |
| `strict-rope-repro/bf16-rope-strict_add.json` | wrapping the final BF16 adds in a custom op makes Inductor exact. |
| `strict-rope-repro/bf16-rope-strict_rope.json` | wrapping the whole RoPE operation in a custom op also makes Inductor exact. |

A standalone RMSNorm repro was added in
`scripts/qwen_rmsnorm_inductor_repro.py`. It captures the real layer-0 `q_norm`
input and compares BF16 Inductor against eager:

| Artifact | Result |
| --- | --- |
| `strict-rmsnorm-repro/bf16-qnorm-current.json` | current RMSNorm differs under Inductor (`max_abs 0.03125`). |
| `strict-rmsnorm-repro/bf16-qnorm-aten_rms_norm.json` | `aten.rms_norm` is exact in the isolated repro. |
| `strict-rmsnorm-repro/bf16-qnorm-strict_custom.json` | a strict RMSNorm custom op is exact in the isolated repro. |

These isolated fixes did not make the full Talker graph safe:

| Artifact | Compatibility mode | Result |
| --- | --- | --- |
| `strict-compat-full-gate/bf16-inductor-aten-rms-strict-rope-r1.json` | `aten_rms_norm` + strict RoPE add | still fails: `logits_last max_abs 0.3125`, codec differs at frame `5`, codebook `1`; frame count and EOS status stay equal. |
| `strict-compat-full-gate/bf16-inductor-strict-rms-strict-rope-r1.json` | strict RMSNorm custom op + strict RoPE add | still fails: `logits_last max_abs 0.25`, codec differs at frame `7`, codebook `1`; frame count and EOS status stay equal. |

This closes the first strict-op experiment without a product rollout. The
current verdict is narrower: the isolated RMSNorm and RoPE lowerings are real
BF16 Inductor hazards, but after neutralizing them the full graph still has at
least one additional BF16 Inductor divergence. Do not run performance gates for
Inductor until the next bisection finds and fixes that remaining source.

### Attention A/B And Layer-Prefix Bisection

The next review suggested checking whether the remaining strict full-gate
failure was specifically SDPA. The first A/B attempt exposed an important
diagnostic trap: requesting `--attn-implementation eager` still loaded a Talker
whose actual `_attn_implementation` was `sdpa`. The parity harness now records
`actual_talker_attn_implementation` and supports a diagnostic
`--force-talker-attn-implementation` override for already-loaded Talker configs.

The forced full gates show that SDPA is not the only remaining cause:

| Artifact | Actual attention | Result |
| --- | --- | --- |
| `attention-ab-strict-full-gate/bf16-inductor-forced-sdpa-attn-strict-rms-strict-rope-r1.json` | `sdpa` | still fails: `logits_last max_abs 0.25`, codec differs at frame `7`, codebook `1`; frame count and EOS status stay equal. |
| `attention-ab-strict-full-gate/bf16-inductor-forced-eager-attn-strict-rms-strict-rope-r1.json` | `eager` | also fails, and more strongly: `logits_last max_abs 1.4375`, codec differs at frame `0`, codebook `2`; frame count and EOS status stay equal. |

Because eager-attention also fails, the broad SDPA custom-op path was not
promoted. Instead, a single-output layer-prefix repro was added in
`scripts/qwen_prefill_layer_prefix_parity.py`. It runs either the first `N`
Talker transformer layers or one selected stage inside a layer, comparing eager
against Inductor under the same strict RMSNorm/RoPE diagnostics.

With strict RMSNorm and strict RoPE, the first layer already differs:

| Artifact | Result |
| --- | --- |
| `layer-prefix-bisect/bf16-sdpa-strict-prefix-0.json` | exact. |
| `layer-prefix-bisect/bf16-sdpa-strict-prefix-1.json` | first layer output differs (`max_abs 0.125`). |
| `layer-prefix-bisect/bf16-sdpa-strict-layer0-mlp_mul.json` | layer-0 `gate/up/act` are exact; first materialized MLP diff appears at `act(gate) * up` (`max_abs 0.015625`). |
| `layer-prefix-bisect/bf16-sdpa-strict-layer0-mlp_output.json` | the MLP down projection amplifies that to `max_abs 0.125`. |

Adding an opaque custom-op around the MLP multiply makes layer 0 exact and keeps
the first several prefixes exact:

| Artifact | Result |
| --- | --- |
| `layer-prefix-bisect/bf16-sdpa-strict-rms-rope-mlp-prefix-1.json` | exact. |
| `layer-prefix-bisect/bf16-sdpa-strict-rms-rope-mlp-prefix-8.json` | exact. |
| `layer-prefix-bisect/bf16-sdpa-strict-rms-rope-mlp-prefix-9.json` | exact. |
| `layer-prefix-bisect/bf16-sdpa-strict-rms-rope-mlp-prefix-10.json` | first new prefix diff appears (`max_abs 0.00390625`). |

The next failing layer is therefore layer `9`. With strict RMSNorm/RoPE/MLP
multiply enabled, layer `9` first differs at the attention output
(`max_abs 0.0009765625`), then the residual/MLP path amplifies it to layer
output `max_abs 0.0625`.

The full strict RMSNorm/RoPE/MLP gate still fails:

| Artifact | Result |
| --- | --- |
| `strict-compat-full-gate/bf16-inductor-strict-rms-rope-mlp-r1.json` | still fails: `logits_last max_abs 0.21875`, `past_hidden max_abs 1.0`, codec differs at frame `4`, codebook `7`, and frame count differs. |

Current interpretation: BF16 Inductor correctness is not blocked by one single
operation. The chain so far is RMSNorm/RoPE, then MLP multiply in early layers,
then attention output in layer `9`. Product defaults should still remain eager;
the next diagnostic target is a layer-9 attention-core repro or a very narrow
attention compatibility island after strict RMSNorm/RoPE/MLP.

### Production-Signature Layer-9 Attention Repro

The FasterQwen safety tests were run for real after installing `pytest` into the
local Faster venv. `tests/test_sampling.py` passed (`25` tests, one Dynamo
warning), and the non-e2e unit files passed (`57` tests). The full FasterQwen
suite collected `96` tests but did not finish within a `15` minute timeout;
the slow/blocking portion is the model e2e parity file, not the safety matrix.

The parity harness now has an attention call sentinel. It performs a separate
eager prefill probe before the compiled gate and records observed attention
function calls without wrapping the compiled graph. For the current product-like
SDPA path, the probe records:

```text
observed attention calls: eager=0, sdpa=28
```

A production-signature layer-9 repro was added in
`scripts/qwen_prefill_layer9_attention_parity.py`. It materializes the exact
eager output after layers `0..8`, then runs layer `9` raw vs Inductor from that
same input using `use_cache=True`, `DynamicCache`, the same `cache_position`,
the same `position_embeddings`, and `attention_mask=None` from verified skip.

With strict RMSNorm/RoPE/MLP enabled, the production-shaped ladder confirms the
same layer-9 attention-core finding:

| Stage | Result |
| --- | --- |
| `layer_input` through `k_rope` | exact. |
| `attention_context` default SDPA | first diff: `max_abs 0.0009765625`. |
| `attention_context` forced math SDPA | same diff: `max_abs 0.0009765625`. |
| `attention_context` eager formula | larger diff: `max_abs 0.017578125`. |
| `attention_context` opaque `strict_sdpa` custom op | exact. |

That opaque SDPA compatibility island was then promoted back into the full
true-greedy gate together with strict RMSNorm, strict RoPE, and strict MLP
multiply. This is the first BF16 Inductor full-gate pass in the diagnostic
stack:

| Artifact | Result |
| --- | --- |
| `strict-compat-full-gate/bf16-inductor-strict-rms-rope-mlp-sdpa-r1.json` | prefill diff `0.0`; codec, frame count, EOS status, waveform, audio sample count all match eager. |
| `strict-compat-full-gate/bf16-inductor-strict-rms-rope-mlp-sdpa-r2.json` | repeat check also passes: prefill diff `0.0`, codec/waveform/frame/EOS/audio samples match eager over `2` repeats. |

This is still diagnostic code, not a product default. The next step is to turn
these four narrow compatibility islands into a maintainable FasterQwen patch
and then run performance gates. Until that patch is product-shaped and retains
semantic parity, the default stays eager.

### Raw-vs-Strict Context Gate Correction

A follow-up A/B/C/D gate found an important bug in the diagnostic strict SDPA
island. The previous strict gate compared strict eager against strict Inductor,
but the strict SDPA wrapper was not identical to the raw Transformers SDPA
path. It missed two production wrapper details:

- `is_causal=True` for full prefill when `attention_mask=None` and sequence
  length is greater than one;
- PyTorch SDPA GQA dispatch through `enable_gqa=True` when Transformers selects
  that path.

Before the fix, raw eager vs strict eager differed even without Inductor:

| Artifact | Result |
| --- | --- |
| `context-gate/bf16-sdpa-raw-strict-inductor-reduce-r1.json` | raw eager vs strict eager failed: `logits_last max_abs 19.828125`; generation still had matching frame/EOS status, so the broken strict reference was easy to miss. |
| `context-gate/bf16-sdpa-strict-component-ablation-prefill-r1.json` | component ablation isolated the large diff to `strict_sdpa_eager`; RMSNorm, RoPE, and MLP islands stayed exact. |
| `context-gate/bf16-sdpa-strict-component-ablation-prefill-after-causal-r1.json` | adding causal SDPA reduced the diff to `0.21875`, but did not close raw-vs-strict parity. |

After matching both causal and GQA behavior, the diagnostic strict SDPA island is
now exact against raw eager:

| Artifact | Result |
| --- | --- |
| `context-gate/bf16-sdpa-strict-component-ablation-prefill-after-causal-gqa-r1.json` | all component ablations are exact against raw eager: `logits_last max_abs 0.0`. |
| `context-gate/bf16-sdpa-raw-strict-inductor-reduce-after-causal-gqa-r1.json` | A/B/C/D gate passed for raw eager, strict eager, strict Inductor default, and strict Inductor reduce-overhead: prefill diff `0.0`; codec, frame count, and EOS status match. |
| `context-gate/bf16-sdpa-raw-strict-inductor-reduce-eos-after-causal-gqa-r1.json` | same A/B/C/D gate passed with true EOS termination at `max_new_tokens=256`. |
| `context-gate/semantic-russian-quote-bf16-sdpa-after-causal-gqa-r1.json` | Russian/Unicode prompt passed: prefill diff `0.0`; codec, frame count, and EOS status match. |
| `context-gate/semantic-english-instruction-bf16-sdpa-after-causal-gqa-r1.json` | English prompt with instruction passed: prefill diff `0.0`; codec, frame count, and EOS status match. Both paths stopped `short_without_eos`, so this is a parity check rather than an EOS-coverage check. |

This closes the raw-vs-strict correctness objection for the current RTX 4090
BF16 SDPA diagnostic stack. Product defaults should still remain eager until
the compatibility islands are moved out of monkeypatch-style diagnostics into a
maintainable FasterQwen opt-in and the resulting product-shaped path passes the
same semantic gates.

### Product-Shaped Strict BF16 SDPA Opt-In

The strict compatibility stack has now been moved from diagnostic monkeypatches
into a FasterQwen opt-in mode:

```text
prefill_compile_compat_mode=strict_bf16_sdpa_v1
```

The local FasterQwen worktree is
`C:\_repoz\faster-qwen3-tts-v032-stack112-clean`, branch
`prefill-compile-exact-shape`, commit `7732b7b`. The bridge worker exposes the
mode through `--prefill-compile-compat-mode`; the default remains `none`.

The opt-in is deliberately fail-closed. It is accepted only for FasterQwen
CustomVoice, BF16 inputs, batch size `1`, compiled prefill backends
`compile_inductor_default` / `compile_reduce_overhead`, verified mask skip with
`attention_mask=None`, SDPA attention metadata, and no sliding-window prefill.
The compatibility islands cover RMSNorm, RoPE additions, MLP multiply, and
SDPA, but they are now applied only inside compiled prefill calls. Load-time
configuration validates the target module counts and records metadata, then
leaves the Talker forwards idle so PredictorGraph/TalkerGraph decode capture
uses the original model forwards.
The transient replacement is guarded by a per-Talker `RLock`, so direct
concurrent FasterQwen streaming calls serialize the strict prefill section
instead of observing a half-restored `forward` state. Compiled prefill cache
Python callable entries are bounded, expose hit/miss/size/compile-time
telemetry, and are cleared for the model's Talker from `FasterQwen3TTS.close()`.
This LRU bounds FasterQwen's wrapper callable cache only; it does not bound
PyTorch/Triton compiler memory.

The lifecycle is now model-immutable in the public FasterQwen path:
`FasterQwen3TTS.from_pretrained(..., prefill_compile_compat_mode=...)`
declares the Talker mode at load time. After that, per-request attempts to use
a different mode fail, including `strict -> none` and `none -> strict`.
The module patch is atomic: target modules are collected and validated before
any `forward` method is temporarily replaced. The bridge also rejects invalid
strict config combinations before model load and validates the loaded model
before sending `ready`: actual model type, dtype, attention implementation,
loaded compat mode, metadata version, declared mode, idle patch state, and
validated module counts/fingerprint must match the strict contract. Strict
product mode now also requires synthesis warmup before `ready`; unknown
first-use compile/capture work must not be hidden in the first user request.
VoiceDesign remains temporarily blocked for strict mode until a real VoiceDesign
gate is run.

The semantic gate was also hardened. Generation comparisons now fail unless
termination telemetry agrees (`termination_reason`, `hit_eos`,
`terminal_token_id`, `terminal_step_index`, `generated_steps`, `emitted_steps`)
and the run is semantically complete. A short generation without EOS is no
longer accepted unless the harness is explicitly run with
`--allow-partial-generation`.

Correctness gates on RTX 4090:

| Artifact | Shape | Result |
| --- | --- | --- |
| `context-gate-v2/bf16-sdpa-raw-strict-inductor-reduce-r3.json` | English quote, `max_new_tokens=64` | raw, strict eager, strict Inductor default, and strict reduce-overhead all pass; prefill diff `0.0`; termination matches with `max_new_tokens`. |
| `context-gate-v2/bf16-sdpa-raw-strict-inductor-reduce-eos-r3.json` | English quote, `max_new_tokens=256` | all paths pass; true EOS termination matches. |
| `context-gate-v2/semantic-russian-quote-bf16-sdpa-r3.json` | Russian text | all paths pass; termination matches. |
| `context-gate-v2/semantic-english-instruction-short-bf16-sdpa-r3.json` | English text plus instruction | all paths pass; true EOS termination matches. |
| `context-gate-v2/product-strict-bf16-sdpa-r3.json` | product opt-in contexts | raw vs product strict Inductor default/reduce both pass; `max_new_tokens` termination matches. |
| `context-gate-v2/product-strict-bf16-sdpa-eos-r3.json` | product opt-in contexts, EOS | raw vs product strict Inductor default/reduce both pass; EOS termination matches. |
| `context-gate-v2/matrix-customvoice-english-short-product-r3.json` | short CustomVoice text | product contexts pass with EOS. |
| `context-gate-v2/matrix-customvoice-english-long-product-r3.json` | longer CustomVoice text | product contexts pass with `max_new_tokens`. |

FasterQwen validation:

```text
py_compile: passed for prefill_compat.py, streaming.py, model.py, and tests.
pytest tests/test_sampling.py tests/test_prefill_compat.py -q: 45 passed, 1 Dynamo warning.
pytest tests/test_ggml_backend.py tests/test_prefill_compat.py tests/test_sample_rate.py tests/test_sampling.py tests/test_voice_clone_prompt_api.py -q: 102 passed, 1 Dynamo warning.
PYTHONPATH=<Qwen fork> pytest tests/test_e2e_parity.py -q: 14 passed, 17 warnings, 305.83s.
PYTHONPATH=<Qwen fork> pytest -q: 116 passed, 18 warnings, 298.91s after final patch.
Bridge scripts/check-python.ps1 -UseVenv -VenvPath .venv: 154 tests OK, 2 skipped.
Bridge ctest --test-dir build\default --output-on-failure: 9/9 passed.
Bridge stdio_transport_test stress, --repeat until-fail:20: 20/20 passed.
After lifecycle hardening:
  FasterQwen selected suite: 107 passed, 1 warning.
  FasterQwen full suite with Qwen fork: 121 passed, 18 warnings, 287.12s.
  Bridge scripts/check-python.ps1 -UseVenv -VenvPath .venv: 158 tests OK, 2 skipped.
  Bridge ctest --test-dir build\default --output-on-failure: 9/9 passed.
  Real-model context-gate smoke with product compat: semantic_pass=true for all
  raw/strict/product contexts; prefill diff 0.0.
After prefill-only lifecycle correction:
  FasterQwen targeted suite: 52 passed, 1 warning.
  FasterQwen selected suite: 109 passed, 1 warning.
  FasterQwen full suite with Qwen fork: 123 passed, 18 warnings, 298.34s.
  Bridge targeted unittest: 49 tests OK.
  Bridge scripts/check-python.ps1 -UseVenv -VenvPath .venv: 158 tests OK, 2 skipped.
  Bridge ctest --test-dir build\default --output-on-failure: 9/9 passed.
  Real bridge worker-load strict smoke in .venv-packaging:
    metadata wrapper/declared/mode=strict_bf16_sdpa_v1, applied=false,
    validated_modules={rmsnorm:134, mlp:33, attention:33};
    request prefill_backend_used=compile_reduce_overhead and fallback=false.
  Real semantic context-gate smoke:
    semantic_pass=true for all raw/strict/product contexts; prefill diff 0.0.
After concurrency/provenance/cache hardening:
  FasterQwen targeted suite: 54 passed, 1 warning.
  FasterQwen selected suite: 111 passed, 1 warning.
  FasterQwen full suite with Qwen fork: 125 passed, 18 warnings, 292.94s.
  Bridge targeted unittest: 49 tests OK.
  Bridge scripts/check-python.ps1 -UseVenv -VenvPath .venv: 158 tests OK, 2 skipped.
  Bridge ctest --test-dir build\default --output-on-failure: 9/9 passed.
  Wheel-only strict worker smoke:
    faster_qwen3_tts imported from .venv-packaging site-packages, installed
    wheel sha256=e83d500a5f0611e0a6e136b27214ea32c7531f6c36e60695e3ecc2238205c456;
    metadata before warmup, after request, and after close stayed idle
    (applied=false, patched_modules={});
    target_fingerprint={schema_version:1, rmsnorm:134, mlp:33,
    attention:33, expected_decoder_layers:33};
    request prefill_backend_used=compile_reduce_overhead, fallback=false,
    cache_hit=true; cache after close entries=0.
  Wheel-only semantic context-gate smoke:
    semantic_pass=true for all raw/strict/product contexts; prefill diff 0.0.
After compile-cache telemetry clarification:
  FasterQwen targeted suite: 55 passed, 1 warning.
  FasterQwen selected suite: 112 passed, 1 warning.
  FasterQwen full suite with Qwen fork: 126 passed, 18 warnings, 288.82s.
  Bridge targeted unittest: 49 tests OK.
  Bridge scripts/check-python.ps1 -UseVenv -VenvPath .venv: 158 tests OK, 2 skipped.
  Bridge ctest --test-dir build\default --output-on-failure: 9/9 passed.
  Wheel-only strict worker smoke:
    faster_qwen3_tts imported from .venv-packaging site-packages, installed
    wheel sha256=18875c6efde80888667c340051ce55e3bd3506d695ae4ef6e34b6be564629d9e;
    request prefill_backend_used=compile_reduce_overhead, fallback=false,
    cache_hit=true, cache_kind=python_callable_lru, shape_call_ordinal=2;
    wrapper_create_ms=0.0, compiled_call_ms=102.417,
    first_call_ms=0.0, warm_call_ms=102.417; cache after close entries=0;
    CUDA memory snapshots were present before/after prefill and after close.
  Wheel-only semantic context-gate smoke:
    semantic_pass=true for all raw/strict/product contexts; prefill diff 0.0.
After compile-call telemetry hardening:
  FasterQwen targeted suite: 57 passed, 1 warning.
  FasterQwen selected suite: 114 passed, 1 warning.
  FasterQwen full suite with Qwen fork: 128 passed, 18 warnings, 301.03s.
  Bridge targeted unittest: 49 tests OK.
  Bridge scripts/check-python.ps1 -UseVenv -VenvPath .venv: 158 tests OK, 2 skipped.
  Bridge ctest --test-dir build\default --output-on-failure: 9/9 passed
  after retry; one earlier run hit a transient stdio_transport_test ready
  timeout, then stdio_transport_test passed 5/5 with --repeat until-fail:5.
  Wheel-only strict worker smoke:
    faster_qwen3_tts imported from .venv-packaging site-packages, installed
    wheel sha256=3b32e0c39df07ae52591aadd7173fb7f22713344ef4e7dc899befa46beb011be;
    request prefill_backend_used=compile_reduce_overhead, fallback=false,
    cache_hit=true, cache_kind=python_callable_lru, shape_call_ordinal=2;
    compiled_call_host_ms=99.53, call_2_host_ms=99.53,
    warm_call_ms=0.0; cache after request entries=1; cache after close
    entries=0; CUDA memory snapshots were present before/after prefill and
    after close.
  Wheel-only semantic context-gate smoke:
    semantic_pass=true for all raw/strict/product contexts; prefill diff 0.0;
    diagnostic profiles include per-request PyTorch CUDA allocator peaks, for
    example product_strict_reduce_overhead peak reserved=2713714688 bytes.
```

The patch and bundle are saved under
`docs/benchmark-artifacts/rtx4090-2026-07-22/faster-qwen-strict-bf16-sdpa-product-patch/`.
The lifecycle-hardened and prefill-only correction patches and bundles are
saved under
`docs/benchmark-artifacts/rtx4090-2026-07-22/faster-qwen-strict-bf16-sdpa-lifecycle-patch/`.

### Product Opt-In Performance A/B

Restart-based source-worker benchmark, RTX 4090, CustomVoice 0.6B, speaker
`ryan`, BF16, SDPA, chunk size `8`, fixed seed `4242`, greedy decode, one
warmup synthesis before `ready`, `5` runs x `4` requests:

| Mode | Steady first audio median | Steady completed median | Steady RTF median | Steady inverse RTF | Steady prefill median | Talker forward GPU median |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| eager / no compat | 357.2 ms | 1441.3 ms | 0.379 | 2.64x | 136.2 ms | 130.6 ms |
| Inductor default / `strict_bf16_sdpa_v1` | 322.4 ms | 1363.5 ms | 0.358 | 2.79x | 109.2 ms | 103.7 ms |
| reduce-overhead / `strict_bf16_sdpa_v1` | 228.1 ms | 1266.6 ms | 0.333 | 3.01x | 11.3 ms | 5.7 ms |

Relative to eager, `compile_reduce_overhead + strict_bf16_sdpa_v1` improves
steady first-audio latency by about `1.56x`, steady completion/RTF by about
`1.14x`, and the measured steady prefill bucket by about `12.0x`. Profile
validation was complete for all three reports.

Artifacts:

```text
product-compat-performance/source-worker-eager-r5x4.json
product-compat-performance/source-worker-product-strict-inductor-default-r5x4.json
product-compat-performance/source-worker-product-strict-reduce-r5x4.json
product-compat-performance/summary.json
```

Current recommendation: keep product defaults eager, but treat
`compile_reduce_overhead + strict_bf16_sdpa_v1` as the first realistic opt-in
candidate for this RTX 4090 CustomVoice shape. VoiceDesign was not validated
because the local model is CustomVoice only. CMP 50HX compatibility remains a
future hardware profile; the mode's fail-closed BF16/SDPA checks should help,
but it still needs a real run on that card before being advertised.

### Shape/Cache Matrix

The first single-worker shape/cache matrix used FasterQwen `3daf26a`, the
installed wheel SHA
`3b32e0c39df07ae52591aadd7173fb7f22713344ef4e7dc899befa46beb011be`,
CustomVoice 0.6B, BF16, SDPA, speaker `ryan`, and 10 real prompt lengths:

```text
16, 21, 23, 24, 29, 39, 40, 30, 32, 35
```

This matrix is not a cold-start benchmark; local PyTorch/Triton compiler caches
were already warm from prior validation. It is a cache-behavior diagnostic.

Key result: dynamic compile-on-miss is not product-safe for arbitrary prompt
lengths. Both compiled modes successfully cache the first 8 observed shapes and
then hit `torch._dynamo config.recompile_limit (8)` on later unseen lengths.
The Python callable LRU itself behaves correctly, but it cannot bypass Dynamo's
per-frame recompilation limit.

Observed single-worker behavior:

| Context | Rows | Compiled rows | Cache entries | Errors/Fallbacks | Host timing summary |
| --- | ---: | ---: | ---: | ---: | --- |
| eager | 69 | 0 | 0 | 0 / 0 | no compiled call telemetry |
| strict Inductor default | 69 | 56 | 8 | 2 / 13 | call1 median `6381.734 ms`; call2 median `100.370 ms`; call3+ median `106.391 ms` |
| strict reduce-overhead, fresh process | 69 | 56 | 8 | 2 / 13 | call1 median `6376.399 ms`; call2 median `163.535 ms`; call3+ median `2.832 ms` |

The fast `reduce-overhead` path is real, but it appears only for already
compiled shapes at ordinal `3+`. Ordinal `2` is still a CUDA Graph
warmup/capture-ish call and should not be called steady replay.

The eviction subtest with `max_entries=4` passed at the Python LRU layer:
`L1_refresh` was a hit with ordinal `2`, `L5_cold` evicted one old entry,
`L2_after_eviction_candidate` was cold again with ordinal `1`, and
`L1_after_refresh` remained hot with ordinal `3`; final entries were `4` and
eviction delta was `2`.

Recommendation update: do not ship unbounded dynamic compile-on-miss. The next
product direction is an exact-length compiled allowlist for common
`talker_prefill_length` values, plus eager fallback for unknown exact lengths.
Padded buckets are a separate correctness project and must not be treated as
equivalent until right-padding, last-token indexing, KV copy length,
`cache_position`, and semantic parity have been verified.

### Exact-Length Allowlist Gate

The first product-shaped exact-length allowlist pass used FasterQwen branch
`prefill-compile-exact-shape` through local commit `7e68b57`, installed from
wheel SHA256
`5ef9a4c9ba6e30191316437f6783c8673ef645c3576cc167e9867579dafd22de`.
The bridge worker wheel SHA256 was
`8aec77800aa7537d03e4e1818404b1d9f741c7e1b0a1df6d836cc853870b63f2`.

An offline histogram over `500` CustomVoice 0.6B preparation-only prompts
selected these exact `talker_prefill_length` values:

```text
32, 29, 35, 34, 33, 30
```

Coverage on that synthetic representative set was `239 / 500 = 47.8%`.
This histogram is product-shaped for the local 0.6B CustomVoice model: voice
instructions are ignored during preparation because the runtime generation path
also drops `instruct` for `tts_model_size=0b6`.

Wheel-only allowlist gate result: pass. For all six selected exact lengths,
compiled `compile_reduce_overhead + strict_bf16_sdpa_v1` reached ordinal `3`,
reported `prefill_shape_policy=compiled_allowlist`, used
`prefill_backend_used=compile_reduce_overhead`, had
`prefill_compile_fallback=false`, and matched eager with `max_abs=0.0`.

Wheel-only strict worker smoke result: pass. With
`prefill_compile_on_miss=false`, the request length `32` hit the allowlist and
reported `prefill_shape_policy=compiled_allowlist`,
`prefill_shape_allowlist_hit=true`, and `prefill_compile_fallback=false`.

Wheel-only mixed persistent-worker benchmark result:

| Metric | Result |
| --- | ---: |
| allowlisted measured requests | 6 / 12 |
| unknown measured requests | 6 / 12 |
| compiled allowlist policy count | 6 |
| eager unknown policy count | 6 |
| compile fallback count | 0 |
| measured length mismatch count | 0 |
| first audio median | 309.1 ms |
| first audio p95 | 412.4 ms |
| completed median | 3009.7 ms |
| RTF median | 0.363 |
| inverse RTF median | 2.75x |

Artifacts:

```text
prefill-length-histogram-customvoice-500.json
prefill-allowlist-gate-top6-wheel.json
strict-worker-load-smoke-exact-allowlist-wheel.json
prefill-mixed-workload-schedule.jsonl
prefill-mixed-workload-wheel.json
faster-qwen-exact-length-allowlist-patch/0001-feat-prefill-add-exact-length-compile-policy.patch
faster-qwen-exact-length-allowlist-patch/0002-fix-prefill-allow-strict-causal-mask-replay.patch
faster-qwen-exact-length-allowlist-patch/faster-qwen-prefill-exact-allowlist-through-7e68b57.bundle
```

Companion artifact SHA256:

```text
prefill-length-histogram-customvoice-500.json d3e5e9425ccdc5096fbb953ccb552c2382c0a49451c79a953c5297b6323e6a5b
prefill-allowlist-gate-top6-wheel.json 3ff2a2f727f2f5df80cb56e536f38eeea9fac8581ad9030bb835c15ff899e3f5
strict-worker-load-smoke-exact-allowlist-wheel.json fe178e5ecf8da4dce99206b32d2262b9cb6fd770030b1d7713ed4f7f2423819c
prefill-mixed-workload-wheel.json 0ba4679f781294ddf0216ed19d265198314b4cf1c2f6e0fc398bf4a5ee2b876f
0001-feat-prefill-add-exact-length-compile-policy.patch f3c695153cf3913f1ae3a7badf438fe8bb79f6ccd3bdd5b5ac478577a7aa5435
0002-fix-prefill-allow-strict-causal-mask-replay.patch 7fd7823aef48b22e2ee4a5e16346669156f1d6aa8532cfbda7c4de49ddbfeed3
faster-qwen-prefill-exact-allowlist-through-7e68b57.bundle 8ffc1f73dbcfd3672bf30a3e2679b82629ee0ef2477d351b38d7b1e4e6825422
```

### Startup Prewarmed Exact Allowlist

The product startup path now has a fail-closed exact allowlist mode in the
bridge worker. It requires FasterQwen, `strict_bf16_sdpa_v1`, a non-empty
allowlist of at most six exact lengths, `prefill_compile_on_miss=false`,
`prefill_unknown_shape_policy=eager`, a warmup manifest, and
`prefill_require_precompiled=true`.

Startup prewarm runs before the worker reports ready. For each allowlisted
length, it prepares a manifest prompt under `torch.inference_mode()`, compares
compiled prefill against eager, and runs the compiled form to ordinal `3`.
After that, the bridge flips the loaded FasterQwen model into
`prefill_require_precompiled=true`, so an allowlisted cache miss on the user path
fails instead of compiling silently.

The first fail-closed smoke exposed a useful bug: prewarm inputs were originally
created outside inference mode, while real streaming runs under
`@torch.inference_mode()`. Because FasterQwen's cache key includes
`requires_grad`, the user request was a cache miss even for
`talker_prefill_length=32`. The bridge prewarm now prepares inputs in inference
mode, preserving the stricter grad-aware cache key.

Wheel-only prewarmed strict worker smoke result: pass.

| Metric | Result |
| --- | ---: |
| FasterQwen local commit | `5aadd31` |
| FasterQwen wheel SHA256 | `53df465d0c25304600434f84f440802fd31afdd4e5ef34d6ddc20c72d04741c9` |
| prewarmed lengths | `32, 29, 35, 34, 33, 30` |
| startup prewarm duration | `47821.824 ms` |
| startup prewarm ordinals | `3, 3, 3, 3, 3, 3` |
| first user request cache hit | `true` |
| first user request ordinal | `4` |
| first user request require precompiled | `true` |
| first user request compiled prefill call | `13.653 ms` |
| first user request prefill total | `8135.318 ms` |
| first user request generation state wall time | `8100.611 ms` |
| first user audio wall time | `8644.604 ms` |

Interpretation: the startup cold-compile leak is closed for the tested shape.
The remaining first-request latency is not a prefill compile miss; it is now
dominated by `generation_state_wall_ms`, which should be the next performance
investigation target.

New artifacts:

```text
strict-worker-load-smoke-exact-allowlist-prewarmed-wheel.json
prefill-prewarm-shape-debug.json
faster-qwen-prewarmed-allowlist-patch/0001-feat-prefill-add-exact-length-compile-policy.patch
faster-qwen-prewarmed-allowlist-patch/0002-fix-prefill-allow-strict-causal-mask-replay.patch
faster-qwen-prewarmed-allowlist-patch/0003-fix-prefill-require-prewarmed-compiled-shapes.patch
faster-qwen-prewarmed-allowlist-patch/faster-qwen-prewarmed-allowlist.bundle
```

New artifact SHA256:

```text
strict-worker-load-smoke-exact-allowlist-prewarmed-wheel.json 45e2c432aeecf1889fe718b4d5b54e6bf155abc0de8aed873810d78d51fb19fd
prefill-prewarm-shape-debug.json 4048d77777a7ac4515592ca63a998ac8433f1147f2652181c166d3e9202be25b
0003-fix-prefill-require-prewarmed-compiled-shapes.patch 2556ac4ff8e5ba543217f48433b2d216cdded8f0acdd23000c3d6f4ff1f55abd
faster-qwen-prewarmed-allowlist.bundle 1f4d18a9689121f05f04f9e090fba980be521b744dc162fc743d119a285c7e01
```

### Decode-State Startup Gate

The next focused fix addressed the `generation_state_wall_ms` tail observed
after exact allowlist prewarm. FasterQwen local commit `d6aac14` normalizes the
verified all-valid generation attention mask to the same canonical state as the
`None` mask used during graph capture. It also reports mask key timing, mask
table build timing, cache hit/miss, and the number of masks built.

The bridge startup prewarm now also runs one representative prefill-to-decode
gate before ready:

```text
compiled prefill
-> prefill_kv
-> set_generation_state
-> one TalkerGraph replay
-> reset
```

This does not run codec decode or full speech synthesis. It only proves that
the boundary from compiled prefill into the CUDA-graphed AR decode path is
ready.

Wheel-only decode-state smoke result: pass.

| Metric | Result |
| --- | ---: |
| FasterQwen local commit | `d6aac14` |
| FasterQwen wheel SHA256 | `f3aed60c510f30e2902b8317c93459d37533c6fbe8081ae940bec38bff6af211` |
| startup allowlist duration | `46292.815 ms` |
| startup allowlist ordinals | `3, 3, 3, 3, 3, 3` |
| startup decode-state duration | `21.405 ms` |
| startup decode-state generation state | `0.106 ms` |
| startup decode-state replay | `8.315 ms` |
| first user request cache hit | `true` |
| first user request ordinal | `4` |
| first user request compiled prefill call | `10.651 ms` |
| first user request generation state | `0.114 ms` |
| first user request mask cache hit | `true` |
| first user request masks built | `0` |
| first user prefill total | `96.089 ms` |
| first user AR decode | `194.061 ms` |
| first user codec/wrapper residual | `306.242 ms` |
| first user audio wall time | `596.391 ms` |

Interpretation: the eight-second generation-state table rebuild is removed for
the verified all-valid path. The first user request no longer rebuilds the
2048-entry mask table. The remaining first-PCM latency is now outside compiled
prefill and generation-state setup; in this smoke it is dominated by AR decode
plus codec/wrapper residual. That is the next performance track, not part of
the decode-state cache fix.

The strict exact allowlist startup threshold is now `max_abs == 0.0` for
`strict_bf16_sdpa_v1`; non-zero drift is rejected instead of tolerated up to
`1e-2`.

Decode-state artifacts:

```text
strict-worker-load-smoke-exact-allowlist-decode-state-wheel.json
faster-qwen-decode-state-patch/0001-feat-prefill-add-exact-length-compile-policy.patch
faster-qwen-decode-state-patch/0002-fix-prefill-allow-strict-causal-mask-replay.patch
faster-qwen-decode-state-patch/0003-fix-prefill-require-prewarmed-compiled-shapes.patch
faster-qwen-decode-state-patch/0004-fix-prefill-reuse-all-valid-generation-mask-state.patch
faster-qwen-decode-state-patch/faster-qwen-decode-state-through-d6aac14.bundle
```

Decode-state artifact SHA256:

```text
strict-worker-load-smoke-exact-allowlist-decode-state-wheel.json 88487b1bfe41e6ae5006f317cbcd9cfe49a12a900bb102482cd9fdc7e3a9c462
0004-fix-prefill-reuse-all-valid-generation-mask-state.patch 4d0a9496553990a72dbfe8e45c001bf7720fe3e52e1f17e6b2a2be5f40e94bb6
faster-qwen-decode-state-through-d6aac14.bundle 218ba6ffc38eb4273cbe06b40d7e4e3fc9ba70bac0276358ff7836abb5a3eb83
```

### First-Chunk Startup Prewarm

Phase instrumentation in FasterQwen commit `656b9cb` separated the remaining
first-PCM work into prefill, first sampling, AR decode, codec decode, and
wrapper residual. It confirmed that the large post-startup cold class was no
longer compiled prefill or generation-mask construction. With the decode-state
gate only, the first measured request took `546.42 ms`; its speech-tokenizer
codec decode was `303.06 ms`, versus `64.73-66.12 ms` on the following three
requests. AR decode was also slightly colder (`179.74 ms` versus
`162.87-167.33 ms`).

The bridge therefore has an opt-in `--prefill-first-chunk-warmup` startup gate.
It uses the first exact-allowlist manifest row, generates exactly one PCM chunk
before `ready`, restores Python/NumPy/Torch CPU and CUDA RNG states, resets the
TalkerGraph cache under `torch.inference_mode()`, and clears internal chunk
metrics. It is valid only with the existing fail-closed exact allowlist mode.
Thus the user-visible stochastic request starts from the same RNG state it
would have had without this service warmup.

Wheel-only strict smoke, CustomVoice 0.6B, speaker `ryan`, BF16/SDPA,
`compile_reduce_overhead + strict_bf16_sdpa_v1`:

| Metric | Result |
| --- | ---: |
| FasterQwen commit / wheel SHA256 | `656b9cb` / `b12ed98d...a017d0` |
| exact prewarmed lengths | `32, 29, 35, 34, 33, 30` |
| allowlist warmup | `49165.314 ms` |
| decode-state warmup | `125.272 ms` |
| first-chunk warmup | `554.132 ms` |
| first-chunk generated audio | `551.643 ms` |
| reset after first chunk | `1.577 ms` |
| next user first PCM | `245.548 ms` |
| user prefill / AR decode / codec residual | `14.173 / 162.836 / 68.538 ms` |
| user compiled prefill fallback | `false` |
| user all-valid generation-mask cache hit | `true` |

The tested wheel remained installed from the wheel path recorded in the smoke
artifact, rather than importing the FasterQwen source worktree. Its request
used an allowlist cache hit at ordinal `5`, with `max_abs=0.0` during all six
strict warmup validations.

The representative restart benchmark uses the same CustomVoice model and
speaker, a fixed seed `4242`, 94-character English text, exact prefill length
`32`, `4` requests per fresh worker process, and a `20 ms` paired-tail
threshold. It measures worker startup separately from the post-ready client
request path.

| Metric | 30 fresh workers / 120 requests |
| --- | ---: |
| startup to ready p50 / p95 | `63609.831 / 64743.813 ms` |
| first request first PCM p50 / p95 / max | `256.009 / 267.553 / 269.883 ms` |
| steady request first PCM p50 / p95 / max | `252.359 / 259.570 / 265.861 ms` |
| paired first-minus-steady median / p95 / max | `+3.333 / +12.475 / +17.424 ms` |
| positive tails above `20 ms` | `0 / 30` |
| unstable runs | `0 / 30` |

This closes the observed user-visible first-chunk cold class for this exact
RTX 4090 configuration. It does not claim a universal startup latency: the
roughly 64-second startup cost is deliberately paid before the worker reports
ready, and the compiled shapes, model family, runtime, driver mode, and GPU
remain part of the measured contract. Unknown prompt lengths still use the
configured eager fallback rather than silently compiling during a request.

Artifacts:

```text
strict-worker-load-smoke-exact-allowlist-first-chunk-wheel.json
exact-allowlist-first-chunk-warmup-instrumented-r1x4.json
exact-allowlist-first-chunk-warmup-instrumented-r30x4.json
faster-qwen-first-chunk-profile-patch/0001-fix-prefill-reject-contradictory-all-valid-masks.patch
faster-qwen-first-chunk-profile-patch/0002-feat-profile-split-first-chunk-decode-phases.patch
faster-qwen-first-chunk-profile-patch/faster-qwen-first-chunk-profile-through-656b9cb.bundle
```

Artifact SHA256:

```text
strict-worker-load-smoke-exact-allowlist-first-chunk-wheel.json fdada10a129af93ad35cbff53a860e291219201f1d0430d31933894d9f1ffdc1
exact-allowlist-first-chunk-warmup-instrumented-r1x4.json a85574c869b334219d859ad799c414dec380271555694147b3b4256af60404c4
exact-allowlist-first-chunk-warmup-instrumented-r30x4.json 3bb51009e25e8b7cd99c65201765c43d074096af2a39b93247c0e29e503cc943
0001-fix-prefill-reject-contradictory-all-valid-masks.patch 3668f6e7731d26d0f0b2ef0e4af2f57495c97f9ef6abb7e1257b54ecded7dd0e
0002-feat-profile-split-first-chunk-decode-phases.patch 50ea169a4a97832971b5e626f6c559b4b00a5fa07cffed3f81b255eda59b3d0e
faster-qwen-first-chunk-profile-through-656b9cb.bundle cd749f13157e9e2b54eee127b5a0c9bfeba73e44b8d999fc18397da70d76f1cf
```

### First-Chunk Correctness Hardening

The first-chunk latency result above did not by itself prove that partial
generation warmup was semantically neutral. The startup path is now
fail-closed for the exact-allowlist product mode:

- `prefill_first_chunk_warmup_length` is required, must be one of the exact
  allowlisted lengths, and is resolved from the manifest by that explicit key.
  Reordering the allowlist no longer changes the warmup request.
- First-chunk warmup and ordinary `warmup_synthesis` are mutually exclusive.
- Python, NumPy, Torch CPU, and all available CUDA RNG states are captured and
  restored around the partial generation. In strict first-chunk mode, capture
  or restore failure is a startup error; the worker does not report ready.
- The bridge no longer accesses `model.talker_graph` directly. It requires
  FasterQwen's public `reset_after_partial_generation()` contract after it has
  closed the partial stream. API version `1` resets TalkerGraph and both
  PredictorGraph caches under `torch.inference_mode()` while preserving CUDA
  Graph capture, generation-mask tables, and compiled prefill cache entries.

The wheel-only semantic A/B script is:

```text
scripts/qwen-first-chunk-warmup-semantic-ab.py
```

It starts independent worker processes for warmup off and on, then compares the
same user request. The trace contains PCM SHA-256, sample count, audio chunk
count, cumulative codec-token SHA-256, codec frame count, and terminal
reason/token/step/flag telemetry. Codec trace collection is opt-in in
FasterQwen and does not run in the normal production path.

The original `r20` run proved audio and codec parity, but it is not treated as
full terminal parity: two sampling cases had absent terminal fields and the old
comparison allowed `null == null`. FasterQwen commit `4f88107` now publishes
terminal accounting through an explicit sink after the generator has completed,
including paths where no final audio chunk is yielded. The semantic runner is
fail-closed: it rejects missing termination reason, generated/emitted counts,
or reason-specific terminal data; it verifies the installed wheel SHA-256 from
`direct_url.json`; and every child report records the bridge, FasterQwen and
Qwen-fork commits plus Torch, CUDA, GPU, and NVIDIA driver provenance.

Full terminal-parity result, CustomVoice 0.6B, RTX 4090, bridge commit
`d06988b`, FasterQwen commit `4f88107`, Qwen fork commit `4082363`, installed
wheel SHA256
`aff052c355a879dad12e2cff5be14780671a057ec6e7f25518f4f8213baa9485`,
Torch `2.10.0+cu130`, CUDA `13.0`, NVIDIA driver `591.86`:

| Scenario | Fresh A/B pairs | User reseed | Semantic mismatches | Incomplete terminal traces |
| --- | ---: | --- | ---: | ---: |
| greedy seed `4242` plus sampling seeds `4242-4246` | 6 | enabled | 0 | 0 / 12 |
| greedy seed `4242` plus sampling seeds `4242-4246` | 6 | disabled | 0 | 0 / 12 |
| total | 12 | both controls | 0 | 0 / 24 |

For the normal fixed-seed control, greedy matched `2015` codec frames, `252`
PCM chunks, identical PCM and codec SHA-256 values, and `max_seq_len` at step
`2014`; all five sampling seeds reached the same EOS token and step on both
arms. The no-user-reseed control sets the engine request seed to `None`, seeds
Python/NumPy/Torch only after model load and before warmup, then leaves the user
request unreseeded. Its six on/off pairs also matched every contract field. The
two controls intentionally need not match each other, because their sampling
RNG schedules differ. Every child imported FasterQwen from the installed
`.venv-qwen-flash` wheel rather than the external source worktree.

Correctness artifacts:

```text
first-chunk-warmup-semantic-ab-r20.json
first-chunk-semantic-ab-fixed-r5.json
first-chunk-semantic-ab-no-reseed-r5.json
faster-qwen-first-chunk-correctness-patch/0001-feat-streaming-add-partial-generation-reset-contract.patch
faster-qwen-first-chunk-correctness-patch/0002-fix-streaming-reset-partial-state-in-inference-mode.patch
faster-qwen-first-chunk-correctness-patch/faster-qwen-first-chunk-correctness-through-66fb5e9.bundle
faster-qwen-terminal-trace-patch/0001-fix-streaming-publish-terminal-trace-after-final-yie.patch
faster-qwen-terminal-trace-patch/faster-qwen-terminal-trace-through-4f88107.bundle
```

Artifact SHA256:

```text
first-chunk-warmup-semantic-ab-r20.json 571ce0cbce38806aff1f16a8ea619122df17391628ce75fdeff80b379c9791bc
first-chunk-semantic-ab-fixed-r5.json 9d953196383298b39093b9e905102b5a9e18ae282a7a0f9f8fa069d0dca7e8d8
first-chunk-semantic-ab-no-reseed-r5.json 5ecdacfbde70a88a64dec08f25c43945eb30f1751e41dfd5d41312618959b929
0001-feat-streaming-add-partial-generation-reset-contract.patch b8824531eb13b5c691717d2e00f74314314e815d168988c8f0de08543fe5327b
0002-fix-streaming-reset-partial-state-in-inference-mode.patch 3fb0fb3048eddf35ccccd998f38f35df30bba41b28c1acfd0efbe93cb665776e
faster-qwen-first-chunk-correctness-through-66fb5e9.bundle 5648a46be8313bf190b2f98b27db1450d40f5bf1656c89fd332912526560b7a3
0001-fix-streaming-publish-terminal-trace-after-final-yie.patch b4b95ccbc1193e611e8971944fc2ba41a5a769ef31f6b59a68aa6a7c4f08f4d8
faster-qwen-terminal-trace-through-4f88107.bundle 83d7059f6c7fa585b70de3e9f479f86b10eeac9d1776db99c04a7faa93250702
```

### Fresh-Process Exact-Allowlist Discovery And Terminal Trace Contract

The terminal trace has a single explicit normal-completion contract. Both
`generated_steps` and `emitted_steps` count accepted non-EOS codec frames in a
fully consumed normal stream, so they must equal `codec_frame_count`. For an
EOS termination, `terminal_step_index` identifies the rejected EOS candidate
and therefore equals those counts. For `max_new_tokens` and `max_seq_len`, it
identifies the last emitted codec frame and therefore equals the count minus
one. Exactly one terminal flag is set and it must agree with
`termination_reason`.

The reusable validator rejects absent or contradictory terminal fields,
negative counters, mismatched frame counts, and impossible terminal indices.
Future semantic A/B reports use schema version 2 and take a provenance manifest
rather than separately supplied source and wheel identifiers. The manifest
binds the installed FasterQwen wheel SHA256
`d08691143ae8ab30f6199f091326e58a9c518d1ab60008fff2849060d23ee9ce` to
source commit `db6361d69386b345c2d2a415d3b9dc080de4ecfd` and the exported
companion bundle. The wheel hash remains the executable identity; the source
commit is a declared, reviewable provenance link.

A shuffled fresh-process discovery matrix then ran 45 source-worker processes
with four requests each: five processes for every exact allowlist length
`29, 30, 32, 33, 34, 35`, and five each for eager unknown lengths `31`, `38`,
and `45`. It used CustomVoice 0.6B, speaker `ryan`, BF16 SDPA,
`compile_reduce_overhead + strict_bf16_sdpa_v1`, fail-closed startup prewarm,
first-chunk warmup, fixed seed `4242`, and completed-generation trace capture.
Every one of the 180 requests passed the terminal trace contract. All selected
lengths reported compiled-allowlist routing with a precompiled cache hit; all
unknown lengths reported eager routing without an accidental compile fallback.

| Category | Fresh processes | First TTFA p50 | First TTFA p95 | First-minus-steady p95 |
| --- | ---: | ---: | ---: | ---: |
| allowlist 29 | 5 | 254.1 ms | 257.7 ms | 3.5 ms |
| allowlist 30 | 5 | 256.9 ms | 261.5 ms | 7.4 ms |
| allowlist 32 | 5 | 257.3 ms | 258.3 ms | 4.7 ms |
| allowlist 33 | 5 | 257.6 ms | 264.6 ms | 6.5 ms |
| allowlist 34 | 5 | 253.6 ms | 257.0 ms | 2.2 ms |
| allowlist 35 | 5 | 255.0 ms | 258.2 ms | 2.9 ms |
| unknown 31 | 5 | 386.1 ms | 393.0 ms | 12.2 ms |
| unknown 38 | 5 | 385.5 ms | 391.8 ms | 9.7 ms |
| unknown 45 | 5 | 393.2 ms | 397.8 ms | 9.9 ms |

The discovery validator intentionally applies a provisional `<300 ms` first
TTFA threshold to every category. Consequently the aggregate result is marked
failed only for the three eager unknown categories; their p95 values are
`393.0`, `391.8`, and `397.8 ms`. This is not a trace, warmup-neutrality, or
routing failure. It demonstrates the expected product boundary: the exact
prewarmed allowlist is consistently below 300 ms, while unknown exact lengths
take the eager path at roughly 0.38-0.40 s. All categories satisfy the separate
`<20 ms` p95 first-minus-steady criterion. A future product decision should
either define a separate eager-unknown latency target or expand the allowlist
only after correctness and startup-cost review.

Artifacts:

```text
faster-qwen-provenance-v1.json
faster-qwen-terminal-contract-patch/faster-qwen-terminal-contract-through-db6361d.bundle
fresh-process-matrix-discovery-r5-schedule.jsonl
fresh-process-matrix-discovery-r5.json
fresh-process-matrix-discovery-r5-summary.json
```

Artifact SHA256:

```text
faster-qwen-terminal-contract-through-db6361d.bundle 0d63656c407a39dda2bb58136beb97834ba9053f345e1b94a95572656914c00d
fresh-process-matrix-discovery-r5-schedule.jsonl 0ada5f6e9b1403e8e6f09b27cb420293d31b5ef247d3a4331a50506996147969
fresh-process-matrix-discovery-r5.json 6b6c5b1f8d035ff5ffad374292dc8980cba5298cd2af695d2e06f1282ea84fc3
fresh-process-matrix-discovery-r5-summary.json 3da0a6baa048ee5717cd574f955c9cb932b44706b16c3ef83b01bdeb8eea6bc1
```

### Release Candidate Validation: Exact Allowlist And Long-Lived Worker

The deployed release candidate uses `strict_bf16_sdpa_v1` with the exact
prewarmed lengths `29, 30, 32, 33, 34, 35`. Known lengths use
`compile_reduce_overhead`; unknown lengths are deliberately eager and may not
create a graph or mutate the prewarmed cache. The validation wheel was built
from FasterQwen commit `20fb8586348878257c99eb9d1ae7b6054ee2252e` and has
SHA256 `142ba31dc7e3c8fa76a21007c89677ee4849385212f99bd2a7ea70db234d70e1`.
It adds per-request observability for compile attempts, cache-entry and
eviction deltas, and Dynamo unique-graph deltas. The bridge-side run used
commit `881d2710cd9996cb331dd6f0e44889a435324a74`, Python 3.12, Torch
`2.10.0+cu130`, CUDA 13.0, BF16 SDPA, CustomVoice 0.6B, and fixed seed `4242`.

The shuffled `r20` fresh-process matrix contains 100 independent workers and
400 requests: four workers for each of 20 language/speaker/length scenarios.
Every completed request passed the terminal-trace validator. Every known
length used the precompiled exact-allowlist route with no compile attempt;
every unknown length stayed eager, also with no compile attempt. Cache and
Dynamo counters had zero deltas after startup. The validator has separate
latency acceptance for the two product routes: compiled p95 `<300 ms` and
eager-unknown p95 `<450 ms`. It keeps an informational global `<300 ms` line,
which is expected to be false for a mixed workload containing eager requests.

| Route/category | Fresh workers | TTFA p50 | TTFA p95 | First-minus-steady p95 |
| --- | ---: | ---: | ---: | ---: |
| compiled allowlist 30 | 20 | 254.6 ms | 259.4 ms | 8.1 ms |
| compiled allowlist 32 | 20 | 256.2 ms | 265.5 ms | 9.6 ms |
| compiled allowlist 33 | 20 | 254.4 ms | 257.7 ms | 6.0 ms |
| eager unknown short | 20 | 381.5 ms | 393.4 ms | 10.7 ms |
| eager unknown long | 20 | 380.1 ms | 394.4 ms | 10.1 ms |

The paired all-eager baseline uses the identical 100-worker schedule and the
same installed FasterQwen wheel. For known compiled shapes, candidate TTFA
improved from 382.2 ms median / 430.8 ms p95 to 254.9 ms median / 264.3 ms
p95. The paired median candidate-minus-baseline TTFA is -128.4 ms and its p95
is -113.9 ms. The tradeoff is startup: the compiled candidate has 62.98 s
median startup versus 22.93 s for all-eager, a +40.19 s paired median cost.
For unknown eager shapes, the candidate's median TTFA is 381.3 ms versus
394.6 ms baseline; the paired p95 delta is +17.7 ms, so this route remains a
separate diagnostic/product SLA rather than a claimed compile speedup.

The long-lived-worker `r500` soak then reused one loaded worker for 500 mixed
requests, cycling the same five categories. It completed 451 requests and
cancelled 49 immediately after their first PCM frame. All 49 cancellations
were followed by a completed request; no terminal trace, routing, cache, or
Dynamo invariant failed. The prewarmed compiled-cache entry count remained
exactly six. Worker RSS changed from 4,141,056 to 4,210,688 bytes (+0.066 MiB)
and GPU memory from 4,404 to 4,405 MiB across 21 snapshots. Completed-request
TTFA was 252.9 ms median / 377.6 ms p95; full completion was 2,758.5 ms median
/ 5,066.2 ms p95 with real-time factor 0.3722 median / 0.4079 p95. Cancellation
after first audio took 227.1 ms median / 231.1 ms p95.

The FasterQwen real-model parity suite also passed in this configuration:
`tests/test_e2e_parity.py` reported 14 passed in 244.82 s. It exercised Base,
CustomVoice, and VoiceDesign parity on CUDA. The suite emitted 17 dependency
deprecation warnings only.

### Semantic Cancellation Smoke: All Shapes

The original `r500` memory line measured the launcher process and global GPU
usage, so it is retained only as historical evidence. The replacement gate
walks the worker process tree, records its model PID in every snapshot, and
requires CUDA allocator metrics from that exact PID for every terminal request.
On this Windows WDDM host, `nvidia-smi --query-compute-apps` identifies that
PID but reports its memory as `[N/A]`; the artifact records that limitation
explicitly instead of substituting global GPU usage.

The `r63` semantic smoke used the same strict CustomVoice configuration and
wheel, but the current runtime was Python 3.12.10 with Torch `2.10.0+cu130`
(CUDA 13.0). It covered all six exact allowlist lengths (`29, 30, 32, 33, 34,
35`) plus unknown lengths `31, 38, 45`. Each category ran one deterministic
reference, one cancellation at each of `before_first_audio`,
`after_first_audio`, and `after_third_audio`, and a fixed-seed post-cancel
audit. The audit compares complete PCM SHA256, byte/chunk totals, and the
terminal codec trace. All 63 requests passed: 36 completed, 27 cancelled,
the exact compile cache stayed at six entries, and no semantic fingerprint
changed after cancellation.

| Measure | Result |
| --- | ---: |
| Completed TTFA median / p95 | 259.3 / 383.7 ms |
| Completed RTF median / p95 | 0.3766 / 0.3997 |
| Cancellation latency median / p95 | 230.5 / 255.4 ms |
| Process-tree RSS growth | +32.3 MiB |
| Process-tree private-byte growth | +38.7 MiB |

This smoke is a correctness and lifecycle gate, not a production workload
forecast. Its weighted operation order is deterministic and deliberately
contains more cancellation/audit traffic than typical application traffic.

The follow-up `r900` run used the identical immutable wheel and configuration.
It completed with `acceptance_pass = true`: 792 completed requests and 108
cancelled requests. Every one of the nine categories received four
cancellations at each stage, for 12 cancellations per category. All nine
reference/audit pairs retained their PCM and terminal-codec fingerprints; no
route, graph, cache, allocator, or process-identity gate failed. The cache
remained exactly six entries. Completed TTFA was 257.5 ms median / 386.5 ms
p95, completion 3240.3 / 4841.4 ms, RTF 0.3748 / 0.3954, and cancellation
latency 232.1 / 378.1 ms (median / p95). Process-tree RSS grew 34.4 MiB and
private bytes 40.3 MiB, with a 2454.6 MiB RSS peak. The WDDM limitation remains
explicit: PID presence was observed in every snapshot, while per-PID GPU memory
values were unavailable; the worker's CUDA allocator metrics were present for
all 900 terminal events.

### Public C++ API Soak

The native `qwen_tts_latency_benchmark` was extended with explicit per-request
seed and first-PCM cancellation controls, then exercised against the same real
worker through `QwenTtsClient` and `StdIoTransport`. The run used the compiled
allowlist-32 scenario, three warmups, 200 measured requests, fixed seed `4242`,
and cancelled every tenth measured request from the C++ audio callback.

The independent artifact validator accepted the result: 180 completed requests,
20 first-PCM cancellations, zero failed terminal states, one worker PID, cache
entry count six, zero compile/cache/Dynamo deltas, and compiled route selection
for all 200 measured C++ requests. The C++ completion TTFA was 257.0 ms median
/ 261.4 ms p95; completion was 2940.3 / 2953.8 ms; and RTF was 0.378 / 0.380.
Startup was 66.5 s. This is a public-API lifecycle check, not an estimate of
multi-request application throughput.

### Experimental Runtime Profile and Wheel Gates

`config/rtx4090-faster-customvoice-experimental.json` records the measured
strict CustomVoice configuration, while
`scripts/start-rtx4090-faster-customvoice.ps1` turns that profile into the
worker's existing CLI arguments. The profile is intentionally explicit rather
than a new runtime configuration format: it uses BF16 SDPA,
`compile_reduce_overhead`, the exact six-shape allowlist, fail-closed compiled
cache misses, and the first-chunk warmup at length 32. Unknown prompt shapes
remain eager by design.

Two independent post-soak checks used the installed immutable FasterQwen wheel
from `site-packages`, with the Faster source worktree forbidden from the import
path. The strict worker smoke prewarmed all six shapes, then hit compiled
allowlist length 32 on its first real PCM request. Its wheel archive and the
installed `direct_url.json` both have SHA256
`142ba31dc7e3c8fa76a21007c89677ee4849385212f99bd2a7ea70db234d70e1`.
The independent context gate compared raw eager, strict eager, strict compiled,
and product-compatibility compiled prefill on the same prompt. Every comparison
had zero prefill max-absolute difference and equal codec tokens, waveform,
frame count, and termination through 64 generated tokens.

Artifacts:

```text
faster-qwen-provenance-v2.json
faster-qwen-request-compile-telemetry-patch/0001-feat-prefill-expose-request-compile-telemetry.patch
faster-qwen-request-compile-telemetry-patch/faster-qwen-request-compile-telemetry-through-20fb858.bundle
compile-telemetry-clean-smoke.json
compile-telemetry-clean-smoke-summary.json
confirmatory-r20-scenarios.jsonl
confirmatory-r20-schedule.jsonl
confirmatory-r20.json
confirmatory-r20-summary.json
release-ab-all-eager-r20.json
release-ab-summary.json
mixed-soak-r500.json
release-soak-smoke-r63.json
release-soak-r900.json
cpp-api-soak-r200.json
cpp-api-soak-r200-validation.json
cpp-api-soak-r200-worker-metrics.log
strict-worker-load-smoke-r900-wheel-only.json
context-gate-r900-wheel-only.json
```

Artifact SHA256:

```text
mixed-soak-r500.json c88dfdf7e3ca4a43a2d632a398f2f8dcf2e56539e4ce0536f4e1fd2590e6ce01
release-soak-smoke-r63.json e841893045d589739cb88b00fffecee0eacb421552d00fa9fbe714a288ce9cba
release-soak-r900.json 3c11e8b12201db28421c098e28e6f840ad182eb2f078c54f2847e19a3b70c1e5
cpp-api-soak-r200.json 6c9b966c077557cfa8b0b47c68d89eab42d674d9a630331795393042fb605e4a
cpp-api-soak-r200-validation.json 4ec5a8a86ac56853de8ec861e4e364997b68efa0282b5f8b6741de19100ccfd3
cpp-api-soak-r200-worker-metrics.log e8f0a0bbf468682398ec879174199356996d072eb77d0545f3a79d6e8fe4ee6f
strict-worker-load-smoke-r900-wheel-only.json b04fd32d8269314bc165e06755489f803094f537434a0f79ed9471d0c8f7ef44
context-gate-r900-wheel-only.json e7b5463c60c46ae47b528aa7ee48e72f5d199bf67306ef7a471798a3c0e5c608
```

### Scheduled First PCM Candidate

FasterQwen commit `0f85465` adds an opt-in frame scheduler for streaming PCM:
the first chunk is emitted after 6 codec frames, the second after 8, and the
third and every later chunk after 12. The bridge exposes it only on the Faster
backend through `--emit-chunk-schedule 6,8,12`; the existing fixed
`--emit-every-frames` behavior remains the default. The companion wheel used
for this candidate has SHA256
`34a56cbde0ef00850404caac5ec818e4533096a5567bf7732bffdbc88d9a6752`.

`config/rtx4090-faster-customvoice-scheduler-6-8-12-experimental.json` is the
explicit RTX 4090 CustomVoice profile for that opt-in. The existing launcher
reads `emit_chunk_schedule` when present, so the profile can be selected with
its `-ProfilePath` argument without inventing a second worker configuration
format.

The strict wheel-only smoke passed with the Faster source worktree forbidden
from imports. It prewarmed all six exact prefill forms, then used compiled
allowlist length 32 on the first real request. Its three observed chunk tuples
were `(chunk_steps, chunk_target_steps, chunk_schedule_index) = (6, 6, 0),
(8, 8, 1), (12, 12, 2)`.

The 63-request semantic/cancellation soak also passed: all nine shape classes
completed their reference and post-cancellation fingerprint checks; 36
requests completed and 27 were cancelled. This run's first audio median/p95
was `216.1 / 344.5 ms`, completion `2830.2 / 4316.7 ms`, and RTF
`0.3447 / 0.3629`. The previous fixed-8 r63 run measured `259.3 / 383.7 ms`,
`3082.6 / 4738.0 ms`, and `0.3766 / 0.3997` respectively. This is encouraging
but intentionally not presented as a paired performance claim: the two runs
use different immutable FasterQwen wheels and have independent samples.

The public C++ API soak passed with the scheduled profile through
`QwenTtsClient` and `StdIoTransport`: 3 warmups, 50 measured requests, fixed
seed `4242`, and cancellation every tenth request from the audio callback. The
validator checked that all 50 first PCM metrics reported both `chunk_steps` and
`chunk_target_steps` equal to 6. It accepted 45 completions and 5 first-PCM
cancellations, with one worker PID and exactly six prewarmed cache entries;
there were no failed requests. C++ completion metrics were:

| Measure | Median | p95 |
| --- | ---: | ---: |
| First audio | 216.4 ms | 225.3 ms |
| Completion | 2687.5 ms | 2749.5 ms |
| RTF | 0.344 | 0.352 |
| Transport/dispatch residual | 0.756 ms | 0.886 ms |

Scheduler artifacts:

```text
release-soak-schedule-r900.jsonl
release-soak-schedule-6-8-12-r63.json
strict-worker-load-smoke-schedule-6-8-12-wheel.json
cpp-api-soak-schedule-6-8-12-r50.json
cpp-api-soak-schedule-6-8-12-r50-validation.json
cpp-api-soak-schedule-6-8-12-r50-worker-metrics.log
faster-qwen-first-chunk-scheduler-patch/0001-feat-streaming-schedule-first-PCM-chunks.patch
faster-qwen-first-chunk-scheduler-patch/faster-qwen-first-chunk-scheduler-through-0f85465.bundle
```

Scheduler artifact SHA256:

```text
release-soak-schedule-r900.jsonl 018b6be15af4cc9aa4db19e3d54de2ca9b6abde1685f593a26b98e16ad429d4f
release-soak-schedule-6-8-12-r63.json b08705fe4c5714a416046bfd757ead3320d2ebc275eeda4637ed5bc3cb6e3242
strict-worker-load-smoke-schedule-6-8-12-wheel.json e3c80101f973b381a1d78d229f6b941c526a651f3cc51fc0f51c242e0a8feb6c
cpp-api-soak-schedule-6-8-12-r50.json c73f908ff8643442c4f7e939538c4273345a14cb6f07c435d3385ff121eb95d1
cpp-api-soak-schedule-6-8-12-r50-validation.json a34fc6fe087db39c5b692e495d37bb1aa4d7a8c2d79711f5e409f1b98862ef01
cpp-api-soak-schedule-6-8-12-r50-worker-metrics.log 5bfa16211fe243f9067de073161711a7d5b659972cc82c73de0e1d8d47d31f79
0001-feat-streaming-schedule-first-PCM-chunks.patch 82caa9e97aad640d4f1e9a66371aed98a351932cecbccbafe56bb3f512d03991
faster-qwen-first-chunk-scheduler-through-0f85465.bundle 80fb1bcc1eff831293084f342ce67db0aa7b978311932a4edc513afbc1cec0d6
```

### Scheduler Hardening Update - 2026-07-29

The scheduler was hardened in FasterQwen commit `85a70c2`: public wrappers
materialize an iterable schedule once, targets above 64 frames are rejected,
and every emitted chunk is checked against its scheduled target. The bridge now
records every delivered PCM callback, validates the `6,8,12` sequence, and
uses `request_finished.final_pcm_chunk_index` to account for a full final
chunk whose EOS is only known on the following decode step.

The same immutable wheel (`607ee824...ab34d18`) was used for a profile-off,
same-prompt C++ A/B: 3 warmups, 20 measured requests, 4 first-audio
cancellations, fixed seed 4242, and the same six prewarmed exact-prefill
forms. The scheduled run improved first-audio p95 from `267.168 ms` to
`217.069 ms` (a `50.099 ms` reduction). Its completion p95 was `2657.135 ms`
versus `2981.182 ms` and RTF p95 was `0.340` versus `0.384`. This is a narrow
same-wheel measurement, not a general hardware claim.

Both A/B sides passed the simulated 50 ms playback-reserve gate without an
underrun. The fixed-8 minimum post-chunk reserve was `566.875 ms`; the
scheduled minimum was `406.875 ms`. A scheduled C++ r100 follow-up also passed
all protocol, sequence, cache and reserve checks in one worker process:
first-audio median/p95 `211.826 / 222.398 ms`, completion median/p95
`2592.578 / 2711.997 ms`, RTF median/p95 `0.332 / 0.347`, minimum reserve
`406.875 ms`, and no underruns.

A direct fixed-8 versus 6/8/12 PCM diagnostic used the same deterministic
codec trace: `98` codec frames and identical codec SHA256. The PCM byte hashes
are intentionally not equal because FasterQwen's decoder uses a different
context window at different chunk boundaries. The resulting duration delta was
`40.125 ms` (within the explicit 50 ms diagnostic limit), while candidate
boundary jump p95/max was `3937 / 4910` S16 compared with fixed-8
`6362 / 6630`. This is a boundary-continuity diagnostic, not a substitute for
human listening evaluation.

The fresh 63-operation semantic soak passed on all nine mixed prompt shapes:
36 completed requests, 27 cancellations across before-first, after-first and
after-third-audio stages, nine reference/post-cancellation fingerprints, one
worker model PID, and no validation failures. It measured first-audio
median/p95 `214.391 / 340.510 ms`, completion `2820.695 / 4299.761 ms`, and
RTF `0.3424 / 0.3642`. Unknown shapes correctly use eager prefill, so the
observed cache values are `6` for allowlisted forms and `0` for eager forms.

`6 -> 8 -> 12` remains an experimental profile. Do not experiment with
`5 -> 8 -> 12` yet: it is explicitly deferred until the current schedule has
passed the broader shape/cache, p95 playback-reserve and PCM-quality matrix.

Current hardening artifacts:

```text
faster-qwen-provenance-scheduler-hardening-v1.json
faster-qwen-first-chunk-scheduler-hardening-patch/0001-0002-faster-qwen-scheduler-hardening.patch
cpp-api-fixed8-r20-85a70c2.json
cpp-api-fixed8-r20-85a70c2-validation.json
cpp-api-fixed8-r20-85a70c2-playback.json
cpp-api-scheduler-6-8-12-r20-85a70c2.json
cpp-api-scheduler-6-8-12-r20-85a70c2-validation.json
cpp-api-scheduler-6-8-12-r20-85a70c2-playback.json
cpp-api-scheduler-6-8-12-r100-85a70c2.json
cpp-api-scheduler-6-8-12-r100-85a70c2-validation.json
cpp-api-scheduler-6-8-12-r100-85a70c2-playback.json
scheduler-pcm-parity-fixed8-vs-6-8-12-85a70c2.json
release-soak-schedule-6-8-12-85a70c2-r63.json
```

Key artifact SHA256:

```text
faster-qwen-provenance-scheduler-hardening-v1.json c3bf297f5a2be9a1e8a4e02451bc9f79643dfc69762ad38cd1e05e7fcd0d1e1f
cpp-api-scheduler-6-8-12-r100-85a70c2.json 86048e3de01a6da82af0c9d0bf7a563b5ed8cd6f2214f65d3879a5e193cb1780
scheduler-pcm-parity-fixed8-vs-6-8-12-85a70c2.json 8a2f815006857b6accede139fed1196de5b1b5bda76430c0296b45ae07c62bf0
release-soak-schedule-6-8-12-85a70c2-r63.json 949fadb8385ccfc675c4d30e47a9228d0388fc5d390acdfe3711696ed0955221
0001-0002-faster-qwen-scheduler-hardening.patch 8a9e26b9f9003619429de000b755ee2db1c5cb1cb69f0083d58a864dabaa0431
```

### Scheduler PCM Quality Update - 2026-07-29

The original `40.125 ms` PCM-duration discrepancy was a real schedule-sensitive
decoder slicing defect, not an acceptance tolerance to retain. FasterQwen
commit `f62ae52` now uses the tokenizer's exact `1920` samples-per-code-frame
contract and slices each emitted chunk by its actual scheduled frame count.
Commit `5dba850` also adds an opt-in overlap facility, but it is not enabled in
the measured profile because the initial 10 ms crossfade did not improve every
boundary metric consistently.

The same strict RTX 4090 configuration was rerun on nine deterministic cases:
English and Russian, short/medium/long prompts, six speakers, all six compiled
allowlist forms, and three unknown eager forms. Fixed-8 and `6,8,12` now have
an exact `0.000 ms` PCM duration delta for every pair and matching codec trace
fields. `scheduler-quality-matrix-v4.json` is a fail-closed quality gate: it
requires exact duration, zero clipped S16 samples, and absolute jump, p95,
RMS, DC and high-band spectral limits. The accompanying WAV pairs are kept as
local review output rather than repository artifacts.

```text
scheduler-quality-matrix-v1.jsonl
scheduler-quality-matrix-v4.json
```

```text
scheduler-quality-matrix-v4.json 182802590866b515223a1d64b51b036af717c7958d35ce17717d63a44981f957
```

## Sources

- `external/python/Qwen3-TTS-streaming/examples/test_streaming_optimized.py`
- `external/python/Qwen3-TTS-streaming/examples/test_model_12hz_base.py`
- https://github.com/andimarafioti/faster-qwen3-tts
- https://github.com/andimarafioti/faster-qwen3-tts/blob/main/BLOG.md
- https://docs.nvidia.com/dl-cuda-graph/latest/torch-cuda-graph/torch-integration.html
- https://docs.nvidia.com/dl-cuda-graph/torch-cuda-graph/best-practices.html
- https://huggingface.co/docs/transformers/perf_torch_compile
