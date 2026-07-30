# Route-Aware Canary Telemetry

The route-aware scheduler remains an internal experimental opt-in. A canary may
record one JSON object per completed request only with this allowlisted schema:

```json
{
  "schema_version": 1,
  "talker_prefill_length": 32,
  "prefill_shape_policy": "compiled_allowlist",
  "prefill_backend_used": "compile_reduce_overhead",
  "selected_chunk_schedule": [8, 8, 12]
}
```

Optional numeric latency fields are `first_audio_ms`, `completed_ms`, and
`inverse_rtf`. Never record text, instruction, speaker, request ID, session ID,
model path, or application-specific labels in this stream.

Aggregate local JSONL with:

```powershell
python scripts/summarize_route_coverage.py canary.jsonl `
  --compiled-length 29 --compiled-length 30 --compiled-length 32 `
  --compiled-length 33 --compiled-length 34 --compiled-length 35 `
  --output route-coverage-summary.json
```

The default evidence threshold is 500 anonymous requests and 30 samples for
each unknown length. Only if that sample gate is met and exact-allowlist
coverage remains below 90% may the output recommend
`evaluate_padded_bucket_correctness`. That recommendation authorizes a new
correctness and quality investigation; it never enables padded compilation.
