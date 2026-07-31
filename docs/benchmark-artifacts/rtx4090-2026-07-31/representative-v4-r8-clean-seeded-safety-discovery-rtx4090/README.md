# RTX 4090 Clean Seeded Safety Discovery

This is the authoritative discovery-only baseline for the frozen 1,500-record
`representative-v4-r6-candidate` discovery split. The runtime measurement
holdout was not read.

## Provenance

- Bridge commit: `e8115103e3201413f10d62e6013d69badbcbfe5e`
- Bridge tracked tree: clean
- FasterQwen commit: `58b063742f7707972ddc74a433a7f205ec471e65`
- FasterQwen tracked tree: clean
- The manifest pins both source-bundle hashes, Git trees, the profile SHA, and
  the Triton Windows wheel SHA.
- Seed contract: `20260731`, `request_id` mode, with every record carrying its
  exact request ID and derived request seed.

## Result

`validation-v2.json` is the acceptance report. It passed all provenance,
seed, profile-limit, generation, and exact-route checks:

- 1,500/1,500 execution completions and EOS terminal outcomes;
- zero safety-duration, max-sequence, max-token, route, fallback, eviction, or
  Dynamo-graph violations;
- 158 exact compiled routes with `8/8/12`; 1,342 eager routes with `8`;
- TTFA p50/p95/p99: 363.374/372.592/377.538 ms; one maximum of 853.971 ms.

The preceding r7 run remains valid pre-commit working-tree research evidence,
but not an authoritative baseline.

## Padding Research

`real-shape-summary-v2.json` supplies the real discovery histogram.
`padded-bucket-16-32-research-authorization-v2.json` authorizes only a
research implementation of actual lengths `16..32 -> 32`. It does not enable
a runtime route, release profile, or holdout experiment.
