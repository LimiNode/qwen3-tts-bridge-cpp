# Frequency Exact-Allowlist R10 Evidence

This directory contains the reproducible, privacy-minimized evidence retained
from the R10 frequency exact-allowlist operational experiment. It is historical
research evidence, not an authorization to enable an internal runtime profile.

The measured configuration used the exact compiled lengths `18, 19, 20, 26,
27, 29`, compiled chunk schedule `8, 8, 12`, eager schedule `8`, and an eager
route for unknown lengths. Padded buckets and the `5, 8, 12` scheduler are not
part of this evidence.

## Included Evidence

- `python-operational-soak-final.summary.json` records a sanitized summary of
  the 504-operation Python soak: 396 completed and 108 cancelled requests.
- `cpp-api-soak-r250.sanitized.json` and `cpp-api-soak-r250.metrics.jsonl`
  retain the fields required to validate the 250-operation C++ API soak.
  Original request IDs are replaced by benchmark ordinals and the worker PID is
  replaced by the constant `1`.
- `cpp-api-soak-r250.validation.json` is produced from the two sanitized files
  and `cpp-api-soak-manifest.jsonl`; it records 225 completions, 25
  cancellations, six cache entries, and a single synthetic worker identity.
- `offline-holdout-report.json` is descriptive only. It breaks the frozen
  500-row holdout down by route, exact length, category, and language. It must
  not be used to retune the allowlist.

Raw stderr, complete per-request Python reports, process IDs, session IDs,
absolute paths, and runtime request text are intentionally absent. The source
file hashes and retained-file hashes are in `evidence-index.json`.

## Revalidation

Run the C++ evidence validator with the canonical JSONL sidecar:

```powershell
.venv\Scripts\python.exe scripts\validate_cpp_api_soak.py `
  docs\benchmark-artifacts\rtx4090-2026-08-01\frequency-exact-allowlist-operational-r10\cpp-api-soak-r250.sanitized.json `
  --worker-metrics docs\benchmark-artifacts\rtx4090-2026-08-01\frequency-exact-allowlist-operational-r10\cpp-api-soak-r250.metrics.jsonl `
  --manifest docs\benchmark-artifacts\rtx4090-2026-08-01\frequency-exact-allowlist-operational-r10\cpp-api-soak-manifest.jsonl `
  --expected-requests 250 `
  --expected-cancelled 25 `
  --expected-cache-entries 6
```
