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

Sanitized per-request measurements are retained in
`evidence/cmp50hx-postfix-20260911/request-results.jsonl`; they are sufficient
to recompute the aggregate values below without access to the machine-local
raw JSON.

## Acceptance result

The runner exited successfully. Both backends completed all six requests with
non-empty PCM and passed all automated terminal/provenance gates exercised by
this six-request no-playback run. In particular, the previously failing
`en-medium-b` native row completed successfully.

| Backend | First PCM median | First PCM p95 | Completion median | Completion p95 | RTF median | Requests |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| FasterQwen low-latency | 6,260.139 ms | 12,138.993 ms | 18,686.529 ms | 23,225.294 ms | 14.332 | 6/6 |
| Native qwentts | 6,883.437 ms | 8,318.353 ms | 7,174.119 ms | 8,552.084 ms | 14.100 | 6/6 |

The native PCM sizes were 26,880 / 19,200 / 72,960 / 26,880 bytes for the
first four rows; the Faster sizes were 30,684 / 42,188 / 72,876 / 69,038
bytes. Byte-for-byte equality is not expected across different codec engines;
listen-based quality and voice-identity review remains a separate gate.

A controlled pre/post check rebuilt qwentts.cpp at the old `1c119f6` commit
and the fixed `7dea823` commit with identical MSVC/CUDA settings, then ran the
same three labels and seeds in fresh worker processes. First-PCM, completion,
RTF, and PCM byte counts were materially unchanged; the per-row values are
preserved in `evidence/cmp50hx-postfix-20260911/pre-post-comparison.json`.

The native playback probe also captured non-empty PCM for the two English rows
that were used to reproduce the original empty-audio report. The capture
metadata and SHA-256 digests are preserved in
`evidence/cmp50hx-postfix-20260911/pcm-capture-summary.json`; the raw PCM stays
outside git under the local acceptance artifact directory. This proves transport
delivery and terminal completion only. Full-text pronunciation, truncation,
quality, and voice identity remain unverified and are explicit release gates.
The follow-up signal diagnostic found peak amplitudes of only 12 and 7 in the
two English native captures (normalized peaks below 0.0004); therefore these
files must currently be treated as near-silent output, not as evidence that the
target sentences were spoken. The native decoder/output-scaling path is now a
functional blocker for semantic acceptance. A canary using the exact
pre-follow-up Bridge pin, `qwentts.cpp@e9ead9e`, and a fresh DLL hash reproduced
the same near-silent `en-medium-b` signature; details are in
`evidence/cmp50hx-postfix-20260911/current-pin-canary.json`.
The follow-up submodule bump to `a3eecf1` contains only the upstream sampling
contract test and CI changes (no runtime source changes), but its exact CUDA
DLL was not rebuilt for this canary. A release-quality semantic gate therefore
still requires a fresh capture from the pinned `a3eecf1` runtime.

## Interpretation

The engine-side EOS guard removed the `empty_audio` failure without changing
later EOS handling. Native completion latency was lower in this batch, while
first-PCM latency was comparable but slightly higher than FasterQwen's median.
These values supersede neither the initial pre-fix report nor the separate
registered-voice/prefix-KV Faster baseline; those remain preserved as distinct
experiments with different runtime semantics.

`benchmark_starvation_proxy` refers only to the benchmark-side transport
check. It is not a physical playback starvation result. Remaining release
gates are a 30–100-request sequential soak, long and near-capacity rows,
physical playback, starvation/cadence under the real sink,
cancellation/restart lifecycle, multilingual quality and voice identity, and a
separate exact-condition `cmp50hx-fastest` prefix-KV baseline.
