# CMP 50HX ABI-6 playback telemetry v2 acceptance

This pass supersedes the runtime attribution and WaveOut cadence conclusion in
the earlier ABI-5 reports. It uses the Bridge source merged by PR #175,
qwentts `130cb99` ABI 6, GGML `c044c6f`, CUDA graphs enabled, Q8 Talker and
codec models, and the registered `kraftwerk_robot_ru_warm` profile with its
matching Cyrillic reference text.

The exact source, input text, reference conditioning, binaries, models, and
output hashes are recorded in the companion JSON. The player emitted the CUDA
graph warmup marker before every measured request.

## Corrected long WaveOut result

The physical WaveOut run used `stream-max-chunk-frames=8`, guard OFF, a 15 ms
terminal fade, and 85 ms completion silence. The model reached natural EOS at
218 frames with qwen total 4920.63 ms and RTF 0.282. Playback completed with
32 sink chunks including the tail and 17.525 seconds of audio.

The corrected cursor-relative backpressure metric recorded:

- zero queue-empty events after the first chunk;
- median backpressure wait 634.451 ms;
- maximum backpressure wait 650.765 ms.

This establishes that the old `52/56` queue-empty result was caused by the
sink's full-buffer backpressure calculation. It is not evidence of a native
chunk scheduler defect. Callback arrival remains serialized by the synchronous
sink callback, so its roughly 640 ms gaps must not be interpreted as raw
worker or transport cadence.

## Cancellation and recovery

Early, middle, and backlog cancellation all obtained a physical playback
cursor, selected the containing submitted buffer, retained exactly 360 frames
of fade, called `waveOutReset`, and completed a second request at natural EOS
without restarting the worker. Measured reset calls took 4.983, 8.915, and
2.603 ms respectively.

The epoch guard discarded 1, 1, and 2 stale callback attempts after the three
cancellations. These counts describe audio rejected before WaveOut submission;
they are not late audio played after the terminal event.

## Natural-EOS matrix

The no-playback probe then ran the same exact UTF-8 Russian text with guard OFF:

| Seed | First PCM | Frames | Qwen total | Outcome | Starvation |
| ---: | ---: | ---: | ---: | --- | --- |
| 1000 | 196.111 ms | 217 | 4879.95 ms | `natural_eos` | no |
| 1002 | 197.487 ms | 218 | 4914.35 ms | `natural_eos` | no |
| 1006 | 196.378 ms | 224 | 5060.08 ms | `natural_eos` | no |
| 1008 | 197.525 ms | 218 | 4906.81 ms | `natural_eos` | no |

This is current ABI-6 runtime evidence. The older ABI-5 EOS rows remain useful
historically but are not part of current canonical acceptance.
