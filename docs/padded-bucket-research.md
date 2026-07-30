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

`scripts/optimize_padded_buckets_v2.py` produces the required candidate
fields. It may leave sparse leading, trailing, or internal observed lengths on
the eager path; it does not force a prefix of the histogram into compiled
buckets. Startup and runtime cost fields remain estimates until measured on the
actual worker.

## Mechanism Gate and First Prototype

`scripts/evaluate_padded_bucket_mechanism_gate.py` owns the separate mechanism
decision. It requires a completed human review and at least 1,500 valid route
records with real representation in the approved actual-length range. It can
authorize exactly one research implementation:

```text
actual prefill length 16..32 -> padded compiled shape 32
```

The prototype must prove attention-mask and position-ID correctness, eager
versus padded semantic parity for greedy and sampling paths, RNG neutrality,
trace and termination equality, PCM duration/quality, playback reserve,
single-entry cache behavior, no dynamic compilation, and cancel/reset state
isolation. The frozen holdout remains unused until that proof is complete.

Neither this research path nor a positive holdout changes a product default,
the release profile, or the deferred `5->8->12` scheduler experiment.
