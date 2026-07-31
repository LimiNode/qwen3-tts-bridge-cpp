# RTX 4090 Seeded Safety Discovery

This is a real, discovery-only RTX 4090 run over the frozen 1,500-record
`representative-v4-r6-candidate` discovery split. The runtime measurement
holdout was not read.

## Contract

- Profile: `rtx4090-faster-customvoice-route-aware-scheduler-release-safety-v1-experimental`
- Seed: `20260731`, derived per request ID
- Product safety cap: 60 generated PCM seconds, surfaced as
  `resource_error/safety_duration_limit`, never as `completed`
- Route policy: exact compiled shapes `29,30,32,33,34,35` use `8/8/12`;
  all other shapes use eager fixed `8`.

## Result

`validation-v1.json` is the authoritative acceptance report. It confirms:

- 1,500/1,500 execution completions;
- 1,500/1,500 `generation_outcome=eos`;
- no `max_seq_len`, safety-duration, cache-eviction, compile-on-request, or
  fallback route event;
- complete exact route-contract coverage.

The previous unseeded discovery artifact remains historical evidence only. Its
single `max_seq_len` row (`v4-b03-096`) is not a valid performance baseline.
The fresh-process diagnostics in the sibling `max-seq-v4-b03-096-initial`
directory reproduce deterministic EOS for the seeded request.

## Padded Buckets

`real-shape-summary-v1.json` and `padded-bucket-offline-candidates-v1.json`
are offline research artifacts. They do not change the runtime. The broad
4--6 graph candidates fail at least one coverage, padding, or bootstrap
stability threshold. The `16..32 -> 32` mechanism gate is recorded separately
and remains fail-closed until an explicit padding implementation has semantic
mask/rope parity evidence.
