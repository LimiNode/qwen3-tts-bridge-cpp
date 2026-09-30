# CMP 50HX native natural-EOS matrix

This is a fresh no-playback matrix captured after the WaveOut cancellation
work, but it uses the older qwentts `40ab5eb` ABI-5 hardware package. The
current Bridge source tree pins qwentts `130cb99` ABI 6, so these rows are
historical runtime evidence rather than canonical-runtime acceptance. The input was passed as escaped Unicode and decoded
to UTF-8 before the worker request; the earlier PowerShell-piped attempt that
produced `????` is discarded.

## Contract and provenance

| Item | Value |
| --- | --- |
| Bridge main | `ad095a3e` |
| qwentts | `40ab5eb` (legacy ABI-5 hardware package; current source pin: `130cb99` ABI 6) |
| Talker / codec | Q8_0 Talker and 12 Hz Q8_0 codec |
| Voice | registered `canonical_fidelity` |
| Language | `russian` |
| Text | `Сегодня проверяем естественное завершение русской фразы на каноническом native runtime.` |
| Warmup | enabled for the same voice and language |
| Stream chunk cap | 8 frames |

Raw probe JSON files are retained under
`C:\tmp\cmp50hx-eos-matrix-9277b0eb-corrected` and are not committed.

## Results

| Seed | First PCM | Frames | Audio | qwen total | Execution outcome | Probe exit |
| ---: | ---: | ---: | ---: | ---: | --- | ---: |
| 1000 | 229.7 ms | 99 | 7.92 s | 7.744 s | `natural_eos` | 1 |
| 1002 | 231.6 ms | 148 | 11.92 s | 11.240 s | `natural_eos` | 1 |
| 1006 | 234.3 ms | 94 | 7.60 s | 7.451 s | `natural_eos` | 1 |
| 1008 | 230.1 ms | 130 | 10.83 s | 10.154 s | `natural_eos` | 1 |

All four requests emitted non-empty PCM, completed normally, and reached
`natural_eos`; none hit the native token cap. The probe exit code is `1` for
each row because its strict inter-chunk starvation proxy observed at least one
gap larger than the preceding 80 ms audio buffer. This is a streaming cadence
finding, not an EOS failure, and it remains a separate acceptance item for
long utterances. The bounded WaveOut cancellation scenarios use a larger
producer chunk (`stream-max-chunk-frames=8`) and passed their physical reset
and next-request checks.

## Scope

This matrix establishes natural-EOS behaviour only for the recorded
`40ab5eb` package, one Russian utterance, and the four listed seeds. ABI 5
does not contain the ABI-6 EOS-guard controls, so this matrix cannot validate
the current guard implementation or decide its production default. Re-run the
same exact UTF-8 text/seeds on the source-pinned `130cb99` ABI-6 CUDA-graphs
runtime before using the result as current release evidence.
