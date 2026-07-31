# RTX 4090 Tail-Case Matrices

Both matrices use only frozen discovery records, the r8 safety profile, and
20 explicit deterministic seeds (`20260731` through `20260750`). Each case
was measured in isolated fresh processes and in one long-lived warmed engine.
The runtime measurement holdout was not read.

## `v4-b08-051`: 60-Second Safety Cap

`v4-b08-051-duration-cap-matrix-20.json` shows the same outcome in both
lifecycle modes: 19/20 EOS and 1/20 `safety_duration_limit`. Seed `20260746`
reaches exactly 60.0 audio seconds in both modes.

The cap therefore protects a real stochastic duration tail; it is not yet a
transparent product limit for this record. Do not increase it without a
separate product-policy decision and a broader tail analysis.

The long-lived `v4-b08-051` measurements also show a persistent slower
first-chunk state (TTFA p95 635.435 ms versus fresh p95 378.730 ms). This is
diagnostic evidence, not a new baseline metric, and should be investigated
before using this record to compare TTFA configurations.

## `v4-b10-182`: TTFA Outlier

`v4-b10-182-ttfa-stall-matrix-20.json` reproduced no 850 ms stall:

- fresh-process TTFA p95/max: 373.148/380.396 ms;
- long-lived TTFA p95/max: 360.424/363.440 ms;
- 40/40 EOS outcomes.

The original discovery maximum is therefore not reproducible in this focused
matrix. It remains a recorded one-off system-level tail until more evidence
attributes it to a concrete cause.
