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

`v4-b01-001-parity-v1.json` is the original real RTX 4090 result for an 18-token prompt
padded with 14 leading positions. It rejects the mechanism before any holdout:

- first-step logits were not exact (`max_abs=0.3125`);
- real-token KV suffixes were not exact (`max_abs=0.2734375`);
- greedy and fixed-seed sampling codec traces differed;
- RNG state and terminal state happened to match, but cannot compensate for
  semantic divergence.

`v4-b01-001-parity.json` is schema v2 of the same result. It separates direct
observations from unproven mask, position-ID, RoPE, and generation-state
hypotheses. The generation runs were limited to eight frames, so equal terminal
states are recorded only as `max_new_tokens`-limited, not as natural EOS parity.

`runtime-acceptance.json` is the fail-closed decision generated from that
report. It prohibits a padded holdout and release route. The likely source is
the interaction of left padding with the Qwen attention/position execution;
this artifact intentionally does not claim a more specific root cause without
separate evidence.

The padded 16..32-to-32 path is therefore deferred. Reopening it requires a
new mechanism and a fresh complete exact-parity report, not a relaxed
tolerance.

## External Source Archive

The corresponding FasterQwen implementation is also published at
`LimiNode/faster-qwen3-tts`, branch `research/padded-prefill-16-32-to-32`,
commit `b70175f531e375f01d4206b605afc2500c2db94e`. This directory retains an
independent patch and incremental Git bundle from base `58b063742f7707972ddc74a433a7f205ec471e65`.
See `faster-qwen-padded-prefill-provenance-v1.json` for the exact hashes.
