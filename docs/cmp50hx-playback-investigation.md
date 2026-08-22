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
2. A two-chunk synthesis warmup substantially improves first-audio latency by
   moving initial graph work out of the user request, but does not warm all
   codec-decoder paths.
3. On the idle CMP 50HX, the short physical-playback request still reproduced
   three queue-starvation proxy observations with that bounded warmup. This
   also proves that the RAG materializer is not a necessary condition for the
   symptom.
4. A valid ETW capture establishes that the bounded-warmup condition reproduces with zero-loss
   DxgKrnl and scheduler evidence. It does not yet distinguish long own GPU
   work, scheduling gaps, competing contexts, preemption, paging, or transfer/
   synchronization effects.
5. Under representative CPU load, the bounded-warm E=16 worker was slower than audio
   in the failed prebuffer run (RTF 1.619). This establishes a sustained-rate
   problem in addition to bursty delivery gaps, but not yet whether its cause
   is own GPU work, CPU dispatch, or WDDM scheduling.
6. Increasing delivery size to E=32 improved proxy observations from three to
   one, but RTF remained 1.300847. Delivery granularity alone therefore cannot
   meet the real-time requirement on this workload.
7. The earlier valid marker windows show simultaneous TTS and RAG GPU activity. Any
   claim that the RAG materializer is CPU-only is inconsistent with this trace;
   the idle reproduction now also rules out a claim that RAG alone caused the
   stalls.
8. A targeted phase profile identifies the dominant cold path as GPU
   `speech_tokenizer.decode`, not predictor decoding, D2H, or PCM conversion.
   Full-EOS startup warmup reduced the proxy symptom in an initial controlled
   playback case without changing numerical kernels, but extended and
   prompt-matched runs still observed the terminal gap; it reduces cold-start
   risk rather than eliminating that path.

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

The first chronological default/high pair was recorded with synthesis warmup,
`emit_every_frames=16`, and the same active representative background workload.
It is a useful directional result, not a repeated or randomized estimate:

| Policy | Worker synthesis | Worker RTF | First worker PCM | Playback start | Queue-empty proxy |
| --- | ---: | ---: | ---: | ---: | ---: |
| Torch default | 7500.108 ms | 1.494976 | 1511.206 ms | 1684.371 ms | 3 |
| `high` | 7152.027 ms | 1.425594 | 1362.078 ms | 1591.154 ms | 3 |

`high` reduced synthesis wall time by 4.64% in this pair, consistent with the
FP32-GEMM hypothesis. It did not reach RTF <= 1 or remove any starvation-proxy
observation. The result therefore justifies a finite/EOS smoke and a repeated
active-versus-idle comparison; it does not yet justify enabling TF32 in the
normal runtime policy.

The corresponding graph-compatible finite smoke completed its warmup and
measured request with no terminal failure. The aggregate checker reported
`all_finite=true` and valid boundaries for both terminal generations, with no
host synchronization during predictor replay. Its RTF is intentionally not a
performance result because the checker is enabled. This closes the basic
numerical safety gate for `high`; it does not replace a repeated playback A/B.

The historical CPU-priority probe raises `qwen_tts_play` only after it has
started. The Python worker may therefore have been created before that change,
so inherited worker priority was never verified. It neither changes nor
suspends the materializer/RAG process.

The historical pair (`Normal` RTF 1.386605 and `AboveNormal` RTF 1.386561,
with three queue-empty proxy observations on each side) is consequently
inconclusive for worker-priority attribution. Do not promote CPU priority as a
realtime fix or use this result to narrow the remaining investigation. The
launcher records this limitation explicitly; a future priority experiment must
set and verify the worker's priority before it can support a causal claim.

### Codec decoder warmup finding

The idle playback A/B used the frozen C path, fixed seed, `emit_every_frames=16`,
and Torch's default float32-matmul policy. The only changed factor was startup
warmup coverage.

| Startup warmup | Worker RTF | Queue-starvation proxy | Result |
| --- | ---: | ---: | --- |
| Bounded after 2 chunks | 1.164323 | 3 | Reproduced on an idle CMP 50HX. |
| Bounded after 4 chunks | 1.006005--1.026629 | 0--1 | Strong improvement, but terminal flush remained intermittently cold. |
| One generic unbounded pass to natural EOS | 1.007151--1.017273 (mean 1.013495) in the initial sample | 0 / 3 initial attempts; then 1 / 2 in the extended run | Reduces cold-start risk, but is not an acceptance result. |
| Prompt-matched unbounded pass to natural EOS | 1.032--1.033 before the terminal chunk | 1 / 1 attempt | Did not cover the dynamic terminal decoder path. |

