# RTX 4090 Discovery Run

This is the first real full-corpus discovery measurement for
`representative-v4-r6-candidate`. It uses only the frozen `discovery.jsonl`
split. The 500-record holdout was not read or synthesized.

## Runtime

- GPU: NVIDIA GeForce RTX 4090
- Python: 3.12.10
- PyTorch: 2.10.0+cu128
- FasterQwen3TTS: 0.3.2
- Triton: triton-windows 3.6.0.post26
- Attention: SDPA; Flash Attention was unavailable
- Profile: `rtx4090-faster-customvoice-route-aware-scheduler-release-experimental`
- Model: Qwen3-TTS-12Hz-0.6B-CustomVoice, speaker `ryan`

## Result

All 1,500 discovery records reached the worker's completed state and the raw
result ID set exactly matches the frozen discovery split. The route contract
had no violations:

| Route | Requests | Schedule |
| --- | ---: | --- |
| compiled exact allowlist | 158 (10.53%) | 8, 8, 12 |
| eager unknown shape | 1,342 (89.47%) | 8 |

Latency for the complete run: first audio p50 372.910 ms, p95 427.811 ms,
p99 441.257 ms; completed p50 2,669.382 ms, p95 8,574.743 ms; inverse RTF
p50 2.653 and p95 2.993.

## Important Limits

The run was unseeded because the first runner revision did not expose a seed.
It is valid discovery evidence for actual input shapes and route coverage, but
it is not a reproducible performance baseline. The runner now defaults to a
request-ID-derived seed for the next measurement.

One record, `v4-b03-096`, emitted 1,999 codec frames (159.92 seconds) and
stopped at `max_seq_len` rather than EOS. It must be diagnosed before any
holdout or release-quality latency claim. The other 1,499 records terminated
at EOS.

The first process persisted records 1-1,070 and then stopped on a Windows
`fsync` `EINVAL`; this was an output durability issue, not an inference error.
The runner was fixed and resumed records 1,071-1,500 using the same input,
profile, runtime, and speaker. See `run-manifest.json`, `checkpoint.json`,
and the ordered `records.jsonl` for the full provenance trail.
