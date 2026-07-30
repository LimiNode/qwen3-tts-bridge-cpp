# Route-Aware Canary Telemetry

The route-aware scheduler remains an internal experimental opt-in. A canary may
record one JSON object per completed request only with this allowlisted schema:

```json
{
  "schema_version": 2,
  "runtime_profile_id": "rtx4090-cv06-bf16-sdpa-strict-v1-9d2a61ef",
  "talker_prefill_length": 32,
  "prefill_shape_policy": "compiled_allowlist",
  "prefill_backend_used": "compile_reduce_overhead",
  "selected_chunk_schedule": [8, 8, 12],
  "prefill_cache_hit": true,
  "prefill_compile_attempted": false,
  "prefill_compile_fallback": false
}
```

Optional numeric latency fields are `first_audio_ms`, `completed_ms`, and
`inverse_rtf`; they must be finite, `completed_ms` must not precede
`first_audio_ms`, and `inverse_rtf` must be positive. Never record text,
instruction, speaker, request ID, session ID, model path, or
application-specific labels in this stream.

`runtime_profile_id` is a stable anonymous fingerprint of the bridge revision,
FasterQwen wheel SHA, Qwen revision, model revision, Torch/CUDA runtime,
allowlist, and scheduler. It must change whenever any of those values changes.
The aggregator requires one explicit profile ID and rejects a mixed report.

Only these completed-request route contracts are accepted:

```text
allowlisted length: compiled_allowlist / compile_reduce_overhead / [8,8,12]
                    cache_hit=true, compile_attempted=false, fallback=false
unknown length:     eager_unknown / eager / [8]
                    cache_hit=false, compile_attempted=false, fallback=false
```

An invalid contract increments `invalid_route_count`, is excluded from all
coverage calculations, and makes the canary summary fail.

Aggregate local JSONL with:

```powershell
python scripts/summarize_route_coverage.py canary.jsonl `
  --runtime-profile-id rtx4090-cv06-bf16-sdpa-strict-v1-9d2a61ef `
  --compiled-length 29 --compiled-length 30 --compiled-length 32 `
  --compiled-length 33 --compiled-length 34 --compiled-length 35 `
  --output route-coverage-summary.json
```

The default evidence threshold is 500 valid anonymous requests and at least
100 valid unknown-shape requests. A length is an eligible padded-bucket
candidate only after 30 observations. Eligible candidates must cover at least
80% of unknown traffic and exact-allowlist coverage must remain below 90%
before the output recommends `evaluate_padded_bucket_correctness`. The long
tail is reported separately and cannot permanently block that decision.
That recommendation authorizes a new correctness and quality investigation; it
never enables padded compilation.