The historical medium benchmark was also replayed with its exact frozen-C
configuration and again achieved RTF 0.974. Therefore the numerical/runtime
stack had not generally regressed; the short playback symptom was a cold-path
coverage problem.

An opt-in `-ProfilePrefill` diagnostic run decomposed the short-request chunk
time. Predictor work remained about 57 ms per codec step. The excess time was
almost entirely GPU `speech_tokenizer.decode` work: 118, 483, 838, and 524 ms
across the four chunks. D2H, NumPy conversion, PCM conversion, and wrapper
CPU work were negligible. A bounded warmup never reaches the distinct terminal
flush-decode path; one unbounded warmup pass reaches natural EOS before the
worker reports ready, but it does not establish a reusable graph or decoder
shape for every later terminal chunk.

The extended validation falsified the initial full-EOS warmup acceptance
hypothesis. In run `20260821T105806Z-98540`, the second request reported one
queue-empty proxy observation before its fourth, terminal PCM chunk. Its
`codec_wrapper_residual_ms` rose from 158--196 ms on the preceding chunks to
874 ms. Prompt-matched warmup in `20260821T110549Z-98540` failed the same way:
the first request's terminal residual was 879 ms after three 131--192 ms
non-terminal residuals. The seed and text do not guarantee the same terminal
codec shape because warmup is itself a generative pass.

Full-EOS warmup remains an explicit, startup-only experiment:

```text
--warmup-synthesis
--warmup-unbounded-passes 1
--warmup-text <finite generic sentence>
```

`--warmup-max-output-chunks` may remain set as a bound for any later passes;
the first unbounded pass deliberately ignores it. It is neither a hardware
underrun fix nor a sufficient real-time policy. The frozen C numerical boundary
remains unchanged. The next controlled mitigation is opt-in sink prebuffering:
measure whether a deliberate initial audio reserve prevents the known terminal
burst without silently claiming that inference itself became faster.

### Sink prebuffer probe

The player now has an opt-in `--playback-prebuffer-chunks <n>` control. The
default is one, which preserves immediate WaveOut submission. A value of two
holds the first PCM chunk locally and starts the physical sink only after the
second chunk arrives. That reserve is intentionally a playback-latency trade-
off, not an inference optimisation: worker RTF and producer chunk arrival times
must be reported unchanged alongside sink-start latency and proxy observations.

The mock CTest covers both sides: with 150 ms chunks arriving 200 ms apart,
immediate submission reports the expected queue-empty proxy; a two-chunk
prebuffer starts after the second arrival and reports no later queue-empty
observation. The initial implementation was corrected so this reserve applies
only before sink start; every later chunk is submitted immediately.

The corrected idle CMP 50HX acceptance run used the frozen C path,
`emit_every_frames=16`, default Torch matmul precision, one full-EOS startup
warmup pass, and `playback_prebuffer_chunks=2`:

| Run | Attempts | Sink start | Queue-starvation proxy |
| --- | ---: | ---: | ---: |
| `20260821T134339Z-98540` | 1 | 2719 ms | 0 |
| `20260821T135959Z-98540` | 3 | 2718--2737 ms | 0 / 3 |

This is a controlled playback mitigation for the observed terminal decode
burst. It deliberately delays physical audio start by about one additional
PCM chunk; it does not improve producer RTF or constitute a hardware-underrun
counter. Longer idle and representative-load validation remain separate
acceptance work.

### Rejected left-padded fixed-shape codec-decode experiment

The next performance investigation is deliberately separate from the playback
reserve. The Faster custom-voice stream currently decodes dynamically sized
codec windows. The vendored streaming implementation provides
`speech_tokenizer.decode_streaming()` with left-padding to a fixed number of
frames and removal of the corresponding leading PCM samples afterwards. This
preserves the emitted tail rather than returning PCM produced for right-side
padding.

The opt-in candidate applies that API only to ordinary streaming windows.
Terminal EOS flush remains on the established `decode()` path for now, because
its audio-tail contract and the observed terminal latency burst need a separate
experiment. The candidate is default-off, checks that the selected shadow
contains its patch marker, and fails closed when the tokenizer lacks
`decode_streaming` or a window exceeds the configured fixed 80-frame size.

