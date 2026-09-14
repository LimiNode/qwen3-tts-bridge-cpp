# CMP 50HX native predictor Philox schedule — 2026-09-14

This report records the first executable verification of the opt-in
`predictor_philox` trace emitted by qwentts.cpp. It is diagnostic evidence, not
release acceptance and not a performance baseline.

## Source and caveat

The authoritative raw probe was captured as
`cmp50hx-native-trace-1006-hybrid.json` (SHA-256
`2c82c150db44488dc9e47d4893d0681f9250c08d8d9568e4480f484bceafbbb`). The WAV
hash is `525e0928616a1bf13671e526fd6d70a362c1ad5f021b4039283c2f7c46dd7b3b`.

This was intentionally a correctness-only hybrid runtime: the new qwen
pipeline/worker came from qwentts.cpp `ed3c665`, while the working CMP DLLs
came from `1c119f6`; both used ggml commit
`c044c6f03892f9d5e98213b05f8afea1f8b0d3c9`. CUDA 13.3 builds from the new
pipeline produced unusable kernels on compute capability 7.5. Therefore the
reported 4934.6903 ms first PCM must not be compared with a production
baseline.

## Executable schedule check

The validator is dependency-free and mirrors qwentts.cpp Philox4x32-10,
including the float32 conversion:

```powershell
python scripts/validate-cmp50hx-philox-trace.py `
  --probe C:\path\to\cmp50hx-native-trace-1006-hybrid.json
```

Result:

```text
seed=1006 records=2 draws=30 steps=[0, 1]
max_abs_error=4.988709445541417e-11 tolerance=1e-7
```

Both complete predictor records passed:

```text
Talker subsequence 0  -> predictor 1..15
Talker subsequence 16 -> predictor 17..31
```

The trace itself observed the existing RNG draws and did not consume an extra
random number. The validator confirms the schedule and each recorded uniform;
it does not claim that native and FasterQwen select identical tokens.

## Request geometry and bounded result

The run used seed `1006`, `T_ctx=236`, `T_trailing=1`, `ref_T=226`, and
`stream_max_chunk_frames=1` with synthesis warmup disabled. It reached natural
EOS after two codec frames, produced 7680 audio bytes in two chunks, and did
not report starvation. The prompt/reference geometry is recorded here only to
make the diagnostic trace reproducible; it is not a semantic quality claim.

## Next gate

Do not change production sampling, EOS suppression, `min_new_tokens`, or RNG
mapping based on this result. The next experiment is a deterministic
native/FasterQwen predictor comparison using identical logits/history and the
shared Philox stream. Only after that comparison should we run forced
model-level parity and then multi-seed production statistics.

The machine-readable artifact is
[`evidence/cmp50hx-native-philox-schedule-20260914.json`](evidence/cmp50hx-native-philox-schedule-20260914.json).
