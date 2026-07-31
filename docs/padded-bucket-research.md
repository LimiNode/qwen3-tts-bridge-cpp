# Padded Bucket Research Gates

Padded prefill buckets are a research path. They are not a release-profile
optimization and do not modify the existing exact allowlist.

## Exact-Length Gate

`scripts/summarize_route_coverage.py` owns exact-length research. Its
concentration metric is meaningful only for deciding whether additional exact
lengths deserve investigation. It must not authorize a padded bucket.

## Distribution Research Gate

`scripts/evaluate_padded_bucket_gate.py` owns the constrained distribution-plan
decision. It does not authorize a runtime implementation.
It requires all of the following:

- a completed human review of the frozen corpus sample;
- at least 1,500 valid synthetic route-discovery records;
- synthetic evidence only, never a release claim;
- constrained Pareto candidate coverage of at least 85 percent;
- at most six compiled graphs;
- mean, p95, and maximum padding at most 6, 12, and 16 frames;
- maximum padding ratio at most 40 percent;
- bootstrap ceiling stability of at least 80 percent within two frames.

The gate also verifies a provenance chain: the candidate input SHA must equal
the supplied route-summary SHA, and route summary, audit, manual review, and
candidate must agree on corpus, generator/config, and runtime-profile identity.

`scripts/optimize_padded_buckets_v2.py` produces the required candidate
fields. It may leave sparse leading, trailing, or internal observed lengths on
the eager path; it does not force a prefix of the histogram into compiled
buckets. Startup and runtime cost fields remain estimates until measured on the
actual worker.

## Research Authorization and Runtime Acceptance

`scripts/evaluate_qwen_padded_bucket_prototype.py` is the research
authorization gate. It uses a clean, accepted discovery baseline and its real
shape histogram. It can authorize the implementation work below, but never a
runtime route, holdout run, or release profile. It deliberately does not
require a padding implementation to exist.

`scripts/evaluate_padded_bucket_mechanism_gate.py` owns the separate mechanism
decision. It requires a completed human review and at least 1,500 valid route
records with real representation in the approved actual-length range. The
range needs at least 100 requests across lower, middle, and upper control
groups, including large-padding `16/17` and zero-padding `31/32` controls. It
can authorize exactly one research implementation:

```text
actual prefill length 16..32 -> padded compiled shape 32
```

After implementation,
`scripts/validate_qwen_padded_bucket_runtime_acceptance.py` consumes the
research authorization and a semantic parity report. It requires attention
mask, position-ID, RoPE, KV-cache, first-step logits, generation state,
greedy trace, seeded sampling, terminal outcome, and RNG-neutrality checks.
Only this second gate can authorize one frozen-holdout run.

## RTX 4090 Result: 16..31 to 32 Rejected

The authorized eager explicit-mask prototype was implemented in an isolated
FasterQwen research worktree and evaluated against an 18-token real discovery
prompt on RTX 4090. The first semantic parity report is stored in
`docs/benchmark-artifacts/rtx4090-2026-07-31/padded-prefill-research-16-32/`.
It failed exact first-logit, real-token KV, greedy codec, and fixed-seed codec
checks. The runtime-acceptance gate therefore rejects both a holdout and a
release route.

Do not relax the exact checks to revive this prototype. The existing
exact-length allowlist remains the only accepted accelerated prefill route.

Neither this research path nor a positive holdout changes a product default,
the release profile, or the deferred `5->8->12` scheduler experiment.
