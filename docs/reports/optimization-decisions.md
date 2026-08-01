# Optimization Decisions

## Accepted

### Frequency exact allowlist

Compilation is restricted to six frequent, verified prefill lengths. Unknown
lengths do not fail: they use eager execution. The fail-closed part is that an
unknown input cannot silently create a new compiled graph. This keeps cache
growth predictable and makes the selected shapes measurable.

### Generation priming and safe chunk schedule

The selected compiled schedule is `8, 8, 12`, with eager remaining at `8`.
Generation priming improved the selected path while preserving the current
correctness gates and producing no cache or memory-growth failures in the
operational evidence.

### Strict correctness gates

Compiled BF16 prefill is permitted only under strict SDPA and an exact
zero-delta gate for the verified contract. The runtime policy pins model,
worker, FasterQwen, Python/Torch/CUDA, and Triton provenance so that the claim
does not silently migrate to a different environment.

## Rejected or deferred

### Padded prefill buckets

Left-padding inputs into convenient buckets changed logits, KV state, or codec
trace in the investigated path. It is archived as a rejected experiment; the
frequency work carries none of its runtime behaviour forward.

### Global aggressive schedules

`5, 8, 12` and `6, 8, 12` schedules showed underrun/correctness risk outside a
narrow context. They are not part of the internal profile. The safer
`8, 8, 12` schedule remains explicit rather than being inferred from an input.

### Flash Attention as the primary lever

The measured prefill bottleneck was not sufficiently attention-dominated for a
Windows Flash Attention migration to justify its compatibility cost. The R10
result comes from verified routing, generation priming, and bounded
compilation, not from claiming Flash Attention as a universal solution.

### Expanding the allowlist from holdout observations

Adding shapes just because they appear in the frozen holdout would invalidate
the evaluation. Coverage may be expanded only from a separate tuning workload,
followed by a fresh holdout and equivalent correctness/operational gates.

## Future directions

Investigate eager prefill, incremental codec decoding, AR/codec overlap, and
adaptive scheduling as independent experiments. Each must state its invariant,
measure warm and cold behaviour separately, test cancellation and cache/memory
boundaries, and keep evaluation data out of design selection.
