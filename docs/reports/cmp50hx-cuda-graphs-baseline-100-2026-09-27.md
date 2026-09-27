# CMP 50HX CUDA-graphs 100-request baseline (2026-09-27)

This baseline extends the 30-request canary with the same persistent ON worker,
Q8 models, registered `kraftwerk_robot_ru_bootstrap_fidelity` voice, Russian
text, seed `1002`, and one-frame streaming chunks.

- 100/100 requests completed with `natural_eos`.
- `ready.warmed_up=true`; CUDA graph warmup marker observed.
- Every request produced 18 chunks / 69120 PCM bytes.
- All 100 PCM SHA-256 values were identical:
  `E68D8F3630D74A6B88D0D8FB4F9E82E84BB7DDC2BE80EDF0676C26E2A785493B`
- Worker exit code: `0`.

| metric | p50 | p95 | p99 | max |
| --- | ---: | ---: | ---: | ---: |
| first PCM | 179.282 ms | 181.641 ms | 189.236 ms | 194.220 ms |
| request wall time | 609.090 ms | 620.897 ms | 648.249 ms | 654.652 ms |
| median inter-chunk gap | 24.815 ms | 25.326 ms | 25.875 ms | 25.995 ms |
| maximum inter-chunk gap | 25.644 ms | 27.939 ms | 33.936 ms | 42.718 ms |

This is a single-text/single-seed/single-voice CMP 50HX baseline, not a general
release SLO. The next acceptance gate is a longer RU/EN text matrix, followed
by EOS guard ON/OFF listening and soak tests.

