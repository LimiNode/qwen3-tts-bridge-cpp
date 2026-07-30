# Route-Aware Canary Telemetry

The route-aware scheduler remains an internal experimental opt-in. Canary
telemetry is one privacy-safe JSONL object per terminal request. It must never
contain text, instruction, speaker, request ID, session ID, model path, or
application labels.

The current canary-v2.1 wire schema uses `schema_version: 3`. Every record has
an anonymous `runtime_profile_id`, a terminal `request_outcome`, and whether a
prefill route was decided. Valid outcomes are `completed`,
`cancelled_before_audio`, `cancelled_after_audio`, and `failed`.

```json
{
  "schema_version": 3,
  "runtime_profile_id": "rtx4090-cv06-bf16-sdpa-strict-v1-9d2a61ef",
  "evidence_source": "synthetic_proxy",
  "request_outcome": "completed",
  "route_decision_made": true,
  "talker_prefill_length": 32,
  "prefill_shape_policy": "compiled_allowlist",
  "prefill_backend_used": "compile_reduce_overhead",
  "selected_chunk_schedule": [8, 8, 12],
  "prefill_cache_hit": true,
  "prefill_compile_attempted": false,
  "prefill_compile_fallback": false,
  "first_audio_ms": 250.0,
  "completed_ms": 2800.0,
  "inverse_rtf": 2.9
}
```

`completed` and `cancelled_after_audio` require `route_decision_made=true`.
Requests cancelled before route selection use `route_decision_made=false` and
omit every route and latency field. A `completed` record requires all three
latency fields; they must be finite, non-negative, and satisfy
`completed_ms >= first_audio_ms`. Latency is never calculated for cancellations
or failures.

For route-decided requests, the aggregator accepts only these contracts:

```text
allowlisted length: compiled_allowlist / compile_reduce_overhead / [8,8,12]
                    cache_hit=true, compile_attempted=false, fallback=false
unknown length:     eager_unknown / eager / [8]
                    cache_hit=false, compile_attempted=false, fallback=false
```

Coverage counts every route-decided request, regardless of outcome. Invalid
route records are excluded from coverage and make `input_valid=false`.
`runtime_profile_id` is an anonymous fingerprint of the bridge revision,
FasterQwen wheel SHA, Qwen revision, model revision, Torch/CUDA runtime,
allowlist, and scheduler. A report cannot mix profiles.

`evidence_source` is either `synthetic_proxy` or `internal_real_traffic`.
Synthetic proxy evidence is useful for reproducibility, protocol behaviour, and
shape discovery, but it cannot authorize a production rollout or padded-bucket
investigation. A production gate must pass
`--require-evidence-source internal_real_traffic`.

Before a canary, generate pinned manifests from the internal RTX 4090 profile:

```powershell
python scripts/create_route_aware_canary_manifests.py `
  --profile config/rtx4090-faster-customvoice-route-aware-scheduler-release-experimental.json `
  --runtime-profile-id rtx4090-cv06-bf16-sdpa-strict-v1-9d2a61ef `
  --faster-wheel-sha256 <wheel-sha256> `
  --qwen-commit <qwen-commit> `
  --model-revision Qwen3-TTS-12Hz-0.6B-CustomVoice `
  --torch-version <torch-version> `
  --cuda-version <cuda-version> `
  --output-directory canary-manifests
```

The generator verifies the six exact lengths, compiled `8,8,12`, eager fixed
`8`, eager unknown-shape fallback, disabled compile-on-miss, and required
precompiled entries. It writes an allowlist manifest and a runtime-profile
manifest which pins its SHA-256. Start the worker with both manifest paths.
The worker validates its active runtime against those manifests before serving
requests and emits one `canary_runtime_provenance` startup metric containing
only the profile ID, bridge commit, wheel SHA-256, and allowlist SHA-256.

Capture the worker's local `qtb_metric` stderr diagnostics with the bridge
transport's `stderr_handler`, then convert that local diagnostic file before
sharing or aggregating anything. The exporter correlates request IDs only in
memory and emits no ID or text in its JSONL output:

```powershell
python scripts/export_route_aware_canary_telemetry.py worker-stderr.log `
  --runtime-profile-manifest canary-manifests/runtime-profile-manifest.json `
  --compiled-allowlist-manifest canary-manifests/compiled-allowlist-manifest.json `
  --evidence-source synthetic_proxy `
  --output canary.jsonl `
  --summary-output export-summary.json
```

The exporter is fail-closed. It requires exactly one worker provenance metric,
rejects duplicate/orphan/ignored request metrics, and requires
`accepted_request_count = terminal_request_count` at EOF. A live collection
tool may pass `--allow-open-requests` explicitly; release evidence must not.

When a Windows PowerShell native stderr redirection created a UTF-16,
line-wrapped capture, normalize only its valid metric objects before export:

```powershell
python scripts/extract_qtb_metrics.py worker-stderr-powershell.log `
  --output worker-metrics.log
```

The extractor validates each recovered JSON object and writes no diagnostics or
request data that was not already in a `qtb_metric` object.

Aggregate telemetry locally with:

```powershell
python scripts/summarize_route_coverage.py canary.jsonl `
  --runtime-profile-id rtx4090-cv06-bf16-sdpa-strict-v1-9d2a61ef `
  --runtime-profile-manifest canary-manifests/runtime-profile-manifest.json `
  --compiled-allowlist-manifest canary-manifests/compiled-allowlist-manifest.json `
  --compiled-length 29 --compiled-length 30 --compiled-length 32 `
  --compiled-length 33 --compiled-length 34 --compiled-length 35 `
  --output route-coverage-summary.json
```

The summary separately reports `input_valid`, `evidence_gate_pass`, and
`decision`, plus input SHA-256, validator commit/schema, and both manifest
SHA-256 values. It also reports route-separated completed latency summaries.
CI or a release script can require a specific decision:

```powershell
--require-decision evaluate_padded_bucket_correctness
```

The default evidence gate requires 500 route-decided requests. If exact
coverage is at least 90%, the decision is `keep_exact_allowlist`. Below 90%,
it additionally requires 100 unknown-shape requests and eligible unknown
lengths with at least 30 observations covering 80% of unknown traffic before
it can recommend `evaluate_padded_bucket_correctness`. The long tail is
reported separately and cannot permanently block the decision.

An evaluation recommendation authorizes a new correctness investigation only:
semantic/codec parity, PCM quality, playback reserve, compile/cache budget,
memory soak, and same-wheel RTX 4090 A/B. It never enables padded compilation
or `5 -> 8 -> 12` rollout.

`scripts/run_route_aware_operational_validation.py` exercises one persistent
worker with configured counts of completed requests, cancellation before first
audio, cancellation after first audio, and controlled request validation
failures. It uses protocol-v1 `shutdown.mode = cancel` and emits a raw worker
diagnostic capture for the exporter.
