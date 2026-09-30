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