The subsequent raw-PCM gate in PR #54 showed that this left-padded path does
not preserve PCM parity despite matching codec tokens. It is therefore rejected
as a correctness candidate: it must remain default-off and must not be used as
a performance control or runtime policy. The commands below are retained only
as historical reproduction instructions for that rejected experiment.

Create an isolated candidate shadow from the exact frozen source:

```powershell
.\scripts\prepare-cmp50hx-faster-codec-streaming-shadow.ps1
```

Then run only the streaming-API correctness smoke:

```powershell
.\scripts\run-cmp50hx-playback-etw-soak.ps1 `
  -Attempts 1 `
  -FasterShadowPath tmp\cmp50hx-faster-codec-streaming-shadow `
  -CodecStreamingDecode `
  -PlaybackPrebufferChunks 2 `
  -WorkerSynthesisWarmup `
  -WorkerWarmupUnboundedPasses 1 `
  -EmitEveryFrames 16 `
  -ProfilePrefill `
  -SkipEtwFollowup
```

This first mode keeps decoder compilation/capture disabled and is not a
performance claim. It exists to establish PCM/EOS completion and finite long
generation before a separately controlled decoder-optimization A/B.

### PCM parity gate for the fixed-shape candidate

Completion alone is insufficient to accept a decoder-path change: the frozen
and fixed-window modes must produce comparable PCM for the same deterministic
request. The native player therefore exposes an explicitly diagnostic-only
capture option:

```text
--pcm-capture-file <path>
```

It accepts one-shot `--text` playback only, refuses to overwrite either the raw
target or its `<path>.json` metadata sidecar, and is off by default. It captures
the active request's PCM before WaveOut submission, requires one stable audio
format, and writes raw `s16le` bytes plus chunk count, byte count, format, and
successful-completion metadata. Capture writes are diagnostic instrumentation;
never use a capture run as a performance measurement.

For a frozen-versus-candidate comparison, use the same seed, speaker, text,
`emit_every_frames`, prebuffer, and warmup on both sides. Require natural EOS
and then compare the metadata and raw SHA-256:

```powershell
Get-FileHash .\tmp\frozen.pcm -Algorithm SHA256
Get-FileHash .\tmp\streaming.pcm -Algorithm SHA256
```

The repository also provides a dependency-free analyzer for fixed, explicit
tolerance gates:

```powershell
python .\scripts\compare-cmp50hx-pcm-parity.py `
  --expected .\tmp\frozen.pcm `
  --candidate .\tmp\candidate.pcm `
  --output .\tmp\pcm-parity.json `
  --max-rms-delta 3 --min-snr-db 55 --max-abs-delta 64
