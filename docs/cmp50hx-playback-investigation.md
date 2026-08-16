# CMP 50H Playback Investigation

## Scope and terminology

This document records the CMP 50H investigation as of 2026-08-16. It separates
three concerns that must not be conflated:

- numerical correctness of the Faster Qwen execution path;
- audio-delivery timing observed by the native playback example; and
- GPU and scheduler attribution from opt-in ETW captures.

The playback metric is deliberately named **WaveOut queue starvation proxy**. It
reports that, when a later PCM chunk arrived, no previously submitted WaveOut
buffer remained queued. It is useful for detecting insufficient delivery slack,
but it is not a hardware underrun counter and does not by itself establish an
audible glitch or a GPU root cause.

All capture artefacts are local and intentionally untracked under `tmp/`. The
run identifiers below make the results auditable without embedding machine-local
paths in versioned documentation.

## Numerical correctness fixed earlier

The original long same-worker FP16 failure was traced to the residual path:
an FP16 residual add overflowed (an observed case was `65440 + 116.75`). The
accepted corrective boundary is graph-compatible and is now the frozen Faster
candidate C configuration:

```text
residual add and RMSNorm       float32
normalized attention/MLP input float16
layer-2 gate/up projections    float16
layer-2 product/down path      float32
```

The FP32 residual carrier was proven on the normal Faster graph path, rather
than only in an eager numerical-tracing path. Long runs reached natural EOS with
finite observations. This was a numerical-correctness fix; it did not claim to
solve the later playback timing question.

## Evidence-quality work

Early Nsight Systems attempts were unsuitable for the final question on this
WDDM machine: WDDM tracing required elevation, some option combinations were
mutually exclusive, and several runs either did not yield a usable report or
captured only normal behaviour. The investigation therefore moved to Windows
Performance Recorder (WPR) and Windows Performance Analyzer tooling.

The diagnostic launcher is opt-in and externally wraps the unchanged playback
executable. A captured trace is usable only when all of the following hold:

```text
workload succeeded
WPR start and stop succeeded
ETL exists and is non-empty
EventsLost is verified as zero
DxgKrnl and CSwitch evidence is present
the requested playback markers are present
```

Any event loss makes the ETL inconclusive. One earlier WPR capture dropped
13,445,097 events and was explicitly rejected rather than used as evidence.

The marker capture and marker-aware analyzer are separate diagnostic changes:

- ETW markers use WPR's `-marker` facility for request start and every observed
  later-chunk queue-empty event.
- The analyzer uses the ETW clock, not the process-relative playback clock.
- Player-to-worker attribution requires a unique player, a unique direct Python
  worker, worker CSwitch data, and worker-attributed DxgKrnl events.

The analyzer reports evidence presence and attribution only. It does not infer
a GPU root cause from that presence. Full DxgKrnl decoding with the installed
legacy `xperf` is expensive for the bounded roughly 754 MB ETL, so no partially
decoded trace is presented as a root-cause conclusion.

The original combined marker range (about 28 seconds) did not finish within
five minutes. In contrast, extracting each 1.1-second marker window separately
completed in tens of seconds per window. This preserves the same ETW-relative
windows while bounding temporary output and enables a compact per-window report.

## Reproductions and observations

The marker-aligned ETW capture `20260816T004412Z-98540` is valid evidence:

| Property | Result |
| --- | --- |
| Capture mode | Minimal DxgKrnl plus scheduler evidence |
| Event loss | Zero, verified |
| Playback markers expected/observed | 8 / 12 PerfInfo marks |
| PCM chunks | 8 |
| Audio duration | 5096.875 ms |
| Later-chunk queue-empty observations | 7 |
| First worker / player audio | About 17.96 s / 18.46 s |

The seven recorded inter-arrival intervals were approximately 1317, 1965,
1259, 1840, 716, 695, and 704 ms. Each delivered chunk contained roughly
640 ms of audio. Worker logs show CUDA graph capture during that first user
request and high variance in codec-wrapper work, while AR decode was commonly
around 500 ms per eight-frame chunk.

An opt-in synthesis warmup was then evaluated. It creates the relevant graphs
before the user request and is passed explicitly to the worker; CustomVoice
warmup includes its language and speaker so it has the same model-family inputs
as the measured request.

