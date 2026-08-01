# RTX 4090 Frequency Allowlist R9

This directory records the candidate, its same-wheel A/B, and one frozen
measurement holdout for an exact compiled-prefill allowlist. It does not
authorize padded bucketing or a universal runtime default.

## Candidate

`candidate-manifest.json` derives six exact lengths from the completed r8
discovery records and the frozen `representative-v4-r6-candidate` discovery
split:

```text
18, 19, 20, 26, 27, 29
```

The six shapes cover 304 of 1,500 discovery prompts (20.2667%). The former
allowlist covered 158 of 1,500 (10.5333%). The candidate generator records the
hashes of both inputs and preserves one representative prompt per exact shape.

## Correctness

`eager-vs-compiled-prefill-gate.json` proves zero eager-versus-compiled
prefill drift for every selected shape under `strict_bf16_sdpa_v1`.

`generation-prime-semantic-matrix.json` separates the generation-prime
experiment from the prefill result. It runs the six selected shapes in separate
eager and compiled processes with fixed request seeds:

- sampling: five seeds per shape;
- greedy: three seeds per shape;
- prime disabled: a codec-trace mismatch is observed in both decode modes;
- prime enabled: every eager/compiled codec trace and terminal EOS result is
  identical in both decode modes.

The prime is an internal, full natural-EOS generation performed before worker
readiness. It preserves Python, NumPy, Torch CPU, and CUDA RNG state, has the
ordinary 60-second generation safety limit, and fails worker startup if it does
not reach EOS. It deliberately does not use the partial-generation reset: that
path was already measured and does not establish first-request parity.

## Same-Wheel A/B

`same-wheel-ab/summary.json` compares the legacy six-shape allowlist and the
candidate with the same FasterQwen source bundle, runtime, speaker, seed, and
55-record stratified fixture. Both profiles completed every row at EOS with
their exact route contracts.

- The five newly compiled shapes (`18, 19, 20, 26, 27`) reduced mean first
  audio from 350.491 ms to 237.762 ms (-112.729 ms) and mean completion from
  1455.678 ms to 1261.151 ms (-194.526 ms).
- The shared shape (`29`) was neutral within this fixture: +2.460 ms mean
  first audio and +2.289 ms mean completion.
- The five removed legacy shapes deliberately route eagerly under the candidate
  and are slower on the artificial balanced fixture. This is a routing tradeoff,
  not an aggregate product-latency claim.
- Candidate startup includes a 824.996 ms internal natural-EOS generation
  prime. Its recorded RNG fingerprint is unchanged before and after the prime.

## Frozen Holdout

`holdout-policy.json` freezes the candidate profile, corpus SHA, seed, and
no-padding constraint. `holdout-run/` records the only measurement holdout run;
`holdout-validation.json` is the fail-closed acceptance result.

`runtime-policy-v2.json` seals that evidence to the worker source bundle,
FasterQwen source/module bundle, Python/Torch/CUDA/Triton versions, the exact
same-wheel A/B summary, and the tool source hashes. The original Triton wheel
is not retained in the local pip cache, so the policy records a hash of the
installed `triton-windows` distribution bundle and explicitly marks the wheel
artifact as unavailable rather than claiming an unverified wheel hash.

The run used 500 held-out prompts on RTX 4090 with the exact candidate
allowlist. All 500 requests completed at EOS, all provenance and seed checks
passed, and there were zero route-contract failures. The six compiled shapes
covered 99 of 500 holdout prompts (19.8%); the remaining 401 intentionally used
the eager fallback without compile-on-miss.

Observed end-to-end distributions:

```text
first audio: mean 368.738 ms, p50 398.740 ms, p95 428.327 ms
completion:  mean 3234.457 ms, p50 2614.533 ms, p95 8772.910 ms
inverse RTF: mean 2.689, p50 2.712, p95 3.004
```

This is a validated research configuration for the pinned RTX 4090 runtime,
not evidence for other GPUs, model families, padded buckets, or an unmeasured
allowlist expansion.

## Route Breakdown

`holdout-route-report.json` separates the observed holdout routes. The 99
compiled requests had mean first audio of 250.067 ms (p95 264.258 ms), while
the 401 eager requests had mean first audio of 398.036 ms (p95 433.175 ms).
It also reports per-length, category, and language distributions.

For context only, the former allowlist would cover 50 of the 500 already
revealed holdout records (10.0%). This is a counterfactual routing count, not a
new measurement and not input to another allowlist selection.

Unknown shapes are accepted and routed to eager execution. The profile is
fail-closed only against unexpected compilation: `compile-on-miss` remains
disabled.
