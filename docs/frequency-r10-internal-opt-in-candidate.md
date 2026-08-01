# Frequency R10 Internal Opt-In Candidate

## Status

The RTX 4090 FasterQwen frequency exact-allowlist configuration is an internal
opt-in candidate. The project default remains unchanged. No result here applies
to other GPUs, including the deferred CMP 50HX profile.

## Runtime Contract

- Exact compiled prefill lengths: `18, 19, 20, 26, 27, 29`.
- Unknown lengths: eager only; they never trigger an implicit compilation.
- Compiled emission schedule: `8, 8, 12`; eager schedule: `8`.
- Strict BF16 SDPA, exact zero-delta allowlist gate, and generation priming are
  required.
- The policy pins the Python, Torch/CUDA, Triton, FasterQwen, worker, profile,
  and evidence hashes.

## Operational Evidence

- The launcher-mediated Python soak passed 504 mixed compiled/eager operations:
  396 completed, 108 cancelled across every cancellation phase, nine semantic
  references, and six cache entries.
- The public C++ API soak passed 250 operations: 225 completed, 25 cancelled,
  one worker identity, and six cache entries.
- The frozen holdout remains descriptive only and was not used to tune forms.

See [the evidence README](benchmark-artifacts/rtx4090-2026-08-01/frequency-exact-allowlist-operational-r10/README.md)
and `runtime-policy-v2-internal-opt-in.json` for validation commands and exact
provenance.

## Deferred Work

`5, 8, 12` scheduling, padded prefill buckets, a broader hardware rollout, and
the CMP 50HX profile remain deferred experiments. They must start from a new
correctness and measurement plan rather than inheriting this internal opt-in.
