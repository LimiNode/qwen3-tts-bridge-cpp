# Agent entry point

The repository-wide instructions are in [`AGENTS.md`](AGENTS.md). Read the
module-level `AGENTS.md` nearest to the files being changed; those documents
own detailed contracts for source, worker, tests, scripts, CI, dependencies,
and research records.

The anti-generated-code policy is in
[`docs/ai-code-quality.md`](docs/ai-code-quality.md). It is normative: keep
changes small, reuse existing owners, remove duplication, and provide evidence
for behavior and performance claims.

Do not commit model weights, virtual environments, generated build output,
WAV captures, or machine-local acceptance artifacts.