```

An exact hash match is the strongest result. If the deterministic sampling path
does not produce exact bytes, record the distinct hashes together with equal
format, length, EOS, and an explicit audio-quality comparison; do not describe
that as byte-identical parity.

If byte length differs, repeat the pair with the launcher's diagnostic
`-CollectGenerationTrace` switch. Compare the emitted codec-frame count and
codec SHA-256 first: a mismatch there is a sampling/reproducibility result, not
evidence that the PCM decoder changed the predictor. Do not include generation
trace or PCM capture in a timing result.

The first left-padded upstream API probe did **not** pass this gate: it reached
the same 63 codec frames with an identical codec digest, but changed all PCM
chunks and increased the first chunk by 444 samples. This is decoder-output
semantics, not sampling drift. It remains a rejected diagnostic candidate.

A separate, default-off right-padding experiment is available for the next
causal test. The 12 Hz decoder is causal, so it fixes the input shape by adding
future zero frames and preserves the valid prefix before selecting the normal
decoder output length. It is intentionally a separate shadow and must pass the
same PCM gate before any timing measurement:

```powershell
.\scripts\prepare-cmp50hx-faster-codec-right-padded-shadow.ps1
```

The first controlled short pair recorded identical codec traces (63 frames and
the same codec SHA-256), equal PCM format/length (240,810 bytes), and natural
EOS. It was not byte-identical: `rms_pcm_delta=2.845`, `snr_db=55.458`, and
`max_abs_pcm_delta=52` after s16le conversion. The explicit tolerance gate
`RMS <= 3`, `SNR >= 55 dB`, `max <= 64` passed. This is sufficient only for a
candidate-quality gate, not a claim of exact equivalence or a runtime change.

A separate longer right-padding smoke reached natural EOS at 316 predictor
steps / codec frames and wrote 20 PCM chunks (25,256.875 ms, 1,212,330 bytes)
without a playback proxy observation. It validates the candidate's bounded
longer correctness path; its PCM capture and generation trace remain diagnostic
artefacts, not performance evidence.

The first fresh-worker timing A/B deliberately omitted PCM capture and
generation tracing. Both sides used the same seed, request, full-EOS warmup,
`emit_every_frames=16`, and two-chunk sink prebuffer. The frozen decoder
measured RTF `1.156173` and `1.152039`; the right-padded candidate measured
`0.966334` and `0.962041`. This is an approximately 16.5% synthesis reduction
and brings this short workload below real-time in both candidate runs. All four
runs completed playback with zero proxy observations. Candidate first-audio
latency was about 132 ms later, so this is a throughput result with a visible
TTFA trade-off, not an unconditional runtime recommendation. It needs the
separate longer playback soak before any policy decision.

That acceptance soak is now complete for run `20260821T203649Z-98540`: ten
fresh-worker attempts used the same full-EOS warmup, `emit_every_frames=16`,
two-chunk sink prebuffer, normal Faster graphs, and the right-padded decoder
shadow. Every attempt exited successfully, produced four PCM chunks / 5,016.875
ms of audio, and recorded zero later-chunk queue-empty observations. No WPR
session was launched because no outlier was detected. This validates the
candidate for this bounded idle playback workload; it still does not establish
hardware-underrun absence, production policy, or behaviour under a competing
GPU workload.

### Rejected compiled codec decoder

The right-padded decoder also received a separate, opt-in
`torch.compile(mode="reduce-overhead", backend="inductor")` experiment. The
sealed worker's Triton installation was verified first, and compile smoke run
`20260822T025117Z-98540` confirmed that the decoder compilation completed. The
request reached natural EOS with four PCM chunks / 5,016.875 ms of audio and no
queue-starvation proxy observation. This smoke is not a performance or audio
acceptance result.

The candidate then failed the PCM quality gate. Baseline run
`20260822T040926Z-98540` and compiled run `20260822T064319Z-98540` both
completed with the same s16le format, four chunks, and 240,810 bytes, but their
SHA-256 values differed. The strict comparison measured RMS delta `14.105`, SNR
`41.551 dB`, and maximum absolute delta `330`; the accepted right-padding gate
is RMS `<= 3`, SNR `>= 55 dB`, and maximum delta `<= 64`.

This is not sampling drift: generation-trace baseline run
`20260822T071848Z-98540` and compiled run `20260822T102844Z-98540` each
produced 63 codec frames with the identical codec SHA-256
`bab57d3e9d4dd49b7fdac6ffd106a8af56b382f1c9648041e473eaa1e5e3d3b8`.
The observed PCM difference therefore comes from the compiled decoder's
numerical implementation. The compile candidate is rejected without a
performance A/B or longer playback soak, and it remains default-off.

### GPU lifecycle evidence gap

The zero-loss marker-aligned ETL from run `20260816T004412Z-98540` was replayed
against the raw DxgKrnl dumper output. The minimal scheduler profile contained
worker `QueuePacket` starts and `DmaPacket` informational records, but zero
worker `DmaPacket Start/Stop` pairs across all eight marker windows. The
informational records are emitted a few microseconds after queue submission and
are therefore not a measurement of GPU execution time.

This closes a methodological gap: the existing event counts establish activity
and attribution only. They must not be converted into kernel duration,
preemption time, or GPU utilisation. The marker analyzer now reports the
observed lifecycle-pair count and, with `-RequireDmaPacketLifecycle`, rejects an
ETL with no worker start/stop pairs as execution-lifecycle evidence.

The opt-in WPR profile `CMP50HX-DxgKrnl-Execution` expands the minimal
`Base + GPUScheduler` mask with `HardwareSchedulingLog`. It is not selected by
default, does not change the TTS worker or player, and retains the existing
elevation, bounded file-mode, semantic-trace, and zero-event-loss gates. Its
first purpose is narrow: establish whether this Windows/WDDM configuration can
emit pairable worker GPU scheduler lifecycles at all. If it cannot, the result
is inconclusive rather than evidence for a GPU execution-duration claim.

The analyzer extracts DxgKrnl independently for each marker window. On the
754 MB reference ETL this replay took about six minutes with the installed
legacy xperf, but it avoids one much larger combined dump and leaves the source
ETL unchanged.

The first execution-profile capture, run `20260818T014947Z-98540`, reproduced
the playback proxy outlier and passed the normal transport, zero-event-loss,
marker, and semantic gates. It produced a 352 MB ETL with 923,154 scheduler
events. The expanded provider recorded global `DmaPacket Start/Stop` and
`SchedulingLog` events, so the profile is active; the strict marker analyzer
correctly rejected it as worker execution-lifecycle evidence because there
were zero worker `DmaPacket Start/Stop` pairs in its marker windows.

Inspection of a representative window shows why that result must remain
inconclusive: Python's queue events use its own `hContext`, while the hardware
`DmaPacket Start/Stop` records are attributed to `System`/`Idle` and use a
different context. The available `SchedulingLog` payload is opaque in xperf's
text dumper and supplies no documented correlation to the worker context. Do
not infer GPU execution duration, TTS preemption, or competing-context blame
from these records. Further automatic keyword expansion is not justified until
an interactive GPUView/WPA review finds a documented join, or a controlled
consumer-isolation A/B gives a causal result.

## Next acceptance gates

1. Keep marker-aware ETW analysis limited to zero-loss, marker-complete ETLs;
   it remains an attribution tool, not a GPU-duration measurement on this WDDM
   stack.
2. Run a controlled opt-in sink-prebuffer A/B on the idle machine. Record TTFA,
   sink start, completion, per-chunk cadence, worker RTF, and proxy observations
   separately; do not describe delayed sink start as improved synthesis speed.
3. If a bounded playback reserve still reproduces a proxy outlier, capture a
   new marker-aligned ETL and investigate competing contexts or WDDM scheduling.

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

Bounded CPU-priority attribution probe:

```powershell
.\scripts\run-cmp50hx-playback-etw-soak.ps1 -Attempts 1 -WorkerSynthesisWarmup -EmitEveryFrames 16 -MatmulPrecision high -TtsCpuPriority AboveNormal -SkipEtwFollowup
```

The historical command is retained only to reproduce the inconclusive probe;
it does not establish worker priority. A future attribution A/B must use a
launcher that sets and verifies worker priority before the worker begins work.

Execution-lifecycle ETW follow-up, only after an ordinary run reproduces a
proxy outlier and only from an elevated PowerShell:

```powershell
.\scripts\run-cmp50hx-playback-etw-soak.ps1 `
  -Attempts 1 `
  -WprProfileName CMP50HX-DxgKrnl-Execution
