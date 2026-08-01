# Frequency Exact-Allowlist R10 Evidence

This directory contains reproducible, privacy-minimized R10 frequency
exact-allowlist evidence. The older evidence is retained as historical research.
The generation-prime evidence below is the candidate basis for the narrowly
scoped RTX 4090 48GB internal opt-in profile. It does not change the default
runtime profile or authorize broader hardware rollout.

The measured configuration used the exact compiled lengths `18, 19, 20, 26,
27, 29`, compiled chunk schedule `8, 8, 12`, eager schedule `8`, and an eager
route for unknown lengths. Padded buckets and the `5, 8, 12` scheduler are not
part of this evidence.

## Generation-Prime Internal Candidate

- `python-launcher-soak-r504.summary.json` and
  `python-launcher-soak-r504.validation.json` record a launcher-mediated,
  504-operation Python soak. It completed 396 requests, cancelled 108 requests
  across all three cancellation phases, exercised all six compiled lengths plus
  three eager holdouts, and observed exactly six compiled cache entries.
- `cpp-api-soak-r250-prime.sanitized.json`, its metric JSONL, sanitization
  sidecar, and validation record a 250-operation public C++ API soak. It
  completed 225 requests, cancelled 25 requests, observed six cache entries,
  and uses embedded request telemetry as its worker-metric source.

Both captures were run against the pinned generation-prime worker source and
FasterQwen module bundles named in `evidence-index.json` and the runtime policy.
Raw reports remain local and are intentionally not committed.

The sealed policy additionally verifies every non-transient file in the selected
model directory before worker startup. Internal profiles reject arbitrary
launcher arguments, and preflight parses the exact worker argv with the worker's
own parser before comparing the resulting configuration with the policy.
`faster-qwen3-tts-a0532ff.bundle` and
its source manifest preserve the clean source tree whose Python module bundle
matches the capture. The original Triton wheel was absent from the local pip
cache at sealing time; the policy therefore does not claim an unverifiable wheel
hash. It pins both the installed distribution `RECORD` and SHA-256 values for
the complete installed Triton file set.

## Latency Scope

The operational soak is a stability gate, not a latency SLA. Across its mixed
completed requests, first audio was `384.5 ms` median, `1073.9 ms` p95, and
`1197.2 ms` maximum. The three eager holdout scenarios each measured p95 first
audio between `1174.2 ms` and `1175.9 ms`. Do not present compiled allowlist
latency as a guarantee for arbitrary eager text lengths.

`python-launcher-soak-r63.*` is retained as a supplementary launcher smoke. It
does not authorize the profile and is not pinned by the runtime policy.

`python-sealing-smoke-r63.*` is the post-sealing smoke. It passed 36 completed
requests and 27 cancellations, covering every compiled/eager scenario and all
three cancellation phases under the pinned model manifest and clean FasterQwen
source.

`python-final-sealing-smoke-r63.*` repeats that gate after the final fail-closed
argv and complete-content-manifest changes. It records a clean bridge commit and
clean FasterQwen source: 36 completed requests, 27 cancellations, six cache
entries, zero allocated CUDA-memory growth, and no validation failures.

## Historical Research

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
file hashes and retained-file hashes are in `evidence-index.json`. Historical
files do not authorize the current profile; only the generation-prime candidate
files are pinned by `runtime-policy-v4-rtx4090-48gb-internal-opt-in.json`.

## Revalidation

Run the generation-prime C++ evidence validator with the canonical JSONL
sidecar:

```powershell
.venv\Scripts\python.exe scripts\validate_cpp_api_soak.py `
  docs\benchmark-artifacts\rtx4090-2026-08-01\frequency-exact-allowlist-operational-r10\cpp-api-soak-r250-prime.sanitized.json `
  --worker-metrics docs\benchmark-artifacts\rtx4090-2026-08-01\frequency-exact-allowlist-operational-r10\cpp-api-soak-r250-prime.metrics.jsonl `
  --manifest docs\benchmark-artifacts\rtx4090-2026-08-01\frequency-exact-allowlist-operational-r10\cpp-api-soak-manifest.jsonl `
  --expected-requests 250 `
  --expected-cancelled 25 `
  --expected-cache-entries 6
```

Verify the actual model directory before launching the internal profile:

```powershell
.venv\Scripts\python.exe scripts\model_runtime_manifest.py verify `
  --model-path models\Qwen3-TTS-12Hz-0.6B-CustomVoice `
  --manifest docs\benchmark-artifacts\rtx4090-2026-08-01\frequency-exact-allowlist-operational-r10\model-runtime-manifest.json
```
