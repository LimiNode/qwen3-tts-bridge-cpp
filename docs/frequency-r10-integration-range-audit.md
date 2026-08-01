# Frequency R10 Integration Range Audit

This audit selects the minimal Frequency R10 runtime stack for integration into
`development-flash-attn-experiment`. It is intentionally performed before
sealing new evidence or enabling the internal profile.

## Compared Revisions

- Integration base: `040526476ca04f6291bf36cddb5d9fab0235d702`
  (`development-flash-attn-experiment`).
- Research head: `b26d53d171716ddf30f6fb2405b1d63f7fda0fe6`
  (`research/frequency-exact-allowlist`).
- `git range-diff` shows that the first ten Frequency R9 commits are
  patch-equivalent to commits already on the integration base. They are not
  selected again.
- The padded research-only branch has three additional commits not present on
  the Frequency branch. None is selected.

## New Research Commits

| Commit | Classification | Integration decision |
| --- | --- | --- |
| `d9da77f` | Operational schedule artifacts | Defer to evidence sealing. |
| `6ea8d10` | Runtime provenance in soak tooling | Defer to evidence sealing. |
| `1a2733d` | Detached Python soak runner | Defer to evidence sealing. |
| `0acd844` | Detached soak output isolation | Defer to evidence sealing. |
| `326dc83` | FasterQwen cooperative cancellation | Include in runtime PR. |
| `0826a9b` | Prompt running-request cancellation terminalization | Include in runtime PR. |
| `78f0d29` | Deterministic post-audio cancellation coverage | Include in runtime PR. |
| `e1129b8` | WDDM and schedule telemetry tooling | Defer to evidence sealing. |
| `117da58` | C++ API soak runner | Defer to evidence sealing. |
| `85bc7bc` | Windows CMake embedded-path fix | Include in runtime PR. |
| `0babe3b` | C++ cancelled-prefix contract | Include in runtime PR. |
| `943f21d` | Launcher generation-prime forwarding | Include in runtime PR. |
| `b26d53d` | R10 profile and measured artifacts | Supersede with integration-head evidence. |

## Runtime Selection

The runtime PR selects `326dc83`, `0826a9b`, `78f0d29`, `85bc7bc`,
`0babe3b`, and `943f21d`. Their tests are selected with the corresponding code.
The final integration commit will be revalidated against the existing R10
research evidence before new integration-head evidence is sealed.

## Excluded Experiment Classes

No selected commit adds a padded prefill runtime route, padded profile, or the
deferred `5 -> 8 -> 12` scheduler. The integration base contains pre-existing
offline padded-bucket research utilities and a separate `6 -> 8 -> 12`
experimental profile; neither is enabled, modified, or referenced by the
selected exact-allowlist runtime.

The selected runtime remains constrained to:

- compiled lengths `[18, 19, 20, 26, 27, 29]`;
- compiled chunk schedule `[8, 8, 12]`;
- eager chunk schedule `[8]`;
- eager unknown-shape routing with compile-on-miss disabled;
- the existing 60-second safety cap.

## Required Follow-Up Gates

1. Run no-CUDA configuration and CLI tests, the full Python gate, CTest, and
   `git diff --check` after the runtime integration.
2. Seal a sanitized C++ metrics sidecar and require every referenced evidence
   artifact to exist before accepting it.
3. Add the fail-closed internal-profile preflight on the final integration
   head, then validate that exact launcher path with a fresh-process smoke.
