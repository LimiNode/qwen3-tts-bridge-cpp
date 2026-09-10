# `src/qwen_tts_bridge/` ? bridge domains

This directory contains the stable C++ bridge API. Public umbrella headers
should be the connection points between domains; use local quoted includes
inside those umbrellas. Keep implementation-private helpers in their owning
subdomain rather than adding `utils` or generic `helpers` directories.

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
