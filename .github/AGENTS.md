# CI and packaging

Workflows must build and test the same targets contributors are asked to run.
Keep native qwentts.cpp jobs, Python worker checks, CTest, PowerShell parser
checks, and packaging smoke tests fail-closed. A workflow that only parses a
script or compiles an unused target is not evidence that the feature works.

When changing a submodule pin, verify that the commit is reachable from its
remote before pushing the parent repository. Do not add generated models,
runtime DLLs, or benchmark artifacts to CI caches committed to the repository.

Read the root [`AGENTS.md`](../AGENTS.md) and
[`docs/ai-code-quality.md`](../docs/ai-code-quality.md) before expanding a
workflow; prefer a small reusable step over copy-pasted job logic.
