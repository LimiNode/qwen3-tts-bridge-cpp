# Research Reports

This directory separates concise project-facing results from the detailed,
reproducible evidence retained under `docs/benchmark-artifacts/`.

- [RTX 4090 frequency R10 report](frequency-r10-rtx4090.md): measured scope,
  results, operational gates, and a carefully bounded external comparison.
- [Representative corpus v4](benchmark-corpus-v4.md): corpus purpose,
  construction, review process, and frozen-holdout rules.
- [Optimization decisions](optimization-decisions.md): accepted, rejected, and
  deferred performance approaches with their rationale.
- [Authoritative baseline, 2026-08-03](authoritative-baseline-2026-08-03.md):
  clean-worktree quality gates and stdio worker-handshake evidence before the
  next voice-clone runner changes.
- [Schema 5 provenance plan](schema-5-provenance-plan.md): actual-byte runtime
  evidence and migration rules for authoritative voice-clone candidates.
- [Technical-beta publishing](../technical-beta-publishing.md): sealed package
  replacement, dual-model relocated validation, and acceptance-evidence rules.
- [Technical-beta R2 acceptance](technical-beta-r2-acceptance.json): compact
  same-host relocated CustomVoice and Base natural-EOS evidence.

These reports describe a narrow internal configuration. They do not make
performance or compatibility claims for arbitrary models, drivers, CUDA stacks,
or GPUs.
