# Frequency R10 Internal Opt-In Candidate

## Status

The RTX 4090 48GB FasterQwen frequency exact-allowlist configuration is an
internal opt-in candidate. The project default remains unchanged. No result
here applies to other GPUs, including the deferred CMP 50HX profile.

This is a pinned `NVIDIA GeForce RTX 4090` configuration reporting `48 GiB`
of total VRAM. A normal 24GB RTX 4090, RTX 3090, or any other CUDA GPU may use
the generic eager path, but must receive its own profile, smoke, and soak before
this compiled configuration can be enabled there.

## Runtime Contract

- Exact compiled prefill lengths: `18, 19, 20, 26, 27, 29`.
- Unknown lengths: eager only; they never trigger an implicit compilation.
- Compiled emission schedule: `8, 8, 12`; eager schedule: `8`.
- Strict BF16 SDPA, exact zero-delta allowlist gate, and generation priming are
  required.
- The policy pins the full non-transient model directory, the complete installed
  Triton file set, Python, Torch/CUDA, FasterQwen, worker, profile, and evidence
  hashes. Repository text identities are canonicalized to LF so Git's Windows
  CRLF checkout conversion does not cause false drift; models and binary bundles
  remain byte-for-byte sealed. Arbitrary launcher overrides are rejected for this
  internal profile.

## Operational Evidence

- The launcher-mediated Python soak passed 504 mixed compiled/eager operations:
  396 completed, 108 cancelled across every cancellation phase, nine semantic
  references, and six cache entries.
- The public C++ API soak passed 250 operations: 225 completed, 25 cancelled,
  one worker identity, and six cache entries.
- The post-sealing Python smoke passed 36 completed and 27 cancelled requests,
  including all six compiled lengths, three eager holdouts, and all cancellation
  phases.
- The final clean-source sealing smoke repeated the same 36/27 gate after argv
  and content-manifest hardening, with six cache entries and zero allocated CUDA
  memory growth.
- The frozen holdout remains descriptive only and was not used to tune forms.

The mixed Python soak is not a latency SLA: first audio was `384.5 ms` median,
`1073.9 ms` p95, and `1197.2 ms` maximum. Eager holdouts reached roughly
`1.17-1.18 s` p95, so arbitrary text shapes need that expectation documented.

See [the evidence README](benchmark-artifacts/rtx4090-2026-08-01/frequency-exact-allowlist-operational-r10/README.md)
and `runtime-policy-v4-rtx4090-48gb-internal-opt-in.json` for validation commands and exact
provenance.

## Deferred Work

`5, 8, 12` scheduling, padded prefill buckets, a broader hardware rollout, and
the CMP 50HX profile remain deferred experiments. They must start from a new
correctness and measurement plan rather than inheriting this internal opt-in.
