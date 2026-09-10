# AI-assisted code quality review (2026-09-09)

This review applies the heuristics from [“Опухший C++ код”](https://habr.com/ru/companies/pvs-studio/articles/1072264/)
to the bridge at commit `1f2affffe88f772707bae25218e276ba4db8f1ca` (`main`
after #74 and #75). It looks for duplicated policy, dead or
redundant branches, unjustified abstractions, misleading exception contracts,
and growth that makes review or analysis harder. It is a maintainability review,
not a replacement for compiler warnings, CTest, or hardware acceptance.

## Findings

### Warning: several historical orchestration units are very large

The largest current units are `worker/src/qwen_tts_bridge_worker/engine/qwen_engine.py`
(2686 lines), `examples/qwen_tts_play.cpp` (1944),
`examples/qwen_tts_latency_benchmark.cpp` (1703), and
`worker/src/qwen_tts_bridge_worker/server/stdio_server.py` (1276). They contain
real lifecycle/model or benchmark state machines, so line count alone is not a
bug. They are nevertheless high-risk places for copy-paste growth.

Rule for follow-up work: do not append another policy branch to these files
when a cohesive domain module can own it. Extract only a real boundary (for
example profile policy, benchmark evidence, or playback), preserve behavior,
and add a focused regression in the same change.

### Warning: profile policy has two executable owners

The CMP profile values are intentionally applied in both the PowerShell
launcher and Python worker CLI: the launcher must export decoder environment
variables, while the worker must configure its model before construction. This
is a legitimate cross-process boundary, but it creates drift risk. Existing
tests cover each side separately; they do not compare the two tables.

Do not add a third copy. A future hardening change should expose a small
machine-readable profile contract or a cross-check test. Until then, any profile
change must update the launcher, worker, documentation, and their tests in one
logical change.

### Warning: benchmark environment setup is repeated across scripts

Several acceptance scripts set the same `PYTHONNOUSERSITE` and
`QTB_FASTER_*` variables. The repetition is partly deliberate because each
script is independently runnable and must fail closed. It should not grow into
another profile implementation. Prefer a shared environment-composition helper
when the next script change needs the same policy, and test restoration of the
caller's environment.

## Checks that passed

- No production `assert()` gate was found in the reviewed C++ paths.
- No explicit `throw` expression was found in the selected `noexcept` bodies.
  This narrow source review does not by itself prove a `noexcept` contract:
  allocations, strings, filesystem operations, and callbacks may still throw.
  Each `noexcept` change must instead establish that no exception can escape
  the function, including at C ABI and callback boundaries.
- Native EOS, capacity, cancellation, and ABI failures are represented by
  explicit results rather than silent success.
- Native/Python duplication in the acceptance harness is intentional: the
  backends have different capabilities and finish evidence, so merging their
  code would hide rather than remove a semantic distinction.
- No new generic `utils`/`helpers` dumping ground or speculative dependency was
  introduced by this batch.

## Review decision

No correctness blocker was found in this pass. The three items above are
maintainability warnings and are now recorded as constraints for future PRs.
The normative checklist is [`docs/ai-code-quality.md`](../ai-code-quality.md);
module-specific routing is in the nearest `AGENTS.md`.
