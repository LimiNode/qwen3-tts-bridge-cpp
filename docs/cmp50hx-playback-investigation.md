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

The subsequent raw-PCM gate in PR #54 showed that this left-padded path does
not preserve PCM parity despite matching codec tokens. It is therefore rejected
as a correctness candidate and is no longer shipped as a runnable patch. It
must not be used as a performance control or runtime policy; the measurements
below are retained only as historical evidence.

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

A separate, default-off right-padding experiment supplies the accepted causal
test. The 12 Hz decoder is causal, so it fixes the input shape by adding future
zero frames and preserves the valid prefix before selecting the normal decoder
output length. Its implementation is now versioned in the pinned
`external/python/faster-qwen3-tts` submodule at `fb09801`; the bridge no longer
constructs it from local patch/shadow directories.

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
candidate. Every attempt exited successfully, produced four PCM chunks / 5,016.875
ms of audio, and recorded zero later-chunk queue-empty observations. No WPR
session was launched because no outlier was detected. This validates the
candidate for this bounded idle playback workload; it still does not establish
hardware-underrun absence, production policy, or behaviour under a competing
GPU workload.

The separate manual codec CUDA-graph smoke (run `20260822T000100Z-98540`) also
completed successfully. Its provenance confirms the right-padded fixed
80-frame path and the opt-in codec graph flag; worker stderr confirms the
decoder graph was warmed and captured before the normal Faster predictor and
talker graphs. The request exited cleanly with four PCM chunks / 5,016.875 ms
of audio and zero later-chunk queue-empty observations. This is a graph-path
correctness smoke only. It still needs a PCM-quality pair against the accepted
right-padded candidate before timing or playback conclusions.

That PCM pair is now complete. The accepted right-padded baseline and manual
codec-graph candidate both produced 240,810 bytes / 120,405 s16le samples with
the identical SHA-256 `747bfd9afd3a004cf545c92beb25e06dd55cbda1dd6b6a13f347a52689a19c1a`.
All samples matched exactly (`RMS=0`, `max delta=0`). The parity analyzer now
represents this mathematically infinite SNR as `snr_db=null` plus an explicit
`snr_db_is_infinite=true`, so the strict JSON report remains valid while the
threshold gate still accepts exact equality.

Two fresh-worker performance pairs then compared that accepted right-padded
baseline with the manual codec graph, without PCM capture or ETW. Both sides
used the same seed, full-EOS warmup, `emit_every_frames=16`, and two-chunk sink
prebuffer. Pair one reduced synthesis `4890.594 -> 4690.625 ms` (4.09%), RTF
`0.974829 -> 0.934969`, and first audio `1390.423 -> 1344.855 ms`. Pair two
reduced synthesis `4933.925 -> 4685.452 ms` (5.04%), RTF `0.983466 ->
0.933938`, and first audio `1387.862 -> 1334.196 ms`. All four requests
completed playback with zero proxy observations. This is repeatable
throughput and TTFA improvement for the bounded workload, pending the separate
ten-attempt playback soak before a runtime-policy decision.

That final graph soak is now complete for run `20260822T005501Z-98540`. Ten
fresh-worker attempts used the right-padded 80-frame decoder, its opt-in manual
CUDA graph, full-EOS warmup, `emit_every_frames=16`, and a two-chunk sink
prebuffer. All ten exited successfully, each emitted four PCM chunks / 5,016.875
ms of audio, and none recorded a later-chunk queue-empty proxy observation. No
WPR session was launched because no outlier was observed. This completes the
bounded idle playback gate for the manual graph candidate; it remains a
default-off experimental path until a separate runtime-policy decision and does
not prove absence of physical hardware underruns or behavior under competing GPU
workloads.

### Smaller codec graph window

For `emit_every_frames=16`, this streaming loop supplies at most 25 left-context
frames plus 16 new frames to one codec decode. A new opt-in launcher control
therefore permits a smaller fixed graph window while rejecting any selected
window below `25 + emit_every_frames`; the established 80-frame default remains
unchanged. The first aligned candidate was 48 frames.