| Experiment | PCM chunks / audio | Later queue-empty observations | Finding |
| --- | --- | --- | --- |
| Baseline, `emit_every_frames=8` | 8 / 5096.875 ms | 7 | First request paid graph-capture cost and steady gaps occurred. |
| Warmup, `emit_every_frames=8` | 8 / 5016.875 ms | 6 | First player audio fell to about 1.24 s, but steady starvation remained. |
| Warmup, `emit_every_frames=16` | 4 / 5016.875 ms | 3 | Larger chunks improved delivery slack but did not remove the proxy signal. |
| Warmup, `emit_every_frames=32` | 2 / 5016.875 ms | 1 | Larger chunks further reduced gaps, but sustained rate remained below real-time. |

The observed E=16 inter-arrival intervals were approximately 1864, 2721, and
1853 ms for audio chunks of about 1.28 s. Thus graph capture is a user-visible
startup problem, but cannot alone explain the repeated steady-stream gaps.

The E=32 run was intentionally performed under the same normal background
workload as the other current experiments. The first WaveOut submission was at 3514 ms; its two
chunks contained about 2537 and 2480 ms of audio and arrived 3012 ms apart.
The worker reported RTF 1.300847 for the 5016.875 ms response. Therefore E=32
reduces the bursty delivery symptom, but it still cannot sustain real-time
output on a long request and it increases first-playback latency substantially.

### GPU activity in the valid marker windows

The zero-loss ETL identifies the TTS worker as `python.exe (100964)`. The
separately running RAG materialization process was `python.exe (38616)`. Both
processes had DxgKrnl activity in every 1.1-second window around a playback
queue-empty marker:

| Queue-empty marker | TTS DxgKrnl events | RAG DxgKrnl events | TTS DMA / queue packets | RAG DMA / queue packets |
| --- | ---: | ---: | ---: | ---: |
| 1 | 12,204 | 13,764 | 2,358 / 7,548 | 6,236 / 4,237 |
| 2 | 13,160 | 13,074 | 2,810 / 7,649 | 5,978 / 4,218 |
| 3 | 12,722 | 10,799 | 2,461 / 7,929 | 4,956 / 3,172 |
| 4 | 13,941 | 7,183 | 3,221 / 7,867 | 3,227 / 2,219 |
| 5 | 25,995 | 13,551 | 5,382 / 15,603 | 6,548 / 4,133 |
| 6 | 23,946 | 19,436 | 4,344 / 15,255 | 9,413 / 5,874 |
| 7 | 12,914 | 17,748 | 2,379 / 8,140 | 7,965 / 5,796 |

These counts establish that the materializer was not CPU-only with respect to
GPU scheduling in this capture, and that it was not the only active workload:
TTS itself also had substantial GPU queue activity. Event counts are not GPU
execution duration, so this table rules out neither TTS-owned long work nor
WDDM scheduling/preemption. It does establish that the next causal A/B must
explicitly account for the materializer as a competing GPU context.

## Changes under evaluation

The playback soak launcher has explicit experimental switches, all defaulting
to the prior behaviour:

- `-WorkerSynthesisWarmup` creates relevant graphs before the measured request.
- `-EmitEveryFrames` changes delivery granularity for an experiment.
- `-SkipEtwFollowup` is for bounded non-ETW experiments only; its summaries are
  never valid ETW evidence.

Playback metrics record the first successful WaveOut submission relative to the request,
so first-chunk arrival and sink start can be reported separately. No default
runtime policy has been changed.

One `emit_every_frames=16`, warmup, 3000 ms prebuffer attempt was stopped
without result while unrelated local CPU/GPU work made a fresh worker load
unusually slow. It is recorded as aborted and must not be cited as evidence.

A later 3000 ms attempt reached a stronger negative result: warmup succeeded,
the worker generated four chunks (5016.875 ms of audio) in about 8.1 s, and
then the experimental player timed out waiting for WaveOut completion. This is
not a GPU-stall result and not evidence that prebuffer fixes playback. The
prebuffer implementation was therefore removed rather than retained as an
opt-in candidate. A mock regression test reproduced the non-zero-prebuffer
timeout, while the restored direct WaveOut submission path completed normally.

