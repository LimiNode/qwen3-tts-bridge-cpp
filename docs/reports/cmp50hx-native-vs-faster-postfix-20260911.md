# CMP 50HX native-vs-Faster direct-reference rerun — 2026-09-11

This is the apples-to-apples rerun after qwentts.cpp PR #2 and Bridge PR #81.
Both backends consumed the same direct-reference manifest, seeds, model family,
and four-row workload. Registered voices and prefix-KV are intentionally not
part of this comparison.

Hardware: NVIDIA CMP 50HX (20,480 MiB), driver 581.94, CUDA. Bridge runtime
commit: `ca8e0b49`; qwentts.cpp: `7dea823`; FasterQwen source:
`90b596d2ffa41eb2da173db92e6f896df11b19cb`. The run used six requests
(four manifest rows followed by two cyclic repeats), no cancellation, and no
physical playback sink.

Raw combined artifacts are retained outside git:

`C:\\tmp\\cmp50hx-native-acceptance\\formal-parity-postfix-20260911.json.artifacts\\20260911T164334270Z-dba8bfc4147b4e55ad752b29d213ee44`

## Acceptance result

The runner exited successfully. Both backends completed all six requests with
non-empty PCM and passed the fail-closed acceptance gates. In particular, the
previously failing `en-medium-b` native row completed successfully.

| Backend | First PCM median | First PCM p95 | Completion median | Completion p95 | RTF median | Requests |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| FasterQwen low-latency | 6,260.139 ms | 12,138.993 ms | 18,686.529 ms | 23,225.294 ms | 14.332 | 6/6 |
| Native qwentts | 6,883.437 ms | 8,318.353 ms | 7,174.119 ms | 8,552.084 ms | 14.100 | 6/6 |

The native PCM sizes were 26,880 / 19,200 / 72,960 / 26,880 bytes for the
first four rows; the Faster sizes were 30,684 / 42,188 / 72,876 / 69,038
bytes. Byte-for-byte equality is not expected across different codec engines;
listen-based quality and voice-identity review remains a separate gate.

## Interpretation

The engine-side EOS guard removed the `empty_audio` failure without changing
later EOS handling. Native completion latency was lower in this batch, while
first-PCM latency was comparable but slightly higher than FasterQwen's median.
These values supersede neither the initial pre-fix report nor the separate
registered-voice/prefix-KV Faster baseline; those remain preserved as distinct
experiments with different runtime semantics.

Remaining release gates are physical playback, starvation/cadence under the
real sink, cancellation/restart lifecycle, multilingual quality and voice
identity, and a separate exact-condition `cmp50hx-fastest` prefix-KV baseline.
