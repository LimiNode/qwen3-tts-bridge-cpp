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

For acceptance and research records, read
[`docs/acceptance-evidence-contract.md`](docs/acceptance-evidence-contract.md).
Keep raw payloads in ignored `.tmp/base-acceptance/<run-id>/`, but commit the
small canonical receipt under `docs/reports/` and update the acceptance index.
User listening verdicts are not durable until the tracked receipt is updated;
never transfer them between model families, backends, or candidates.