```

Then require the lifecycle evidence explicitly. Replace the summary path with
the new run's generated `summary.json`.

```powershell
.\scripts\analyze-cmp50hx-etw-markers.ps1 `
  -SummaryPath .\tmp\cmp50hx-playback-etw-soak\<run-id>\summary.json `
  -RequireDmaPacketLifecycle
```

Warmup and larger delivery-chunk experiment without an ETW follow-up:

```powershell
.\scripts\run-cmp50hx-playback-etw-soak.ps1 `
  -Attempts 1 `
  -WorkerSynthesisWarmup `
  -EmitEveryFrames 16 `
  -SkipEtwFollowup
```

Full-EOS codec-decoder warmup acceptance run without ETW follow-up:

```powershell
.\scripts\run-cmp50hx-playback-etw-soak.ps1 `
  -Attempts 3 `
  -WorkerSynthesisWarmup `
  -WorkerWarmupUnboundedPasses 1 `
  -WorkerWarmupText 'This warmup synthesis prepares several streaming codec decode windows before the first user request begins.' `
  -EmitEveryFrames 16 `
  -SkipEtwFollowup
```

For phase diagnosis only, add `-ProfilePrefill`. It adds timing events and
must not be used as a normal-performance measurement.

Two-chunk sink-prebuffer A/B, without ETW follow-up:

```powershell
.\scripts\run-cmp50hx-playback-etw-soak.ps1 `
  -Attempts 3 `
  -PlaybackPrebufferChunks 2 `
  -WorkerSynthesisWarmup `
  -EmitEveryFrames 16 `
  -SkipEtwFollowup
```

Compare this with the same command using `-PlaybackPrebufferChunks 1`. Report
the physical sink start separately from first PCM arrival and do not treat the
added prebuffer delay as a TTFA improvement.
