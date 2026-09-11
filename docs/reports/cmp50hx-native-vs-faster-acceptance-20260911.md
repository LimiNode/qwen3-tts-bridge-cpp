# CMP 50HX native-vs-FasterQwen acceptance — 2026-09-11

## Scope

This report records the first reproducible hardware comparison after the
acceptance harness hardening. The parity run uses the same direct-reference
manifest for both backends; it does not use registered voices or prefix-KV.
The optimized FasterQwen run is recorded separately and must not be read as an
apples-to-apples engine comparison.

Hardware: NVIDIA CMP 50HX, 20,480 MiB, driver 581.94, CUDA backend.
GPU 1 (GTX 1060, 3,072 MiB) was not used. Bridge commit: `95d72936`.
FasterQwen commit: `90b596d2ffa41eb2da173db92e6f896df11b19cb`.
Native qwentts runtime: commit `1c119f69b0008edb8b687a8df3d7a537c8a22dbe`,
ABI 5, CUDA DLL build recorded in the artifact manifest.

The raw artifacts are intentionally kept outside git because they contain
machine-local paths and generated logs:

* direct-reference accepted run:
  `C:\tmp\cmp50hx-native-acceptance\formal-direct-reference-pass-20260911.json.artifacts\20260911T111230911Z-254e498fbba04af3bea753285194797a`
* direct-reference diagnostic run including `en-medium-b`:
  `C:\tmp\cmp50hx-native-acceptance\formal-direct-reference-20260911.json.artifacts\20260911T105605561Z-1be19f945ca244ce9687693f7f344049`
* registered-voice/prefix-KV Faster run:
  `C:\tmp\cmp50hx-native-acceptance\formal-fastest-20260911.json` and
  `formal-fastest-20260911.stderr.log`

## Direct-reference parity

The accepted subset contains six persistent requests (two repetitions of
`ru-short-a`, `en-short-b`, and `ru-medium-a`). No cancellations were used;
startup is excluded from per-request latency.

| Backend | First PCM median | First PCM p95 | Completion median | RTF median | Requests |
| --- | ---: | ---: | ---: | ---: | ---: |
| Native qwentts | 2,927.528 ms | 3,884.903 ms | 3,051.761 ms | 5.539 | 6/6 |
| FasterQwen low-latency | 6,816.403 ms | 18,078.718 ms | 21,231.757 ms | 15.067 | 6/6 |

All six requests completed successfully in both backends. This is a timing
observation, not a quality claim: PCM listening, voice-identity review, and a
larger multilingual matrix remain required before release acceptance.

The four-row diagnostic run additionally included `en-medium-b`. Native
returned `empty_audio` for that row while the other three rows passed. The
runner retained both backend results and failed closed. This remains an open
native medium-path defect and is not hidden by the accepted subset.

## Registered-voice/prefix-KV Faster baseline

The separate FasterQwen run used `cmp50hx-fastest`, registry voice `cmp50hx_a`,
internal voice warmup, `max_seq_len=448`, W29, E3→E4 scheduling, and prefix-KV
reuse. Six requests completed successfully:

| Metric | Value |
| --- | ---: |
| Worker startup | 28,529.498 ms |
| First PCM median | 1,278.690 ms |
| First PCM p95 | 1,755.498 ms |
| Completion median | 1,602.988 ms |
| RTF median | 5.367 |
| Prefix-KV hits | 1/6 |

This run is a best-production-path observation for the current environment,
not a parity result. It is not comparable to the historical ~520 ms result:
the current run did not reproduce the complete historical warmup/cache-hit
conditions for every request.

## Conclusions and next gates

1. Native qwentts is functional on CMP 50HX and was faster than the selected
   Faster low-latency direct-reference run in this batch.
2. Native does not yet pass the full direct-reference matrix because
   `en-medium-b` produced empty audio.
3. The optimized registered-voice Faster path remains a separate baseline;
   its latency must not be merged into the parity table.
4. Next work is to diagnose native empty audio on medium English, repeat the
   direct-reference matrix after the fix, and then run the registered-voice
   Faster profile with the exact historical warmup/cache-hit workload.
