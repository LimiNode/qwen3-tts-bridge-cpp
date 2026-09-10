# Python tests

Use the installed worker package or the test runner's `PYTHONPATH`; do not
mutate `sys.path` inside tests. Keep model-free tests deterministic and isolate
CUDA/model acceptance from unit tests. Shared fixtures should be extracted
only when the setup and semantics are genuinely identical.

When a test asserts a script's source text, explain why an executable seam is
not available. Prefer invoking a parser, mock worker, or deterministic helper
when one exists.