The W48 PCM/EOS gate passed against the accepted W80 manual-graph baseline.
W80 run `20260823T130145Z-98540` and W48 run
`20260823T130501Z-98540` both reached natural EOS with four s16le PCM chunks /
240,810 bytes. They were not byte-identical, but the comparison passed the same
explicit candidate-quality gate: RMS delta `2.763 <= 3`, SNR `55.710 dB >= 55`,
and maximum absolute delta `56 <= 64`.

Two fresh-worker performance pairs omitted PCM capture and tracing. Both used
the fixed seed, full-EOS warmup, `emit_every_frames=16`, two-chunk sink
prebuffer, and manual CUDA Graphs:

| Pair | W80 synthesis / RTF / first audio | W48 synthesis / RTF / first audio | Synthesis reduction |
| --- | --- | --- | ---: |
| 1 | 4885.240 ms / 0.973762 / 1298.716 ms | 4282.994 ms / 0.853718 / 1211.771 ms | 12.33% |
| 2 | 4783.881 ms / 0.953558 / 1369.944 ms | 4268.415 ms / 0.850812 / 1200.721 ms | 10.78% |

The W48 ten-attempt bounded idle soak, run `20260824T174430Z-98540`, then
completed 10/10 fresh-worker attempts with zero later-chunk queue-empty proxy
observations. Its synthesis time ranged from 4294.863 to 4363.953 ms (mean
4319.139 ms); RTF ranged from 0.856083 to 0.869855 (mean 0.860922); and first
audio ranged from 1211.652 to 1270.779 ms (mean 1232.245 ms). No WPR session
was launched because no outlier occurred. W48 consequently supersedes W80 as
the best bounded idle experimental codec-graph candidate, but remains opt-in
and does not establish a hardware-underrun guarantee or behavior under a
competing GPU workload.

### Rejected W41 codec graph window

With `emit_every_frames=16`, the theoretical smallest fixed codec input is 41
frames: 25 frames of decoder history plus 16 newly emitted frames. W41 was
therefore evaluated as a separate opt-in candidate against W48, rather than
changing the accepted path.

The PCM pair completed in W48 run `20260826T113853Z-98540` and W41 run
`20260826T114150Z-98540`. Both reached natural EOS with four chunks,
240,810 bytes, and 120,405 s16le samples; neither recorded a later-chunk
queue-empty proxy observation. The audio was not byte-identical: 42.8595% of
samples were exactly equal, RMS delta was `2.5570`, SNR was `56.3839 dB`, and
the maximum absolute delta was `38`. It fits the explicit non-bit-exact
candidate-quality envelope used for W48, but is not a transparent,
bit-identical technical substitution.

Fresh-worker ABBA timing used the same fixed seed, full-EOS warmup, two-chunk
prebuffer, manual codec CUDA Graph, and `emit_every_frames=16`:

| Case | TTFA | Synthesis | RTF | AR ms/step | Codec residual |
| --- | ---: | ---: | ---: | ---: | ---: |
| W48-A | 1228.237 ms | 4339.932 ms | 0.865067 | 57.252 ms | 140.262 ms |
| W41-A | 1224.114 ms | 4318.488 ms | 0.860792 | 56.758 ms | 142.780 ms |
| W48-B | 1230.650 ms | 4332.095 ms | 0.863505 | 56.905 ms | 142.418 ms |
| W41-B | 1240.233 ms | 4334.955 ms | 0.864075 | 56.622 ms | 144.894 ms |

Mean synthesis was `4336.014 ms` for W48 and `4326.722 ms` for W41: an
apparent `9.292 ms` / `0.21%` difference, well within run-to-run noise. W41
also had slightly worse mean TTFA and codec residual. It is rejected because
there is no material performance benefit to justify a second quality profile;
W48 remains the accepted bounded-idle experimental candidate.

