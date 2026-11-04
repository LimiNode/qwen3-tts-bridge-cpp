# `src/qwen_tts_bridge/` — bridge domains

This directory contains the stable C++ bridge API. Public umbrella headers
should be the connection points between domains; use local quoted includes
inside those umbrellas. Keep implementation-private helpers in their owning
subdomain rather than adding `utils` or generic `helpers` directories.

Umbrellas are dependency boundaries, not only convenience aggregators. An
umbrella includes lower-level or sibling umbrellas first and then its own leaf
headers. Public umbrellas are independently compilable. Internal leaves may
obtain cross-domain declarations transitively from the enclosing umbrella.
Keep standard-library includes in leaves, avoid duplicate cross-domain
includes, and do not introduce umbrella cycles. When context is needed, a
per-source domain-owned translation unit supplies the umbrella before including
exactly one implementation source. Both paths are library-qualified, without
`../`. The implementation starts with its own local header, or the existing
private header for source-only splits. Standalone/compatibility entry headers
can supply the context directly; do not add unnecessary wrappers.
Public consumers should include the domain umbrella instead of
reaching into internal leaves.

`QwenTtsClient` is async-first and owns request callbacks. `WorkerSession`
owns process/session state. `ITransport` moves bytes only. The protocol layer
validates framing and control messages without importing process or model code.
No mutex may be held while invoking an application callback.

Do not silently change protocol semantics, terminal-state rules, or callback
ordering. Add a focused regression test for every lifecycle or failure-mode
change. Native code is opt-in and must not leak qwentts.cpp types into the
normal public bridge surface.

For quality review, apply [`docs/ai-code-quality.md`](../../docs/ai-code-quality.md):
reuse existing owners, avoid parallel implementations, and justify any new
abstraction in the PR description.
