# Frequency Exact-Allowlist Operational Soak R10

This record promotes one narrowly defined RTX 4090 configuration to an internal
opt-in. It does not change the default worker profile.

## Frozen Runtime Contract

- FasterQwen runtime: `faster-qwen3-tts` 0.3.2 from source commit
  `1ab0dc0e2c9b98292960e3e8469bd554ae744354`; module bundle SHA-256
  `c258f89d59894f549c65324d793575aab31161d91f6825db1f5d6ca1317431df`.
- Python: 3.12.10; Torch: 2.10.0+cu128; CUDA runtime: 12.8; Triton Windows:
  3.6.0.post26.
- Backend: FasterQwen, BF16 SDPA and `strict_bf16_sdpa_v1`.
- Exact compiled prefill lengths: `[18, 19, 20, 26, 27, 29]`.
- Compiled chunk schedule: `[8, 8, 12]`; eager chunk schedule: `[8]`.
- Unknown shapes are eager. Compile-on-miss is disabled and every compiled
  prefill must already be present in the six-entry allowlist cache.

## Python Worker Soak

`python-operational-soak-final-report.json` SHA-256:
`cc3436988bacdee92980b8250d811f1e4fdf61997ed342fb88b3deb93a3e7007`.

- PASS: 504 requests, 396 completed and 108 cancelled.
- All nine frozen labels exercised every cancellation stage twelve times.
- Cache entries remained six and Dynamo graph delta remained zero.
- Median first audio was 254.289 ms; median RTF was 0.360.
- RSS grew 40.215 MiB, private bytes grew 90.574 MiB, allocated CUDA memory
  had zero end-to-end growth, and reserved CUDA memory grew 6 MiB with zero
  tail slope.
- Windows WDDM exposes no `nvidia-smi --query-compute-apps` PID rows here.
  This is recorded as unsupported; worker-side CUDA allocator and process-tree
  memory gates still passed.

## C++ Public API Soak

`cpp-api-soak-r250.json` SHA-256:
`45461a25378ee4336892e7002d9ff0be8ede2fd20994661ff63ccda41e498089`.

`cpp-api-soak-r250-validation.json` SHA-256:
`33950b3cb8ece08c66f8389ceacaca8995c47ceca4e4e619caab85763bcdb0c`.

- PASS: 250 measured public-C++-API requests from one worker PID.
- 225 completed and 25 cancelled after the first PCM chunk.
- All declared manifest contracts passed, including the cancellation-prefix
  contract; cache entries observed were `[6]`.
- Median first audio was 251.573 ms; median RTF was 0.363.

## Scope

The approved profile is an internal RTX 4090 opt-in only. It is not a release
default, does not authorize padded buckets or `5 -> 8 -> 12`, and does not
generalize to other hardware or runtime bundles.
