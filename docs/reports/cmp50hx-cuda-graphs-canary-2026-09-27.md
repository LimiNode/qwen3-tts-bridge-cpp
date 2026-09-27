# CMP 50HX CUDA-graphs 30-request canary (2026-09-27)

This canary follows the paired OFF/ON probe recorded in
`cmp50hx-cuda-graphs-paired-2026-09-27.md`. It uses the same ON runtime,
registered Kraftwerk voice, Russian text, seed `1002`, Q8 models, and
`--stream-max-chunk-frames 1`. One persistent worker was warmed once and then
served 30 sequential synthesis requests without restart.

## Results

- `ready.warmed_up`: `true`
- CUDA graph warmup marker: observed
- all 30 requests: `completed`, `natural_eos`, 18 chunks, 69120 PCM bytes
- all 30 PCM SHA-256 values identical:
  `E68D8F3630D74A6B88D0D8FB4F9E82E84BB7DDC2BE80EDF0676C26E2A785493B`
- worker exit code: `0`

| metric | p50 | p95 | p99 | max |
| --- | ---: | ---: | ---: | ---: |
| first PCM | 179.072 ms | 189.298 ms | 193.949 ms | 194.871 ms |
| request wall time | 608.318 ms | 623.102 ms | 625.903 ms | 626.984 ms |
| median inter-chunk gap | 24.797 ms | 25.163 ms | 25.307 ms | 25.360 ms |
| maximum inter-chunk gap | 25.514 ms | 27.040 ms | 29.552 ms | 30.513 ms |

This supports moving to the 100-request baseline and longer RU/EN texts. It is
not a release-wide performance claim: the canary covers one text, one seed,
one registered voice, and one GPU.

