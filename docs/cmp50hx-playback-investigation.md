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

The observed E=16 inter-arrival intervals were approximately 1864, 2721, and
1853 ms for audio chunks of about 1.28 s. Thus graph capture is a user-visible
startup problem, but cannot alone explain the repeated steady-stream gaps.

## Changes under evaluation

The playback soak launcher has explicit experimental switches, all defaulting
to the prior behaviour:

- `-WorkerSynthesisWarmup` creates relevant graphs before the measured request.
- `-EmitEveryFrames` changes delivery granularity for an experiment.
- `-PlaybackPrebufferMs` queues an initial amount of PCM before calling
  WaveOut. A value of zero retains immediate playback.
- `-SkipEtwFollowup` is for bounded non-ETW experiments only; its summaries are
  never valid ETW evidence.

The player prebuffer is intentionally opt-in. Before playback begins, pending
buffers count toward the queue balance but do not produce a later-chunk
queue-empty observation. End of stream flushes a partial prebuffer so short
responses still play. Its metrics record the requested prebuffer duration.

This is a possible playback-resilience mechanism, not a throughput fix: it
trades initial playback delay for delivery slack. No default runtime policy has
been changed.

One `emit_every_frames=16`, warmup, 3000 ms prebuffer attempt was stopped
without result while unrelated local CPU/GPU work made a fresh worker load
unusually slow. It is recorded as aborted and must not be cited as evidence.

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
5. The appropriate next optimisation decision depends on marker-window analysis
   of valid captures, not on another unsupported global precision change.

## Next acceptance gates

1. Finish the marker-aware analyzer review and use it only on zero-loss,
   marker-complete ETLs.
2. On a comparatively idle machine, repeat fresh-worker runs for warmup plus
   `emit_every_frames=16` and a bounded prebuffer sweep (for example 2000,
   2500, and 3000 ms). Record TTFA, prebuffer delay, completion, chunk cadence,
   and proxy observations separately.
3. Do not promote a prebuffer to the default merely because one short run has
   no proxy observation. It must have an explicit latency trade-off and repeat
   successfully across bounded runs.
4. If a valid marker-aligned window shows long worker-owned GPU work, profile
   that work; if it shows GPU gaps or competing context activity, investigate
   WDDM scheduling and other consumers instead. Only then choose a targeted
   runtime change.

## Reproduction examples

Normal playback evidence (ETW follow-up is started only after an observed
proxy outlier):

```powershell
.\scripts\run-cmp50hx-playback-etw-soak.ps1 -Attempts 1
```

Warmup and larger delivery-chunk experiment without an ETW follow-up:

```powershell
.\scripts\run-cmp50hx-playback-etw-soak.ps1 `
  -Attempts 1 `
  -WorkerSynthesisWarmup `
  -EmitEveryFrames 16 `
  -SkipEtwFollowup
```

Candidate prebuffer experiment (not an accepted default):

```powershell
.\scripts\run-cmp50hx-playback-etw-soak.ps1 `
  -Attempts 1 `
  -WorkerSynthesisWarmup `
  -EmitEveryFrames 16 `
  -PlaybackPrebufferMs 3000 `
  -SkipEtwFollowup
```