### Rejected E20 delivery cadence

The W48 window can technically accommodate `emit_every_frames=20` because its
25-frame history plus 20 newly emitted frames fit the fixed 48-frame graph
input. The expected benefit was one fewer codec decode on this five-second
workload. This is a delivery-cadence experiment, not an autoregressive-model
optimization.

The E16 reference run `20260826T222124Z-98540` and E20 run
`20260826T222159Z-98540` both completed naturally with four chunks / 240,810
bytes / 120,405 samples and zero later-chunk queue-empty proxy observations.
Their PCM comparison failed the candidate-quality gate decisively: RMS delta
was `76.6663` (limit `3`), SNR was `26.8465 dB` (minimum `55 dB`), and maximum
absolute delta was `1839` (limit `64`). E20 is rejected without a timing ABBA;
its possible decode-count saving cannot justify this audio divergence.

The parity tool writes its report before returning status: a failed threshold
returns exit code `2`. In PowerShell, check `$LASTEXITCODE` after an invocation
when the exit status is not otherwise consumed; the report's
`threshold_pass=false` is the authoritative diagnostic record.

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

## Deferred multi-voice scheduling

Two independent fresh workers were launched simultaneously with the W48
right-padded manual codec graph, two-chunk prebuffer, full-EOS warmup, and
`emit_every_frames=16`: `ryan` run `20260826T100349Z-43736` and `serena` run
`20260826T100349Z-23228`. Both completed without CUDA out-of-memory failure,
but each recorded two later-chunk queue-empty proxy observations. They produced
the same 5.016875 s audio duration in 11.059799 s (RTF `2.204520`) and
11.606281 s (RTF `2.313448`) respectively.

This establishes only that two external GPU workers are technically viable on
this machine. It is not a supported real-time multi-voice mode. The WaveOut
measurement is a queue-starvation proxy, not a hardware-underrun counter.
Application concurrency should therefore remain queued through one worker;
multiple GPU workers are useful only for diagnostic or aggregate-throughput
experiments.

A future single-worker batch/interleaving design must preserve independent
generation, codec, EOS, cancellation, and seed state. It must additionally
demonstrate batch-2 fixed-seed PCM parity against equivalent single requests,
define the CUDA-Graph batch-size contract with a safe fallback, show no
single-voice latency regression, and publish separate two-voice throughput and
playback-proxy gates before it is considered a runtime feature.

## Next acceptance gates

1. Do not pursue further codec-window or delivery-cadence variants without a
   causal measurement. W41 brought no material throughput improvement and E20
   failed the PCM-quality gate; the remaining dominant work is the graph-captured
   autoregressive talker/predictor path. Any future AR speedup requires a
   separately validated engine-level approach rather than a silent runtime tweak.
2. Keep marker-aware ETW analysis limited to zero-loss, marker-complete ETLs;
   it remains an attribution tool, not a GPU-duration measurement on this WDDM
   stack.
3. Run a controlled opt-in sink-prebuffer A/B on the idle machine. Record TTFA,
   sink start, completion, per-chunk cadence, worker RTF, and proxy observations
   separately; do not describe delayed sink start as improved synthesis speed.
4. If a bounded playback reserve still reproduces a proxy outlier, capture a
   new marker-aligned ETL and investigate competing contexts or WDDM scheduling.

## Deferred native GGML/qwentts.cpp backend

The accepted Faster candidate remains the opt-in W48 right-padded codec decode
with a manual CUDA Graph. Its numerical and playback evidence must not change
while a native-engine experiment is evaluated.

The next A/B is intentionally a separate engine: the Python worker remains the
IPC host, but an explicit `ggml` backend may call the native qwentts.cpp DLL
through its Python adapter. This is not PCM-equivalent to Faster by design.
Initial acceptance therefore requires a CustomVoice streaming smoke, audible
quality review, format/duration checks, and independent timing/playback-proxy
evidence. It must not reuse Faster's byte-level PCM parity thresholds or make
claims about hardware underruns.

