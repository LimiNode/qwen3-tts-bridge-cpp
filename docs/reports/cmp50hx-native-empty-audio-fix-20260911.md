# CMP 50HX native empty-audio fix acceptance — 2026-09-11

## Scope

This report records the focused rerun of the four-row direct-reference native
workload after qwentts.cpp fix PR #2 (`7dea823fa9e2b9d65ae596231a75edc7f9a2c9f7`).
The previous runtime could sample codec EOS at generation step 0 and report a
successful `natural_eos` with no PCM. The native worker correctly rejected that
result as `empty_audio`; this run verifies the engine-side fix.

Hardware: NVIDIA CMP 50HX, 20,480 MiB, driver 581.94, CUDA backend. The run
used the Bridge post-fix commit `ca8e0b49` and qwentts.cpp runtime commit
`7dea823`. The same four direct-reference rows from the initial diagnostic
run were used, with absolute paths to the checked-out `A.wav`/`B.wav` files.
No cancellation or playback sink was enabled in this focused engine check.

Raw result and stderr are retained outside git:

* `C:\\tmp\\cmp50hx-native-acceptance\\formal-direct-reference-postfix-abs-20260911.json`
* `C:\\tmp\\cmp50hx-native-acceptance\\formal-direct-reference-postfix-abs-20260911.stderr.log`

## Result

All four rows completed with non-empty PCM and `natural_eos`:

| Row | PCM bytes | Outcome |
| --- | ---: | --- |
| `ru-short-a` | 26,880 | `natural_eos` |
| `en-short-b` | 19,200 | `natural_eos` |
| `ru-medium-a` | 72,960 | `natural_eos` |
| `en-medium-b` | 26,880 | `natural_eos` |

The acceptance summary reported `failed_requests=0` and
`acceptance_failed_requests=0`. The formerly failing `en-medium-b` row now
produces 26,880 bytes instead of an empty stream.

Focused timing (startup included only in the top-level startup field):

* startup: 9,665.568 ms;
* first PCM median: 6,815.930 ms, p95: 7,618.658 ms;
* completion median: 7,091.584 ms, p95: 7,861.350 ms;
* RTF median: 13.032.

These numbers are diagnostic, not the final native-vs-Faster parity table. The
full streaming cadence, starvation, playback, cancellation, quality, and
voice-identity gates remain covered by the formal acceptance procedure.

## Root cause and fix

The failing request sampled codec EOS on step 0 (`c0=2150`) and retired with
zero generated codec frames. qwentts.cpp now masks the codec EOS logit only for
the first generation step. EOS remains available on later steps, while every
successful natural-EOS request is guaranteed to have at least one codec frame.

The fix passed qwentts.cpp CPU and Windows shared CI, and Bridge PR #81 passed
all four Windows CI jobs before merge.

## Next gate

Repeat the complete native-vs-Faster direct-reference matrix with playback and
quality review enabled. Keep the registered-voice/prefix-KV Faster run as a
separate optimized baseline; do not merge its latency into this parity result.
