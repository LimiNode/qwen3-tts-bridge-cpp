# RTX 4090 Frequency Allowlist R9

This directory records discovery-only evidence for an exact compiled-prefill
allowlist candidate. It does not authorize a runtime profile, padded bucketing,
or use of the frozen measurement holdout.

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

## Remaining Gates

Before a holdout run, the candidate still requires a same-wheel old-versus-new
A/B measurement with startup cost, first/steady TTFA, cache/Dynamo deltas, and
memory telemetry. The A/B result must then freeze the policy manifest. Only the
frozen policy may be evaluated on the measurement holdout.
