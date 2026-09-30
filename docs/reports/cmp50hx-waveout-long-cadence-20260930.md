# CMP 50HX long WaveOut cadence check

The cancellation cursor contract passes for bounded interruptions on the
tested package, but a longer physical playback request exposes a cadence
limitation on that same legacy runtime.

## Setup

- qwentts `40ab5eb` ABI 5 (legacy hardware package; current Bridge source
  pins `130cb99` ABI 6), Q8_0 Talker/codec, registered `canonical_fidelity`;
- native worker on NVIDIA CMP 50HX;
- `stream-max-chunk-frames=8` (640 ms PCM chunks);
- warmup enabled;
- the same UTF-8 Russian request was used for both runs;
- no cancellation and no terminal fade.

Raw metrics are retained under `C:\tmp\cmp50hx-long-waveout` and are not
committed.

## Results

| Playback prebuffer | Result | Audio chunks | Audio duration | Queue-empty proxy | Maximum inter-arrival |
| ---: | --- | ---: | ---: | ---: | ---: |
| 1 | completed, exit `0` | 56 | 32.005 s | 52 | 664.9 ms |
| 2 | completed, exit `0` | 38 | 22.160 s | 35 | 665.4 ms |

The first run reached `natural_eos` after 398 frames with qwentts total
`30.294 s` and RTF `0.951`; the second run also completed normally. The
queue-empty proxy still fired for most later chunks in both runs. This means
the average producer rate is near realtime, but its chunk cadence is not yet a
continuous-playback acceptance result. Increasing the existing prebuffer from
one to two chunks is therefore insufficient on this hardware/runtime pair.

This finding is independent of cancellation correctness, but it is also
runtime-specific. It must not be treated as a cadence blocker for the current
source-pinned ABI-6 runtime until reproduced there.

Earlier qwentts `130cb99` CUDA-graphs-ON evidence on the same CMP 50HX
recorded no starvation for its bounded short request and a maximum inter-chunk
gap of 42.718 ms across a 100-request single-text baseline. That does not prove
long-text continuity on ABI 6, but it is enough to require a paired ABI-6
long-WaveOut rerun before changing chunk scheduling or adding more buffering.

## Measurement correction

The playback result above must not be used to diagnose native producer cadence.
At capture time the WaveOut example applied its 250 ms backpressure threshold
to the sum of each submitted buffer's full duration rather than the remaining
audio ahead of the physical playout cursor. With
`stream-max-chunk-frames=8`, one chunk represents about 640 ms of audio and is
therefore already larger than the threshold. The following enqueue could stay
blocked until the current WaveOut buffer became `WHDR_DONE`, which can
self-induce an empty queue before the next submission.

The recorded `inter-arrival` timestamps were also taken after that sink-side
backpressure wait. They therefore measure application/sink admission timing,
not raw worker or transport emission cadence.

A corrected player uses remaining cursor-relative playout-ahead duration for
backpressure and records callback arrival separately from post-backpressure
admission. Re-run the long physical playback test with that code before opening
a native chunk-scheduling investigation. If cadence still needs analysis,
measure it in the no-playback/native probe path so sink backpressure cannot
contaminate producer timing.