The experiment is default-off. Normal Faster playback must neither import the
adapter nor load a GGML DLL, weights, WPR, or additional diagnostics. A later
accepted native backend could move from this adapter to a direct C++ engine and
remove the Python runtime dependency; that is explicitly out of scope for this
first A/B.

The experimental GGML contract is deliberately narrower than the shared Qwen
configuration. It accepts only its native quantization, local source/cache/DLL
paths, codec chunk seconds, fixed sampling controls, and explicit language.
`language=auto` is rejected: qwentts.cpp auto-language behavior is not yet
validated, so silently substituting English would be incorrect. Likewise,
non-default Faster/upstream controls such as emit cadence, codec window,
overlap, compilation, CUDA Graph, prefill, profiling, and voice-profile options
are rejected rather than silently ignored. Native codec chunking is controlled
only by `--ggml-codec-chunk-seconds`.

### Local build prerequisites (CMP 50HX)

The tested local toolchain is CUDA Toolkit 13.3, Visual Studio 2022 Build Tools
with the Desktop development with C++ workload (MSVC v143 and a Windows SDK),
CMake 4.2.3, Git, and sufficient temporary disk for a native build plus GGUF
weights. Build from an x64 Visual Studio developer environment, not an ordinary
PowerShell, because `cl.exe` is injected by `VsDevCmd.bat`.

The CMP 50HX is compute capability 7.5, so the CUDA build must target `sm_75`:

```powershell
cmd /c 'call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\Common7\Tools\VsDevCmd.bat" -arch=x64 -host_arch=x64 && cl'
nvcc --version
nvidia-smi --query-gpu=index,name,compute_cap,driver_version --format=csv,noheader
```

The temporary source pins used for the local experiment are
`andimarafioti/qwentts-cpp-python` at
`b0b2da11293fb5a3f84fafc0a4c64524d7635b88` and `andimarafioti/qwentts.cpp` at
`b7d601ff66f71ef07b17305e18757c8c8f19f40a`. The native CMake configuration
must include `GGML_CUDA=ON` and `CMAKE_CUDA_ARCHITECTURES=75-real`. The DLL
bundle and GGUF weights remain local `tmp/` artifacts and must not be committed.
For CUDA 13.3 on Windows, the cuBLAS runtime is under
`%CUDA_PATH%\bin\x64`; the experimental host must add that directory with
`os.add_dll_directory()` before it loads `qwen.dll`.

The adapter has no ready Windows CPython 3.11 wheel, so build it from those
pinned sources. The GGUF CustomVoice model is separate from the Faster
safetensors model and must be downloaded into a local cache only after the DLL
smoke succeeds.

### Local native smoke result

The pinned source pair was built successfully with Ninja for `sm_75` on CUDA
13.3 and loaded by the sealed CPython 3.11 runtime. `QwenLibrary().version()`
reported `b7d601f (2026-05-20)`. With `CUDA_VISIBLE_DEVICES=0`, the native
runtime selected the CMP 50HX and completed a deterministic BF16 CustomVoice
streaming smoke using `speaker="ryan"`: 3 chunks, 24 kHz, 2.56 seconds of PCM,
first callback at about 1.48 seconds, and native synthesis completion at about
2.80 seconds. This validates the DLL, model format, CUDA path, CustomVoice
route, and streaming callback only; it is not a long-form timing or quality
acceptance result.

The selected upstream engine exposes the CustomVoice route but not the
wrapper's optional ABI-v2 speaker-enumeration symbols. The experiment must use
the known CustomVoice speaker name explicitly and must not treat the absence of
that optional enumeration API as evidence that CustomVoice streaming failed.