The same failed run provides a separate throughput observation: its worker
reported a 1.619 real-time factor (8123.835 ms synthesis for 5016.875 ms
audio). Consequently, even a correct finite prebuffer would only hide a short
burst; it cannot make arbitrarily long output real-time when the sustained
worker rate is below audio rate.

## Current conclusions

1. The frozen C numerical boundary fixes the known FP16 residual overflow and
   remains separate from the timing investigation.
2. Synthesis warmup substantially improves first-audio latency by moving graph
   capture out of the user request.
3. The tested stream still lacks enough delivery slack after warmup, although
   larger delivery chunks reduce the number of queue-starvation proxy events.
4. A valid ETW capture establishes that the condition reproduces with zero-loss
   DxgKrnl and scheduler evidence. It does not yet distinguish long own GPU
   work, scheduling gaps, competing contexts, preemption, paging, or transfer/
   synchronization effects.
5. Under representative CPU load, the warm E=16 worker was slower than audio
   in the failed prebuffer run (RTF 1.619). This establishes a sustained-rate
   problem in addition to bursty delivery gaps, but not yet whether its cause
   is own GPU work, CPU dispatch, or WDDM scheduling.
6. Increasing delivery size to E=32 improved proxy observations from three to
   one, but RTF remained 1.300847. Delivery granularity alone therefore cannot
   meet the real-time requirement on this workload.
7. The valid marker windows show simultaneous TTS and RAG GPU activity. Any
   claim that the RAG materializer is CPU-only is inconsistent with this trace;
   any claim that it alone caused the stalls is also unsupported because TTS
   activity is substantial in the same windows.
8. The appropriate next optimisation decision depends on timing-aware
   marker-window analysis, not on another unsupported global precision change.

### Bounded throughput probe pending

The historical near-real-time C results were produced with the same frozen
numerical boundary under more favourable scheduling conditions: fixed-seed C
medium runs observed RTF 0.981--0.987, while a graph-compatible long smoke
observed RTF 1.001. They establish that the model path can approach audio rate,
but do not make the current representative-load RTF 1.300847 a regression that
can be assumed away.

One explicitly opt-in experiment is now available through
`-MatmulPrecision high`. It asks PyTorch to use its `high` float32-matmul
policy, which can select TF32 tensor-core kernels for the frozen C FP32
`down_proj` GEMM on supported hardware. It does **not** change the configured
FP32 carrier, RMSNorm, product/down data types, or default playback path.
Because it can alter floating-point GEMM results and hence the sampled token
trajectory, it is a diagnostic A/B only: each side needs the same warmup,
fresh-worker EOS/finite smoke, and a representative-load RTF/playback run.
No result is a runtime-policy change until that comparison completes.

## Next acceptance gates

1. Finish the marker-aware analyzer review and use it only on zero-loss,
   marker-complete ETLs.
2. On a comparatively idle machine, repeat fresh-worker runs for warmup plus
   `emit_every_frames=16`. Record TTFA, sink start, completion, per-chunk
   cadence, worker RTF, and proxy observations separately.
3. If a valid marker-aligned window shows long worker-owned GPU work, profile
   that work; if it shows GPU gaps or competing context activity, investigate
   WDDM scheduling and other consumers instead. Only then choose a targeted
   runtime change.

## Reproduction examples

Normal playback evidence (ETW follow-up is started only after an observed
proxy outlier):

```powershell
.\scripts\run-cmp50hx-playback-etw-soak.ps1 -Attempts 1
```

Bounded TF32-policy probe, with no ETW follow-up (use only after the normal
correctness smoke has completed):

```powershell
.\scripts\run-cmp50hx-playback-etw-soak.ps1 -Attempts 1 -WorkerSynthesisWarmup -EmitEveryFrames 16 -MatmulPrecision high -SkipEtwFollowup
```

Warmup and larger delivery-chunk experiment without an ETW follow-up:

```powershell
.\scripts\run-cmp50hx-playback-etw-soak.ps1 `
  -Attempts 1 `
  -WorkerSynthesisWarmup `
  -EmitEveryFrames 16 `
  -SkipEtwFollowup
```
