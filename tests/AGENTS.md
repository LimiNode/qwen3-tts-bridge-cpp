# `tests/` — regression and acceptance tests

Tests must exercise observable behavior and failure modes. Prefer deterministic
fixtures and the mock worker for protocol/lifecycle tests; keep real-model and
GPU acceptance artifacts outside the repository.

Every new C++ test must be registered in CMake/CTest and run locally at the
narrowest relevant target. Python tests under `tests/python/` must be included
in the normal Python test runner and follow `tests/python/AGENTS.md`.
Source-text assertions are allowed for PowerShell or packaging contracts only
when no executable seam exists. For a performance or quality claim, retain
workload, seed, hardware, runtime revisions, and raw metrics in `docs/reports/`
or an external artifact location.

Do not duplicate a test body for a new profile. Parameterize genuinely identical
cases, and keep intentionally different terminal/error contracts explicit.