The first end-to-end bridge playback smoke also completed through the separate
`run-cmp50hx-ggml-playback-smoke.ps1` launcher: 8.96 seconds of 24 kHz PCM in
9 chunks, first PCM at about 1.33 seconds, synthesis completion at about 8.23
seconds, worker RTF `0.918687`, and zero WaveOut queue-starvation-proxy
observations with a two-chunk prebuffer. The record is a single native GGML
smoke, not a distributional performance conclusion, a Faster PCM-parity
comparison, or physical hardware-underrun evidence. The next acceptance gates
are listening/quality review, repeated idle and loaded runs, and an explicitly
separate quality comparison between engines.

A two-attempt idle pilot with the repeated-measurement harness used the same
BF16 model, speaker, one-second native codec chunks, and a two-chunk playback
prebuffer. Both attempts completed with zero queue-starvation-proxy
observations. The median first-audio time was 1.424 seconds and median RTF was
0.949 (p95 values 1.437 seconds and 0.953 respectively). This is a harness
validation and a promising baseline only: two attempts are insufficient for an
acceptance distribution or a Faster-versus-GGML comparison.

## Reproduction examples

Normal playback evidence (ETW follow-up is started only after an observed
proxy outlier):

```powershell
.\scripts\run-cmp50hx-playback-etw-soak.ps1 -Attempts 1
```

The native GGML experiment is a separate, default-off CustomVoice smoke. On a
worktree without generated build outputs, give it the already-built player and
sealed worker explicitly. Keep the local adapter source, GGUF cache, and CUDA
DLL directory outside Git:

```powershell
.\scripts\run-cmp50hx-ggml-playback-smoke.ps1 `
  -PlayerPath 'E:\_repoz\qwen3-tts-bridge-cpp\build\cmp50hx-diagnostic-mingw\qwen_tts_play.exe' `
  -PythonPath 'E:\_repoz\qwen3-tts-bridge-cpp\tmp\QwenTTSBridge-technical-beta-r3\QwenTTSBridge-technical-beta-r3\worker\python\python.exe' `
  -GgmlPythonPath 'E:\_repoz\_tmp-qwentts-cpp-python-cmp50hx\src' `
  -GgmlCachePath '.\tmp\cmp50hx-qwentts-gguf' `
  -CudaDllPath 'C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.3\bin\x64' `
  -Seed 20260806 `
  -WorkloadLabel 'uncontrolled_no_deliberate_gpu_workload' `
  -Language english `
  -Speaker ryan
```

This records a native-engine smoke only. It is intentionally not an ETW
capture, Faster parity test, or hardware-underrun measurement.

For repeated native-GGML baseline measurements, use the separate harness. It
extracts the worker's `request_finished` metric and the WaveOut proxy into one
summary; it does not capture PCM or decide quality equivalence. Use at least
five idle attempts before interpreting the median or p95, and repeat later
under a documented competing GPU workload:

```powershell
.\scripts\measure-cmp50hx-ggml-playback.ps1 `
  -Attempts 5 `
  -PlayerPath 'E:\_repoz\qwen3-tts-bridge-cpp\build\cmp50hx-diagnostic-mingw\qwen_tts_play.exe' `
  -PythonPath 'E:\_repoz\qwen3-tts-bridge-cpp\tmp\QwenTTSBridge-technical-beta-r3\QwenTTSBridge-technical-beta-r3\worker\python\python.exe' `
  -GgmlPythonPath 'E:\_repoz\_tmp-qwentts-cpp-python-cmp50hx\src' `
  -GgmlCachePath '.\tmp\cmp50hx-qwentts-gguf' `
  -CudaDllPath 'C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.3\bin\x64' `
  -Speaker ryan
```

The resulting `summary.json` reports per-attempt and aggregate synthesis time,
first audio, RTF, playback completion, and queue-starvation-proxy counts. It
is a native-GGML baseline, not a Faster-versus-GGML winner declaration.

Create the matching frozen-Faster W48 timing record with the normal playback
launcher, with ETW explicitly disabled, then normalize its worker telemetry.
Use the same text, speaker, prebuffer, attempt count, and declared workload
state as the native measurement. Do not use a historical Faster record with a
different text as an A/B result:

