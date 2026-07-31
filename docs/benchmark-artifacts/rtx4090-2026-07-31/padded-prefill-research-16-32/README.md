# Padded Prefill Research: Negative Result

This directory records the only implementation experiment authorized by
`representative-v4-r8-clean-seeded-safety-discovery-rtx4090`:

```text
actual prefill length 16..31 -> left-pad to 32 -> eager explicit-mask prefill
```

The implementation was deliberately isolated in the FasterQwen worktree
`research/padded-prefill-16-32-to-32` at
`b70175f531e375f01d4206b605afc2500c2db94e`. It never changes the bridge
runtime profile, the exact compiled allowlist, or a released worker artifact.

`v4-b01-001-parity.json` is a real RTX 4090 result for an 18-token prompt
padded with 14 leading positions. It rejects the mechanism before any holdout:

- first-step logits were not exact (`max_abs=0.3125`);
- real-token KV suffixes were not exact (`max_abs=0.2734375`);
- greedy and fixed-seed sampling codec traces differed;
- RNG state and terminal state happened to match, but cannot compensate for
  semantic divergence.

`runtime-acceptance.json` is the fail-closed decision generated from that
report. It prohibits a padded holdout and release route. The likely source is
the interaction of left padding with the Qwen attention/position execution;
this artifact intentionally does not claim a more specific root cause without
separate evidence.

The padded 16..32-to-32 path is therefore deferred. Reopening it requires a
new mechanism and a fresh complete exact-parity report, not a relaxed
tolerance.
