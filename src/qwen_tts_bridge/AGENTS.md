# `src/qwen_tts_bridge/` — bridge domains

This directory contains the stable C++ bridge API. Public umbrella headers
should be the connection points between domains; use local quoted includes
inside those umbrellas. Keep implementation-private helpers in their owning
subdomain rather than adding `utils` or generic `helpers` directories.

Umbrellas are dependency boundaries, not only convenience aggregators. An
umbrella includes lower-level or sibling umbrellas first and then its own leaf
headers. Public umbrellas and documented compatibility entry points are
independently compilable. Internal leaves inherit the owning umbrella's
cross-domain context; they are not required to compile independently. Keep
standard-library includes in leaves and express cross-domain dependencies
through the corresponding umbrella; same-domain and implementation-private
dependencies may use local leaf includes. Do not introduce umbrella cycles.
Every real implementation is compiled directly and starts with its owning
domain/subdomain umbrella (or a documented compatibility umbrella), followed
by private implementation headers when needed.
First-party `.cpp` inclusion, wrapper translation units, forced includes, PCH,
and unity-build context are forbidden. Standalone/compatibility entry headers
remain explicit supported entry points.
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