```powershell
.\scripts\run-cmp50hx-playback-etw-soak.ps1 `
  -Attempts 5 `
  -CodecRightPaddedDecode `
  -CodecRightPaddedCudaGraph `
  -CodecRightPaddedWindowFrames 48 `
  -PlaybackPrebufferChunks 2 `
  -WorkerSynthesisWarmup `
  -WorkerWarmupUnboundedPasses 1 `
  -WorkerWarmupMaxOutputChunks 2 `
  -EmitEveryFrames 16 `
  -Seed 20260806 `
  -WorkloadLabel 'uncontrolled_no_deliberate_gpu_workload' `
  -Language english `
  -SkipEtwFollowup

.\scripts\summarize-cmp50hx-faster-playback.ps1 `
  -SummaryPath .\tmp\cmp50hx-playback-etw-soak\<run-id>\summary.json
```

The normalizer refuses failed attempts, missing `request_finished` telemetry,
or a missing comparison-contract fingerprint. The two summary schemas expose
the same timing and playback-proxy fields, but they still do not establish
output quality equivalence. Listen to retained samples and assess quality
independently before selecting either backend.

Create a machine-readable timing-only comparison. The comparator fail-closes
unless both records have identical text hash, language, speaker, fixed seed,
requested and completed attempt counts, prebuffer, workload label, and disabled
ETW/PCM capture:

```powershell
.\scripts\compare-cmp50hx-backend-timing.ps1 `
  -GgmlSummaryPath .\tmp\cmp50hx-ggml-idle-comparison\<ggml-run-id>\summary.json `
  -FasterSummaryPath .\tmp\cmp50hx-faster-w48-idle-comparison\<faster-run-id>\faster-timing-summary.json
```

On the current CMP 50HX host, a pre-fingerprint five-attempt timing pilot used
the same text and `ryan` speaker, a two-chunk prebuffer, no deliberate
competing GPU workload, and no ETW/PCM capture. Both backends completed all
five attempts with zero WaveOut queue-starvation-proxy observations. Faster W48
had median RTF `0.870649` versus native GGML BF16 `0.955963` (GGML was 9.80%
higher, where lower is faster), and median first audio `1246.527 ms` versus
`1448.649 ms` (GGML was 16.21% higher). This observational pilot does not meet
the later enforced fingerprint contract and must be rerun before it is cited as
a formal A/B. The comparator treats RTF, first audio, completion, and proxy as
primary metrics; raw synthesis time and output duration remain diagnostic only.
The result rejects making GGML the CMP 50HX default on current timing evidence;
it does not reject the opt-in native backend, assess voice quality, or predict
behavior under a real competing workload.

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

E20 versus E16 PCM-quality pair for the W48 manual-graph candidate (capture
each side with the same seed and compare before timing it):

```powershell
$e16 = $common.Clone()
$e16.EmitEveryFrames = 16
& $runner @e16 -CodecRightPaddedWindowFrames 48 -PcmCaptureFile 'tmp\cmp50hx-e20-parity\e16.pcm'

$e20 = $common.Clone()
$e20.EmitEveryFrames = 20
& $runner @e20 -CodecRightPaddedWindowFrames 48 -PcmCaptureFile 'tmp\cmp50hx-e20-parity\e20.pcm'

& $common.PythonPath .\scripts\compare-cmp50hx-pcm-parity.py `
  --expected tmp\cmp50hx-e20-parity\e16.pcm `
  --candidate tmp\cmp50hx-e20-parity\e20.pcm `
  --output tmp\cmp50hx-e20-parity\report.json `
  --max-rms-delta 3 --min-snr-db 55 --max-abs-delta 64
```

Only if that quality gate passes, run fresh-worker E16/E20/E16/E20 timing
without PCM capture or ETW. A small difference is not a candidate: record
TTFA, synthesis time, RTF, proxy observations, and codec residual separately.

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
