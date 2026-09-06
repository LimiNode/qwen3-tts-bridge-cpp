# Native versus Python acceptance matrix

The native process worker and the accepted Python/FasterQwen worker use the
same C++ benchmark executable and QTB transport. This keeps request timing and
callback dispatch comparable while allowing the engines to produce different
PCM trajectories. Byte-for-byte PCM parity is not a gate between these engine
families; successful text, natural EOS, identity, absence of starvation, and
audible quality are measured separately.

Required workload rows:

| Dimension | Rows |
| --- | --- |
| Language | Russian, English |
| Length | 1–2 words, short sentence, medium paragraph, long paragraph near the configured limit |
| Lifecycle | warmed worker, cold start, 30–100 sequential requests, cancellation after first PCM, reset/restart |
| Voice | Kraftwerk profile/reference, A→B→A voice switch |
| Metrics | startup, first PCM, inter-chunk cadence, total synthesis, RTF, starvation, EOS, errors, peak VRAM |

Run every row with the same model family, seed policy, and runtime settings.
The native manifest commit, ABI, DLL hashes, and backend must be retained with
the raw result. The Python package and source revisions must be retained too.

The benchmark fails a row if an unexpected request fails or is cancelled, a
completed request has no PCM, PCM arrives after cancellation, EOS is missing,
or a protocol/stdout violation occurs. Keep raw JSON and stderr telemetry. Add a short subjective listening check for clicks,
pauses, clipping, word endings, and voice identity after objective gates pass.

The benchmark records the backend-neutral `TtsCompletion` callback as
`completion_execution_outcome` when supplied. Native runs report
`natural_eos` or `max_tokens`; a completed request that reports `max_tokens` is
rejected as truncated. The stderr `qtb_metric` line remains diagnostic only,
and Python workers that do not expose this optional field remain compatible
with the generic terminal gate.

The repository currently has no local GGUF pair, so a real hardware comparison
is intentionally not claimed by CI. Supply model paths from outside the source
tree when running the matrix.

## Runner

`scripts/run-native-python-matrix.ps1` wraps every worker argument as a
repeated `--worker-arg`, runs the same benchmark configuration against both
workers, and stores raw JSON plus stderr logs. Use a JSONL request manifest to
exercise multiple languages, lengths, voices, and deterministic seeds:

```powershell
.\scripts\run-native-python-matrix.ps1 `
  -BenchmarkExecutable .\build\Release\qwen_tts_latency_benchmark.exe `
  -PythonWorkerExecutable .\.venv\Scripts\python.exe `
  -PythonWorkerArgument @('worker/src/qwen_tts_bridge_worker/main.py', '--model-path', 'E:\models\qwen') `
  -NativeWorkerExecutable .\build\Release\qwen_tts_native_worker.exe `
  -NativeWorkerArgument @('--runtime-dir', 'E:\models\qwentts-runtime', '--talker-model', 'E:\models\talker.gguf', '--codec-model', 'E:\models\codec.gguf') `
  -RequestManifest .\docs\acceptance\native-python-smoke.jsonl `
  -Warmups 5 -Requests 30 -CancelEvery 5 -Seed 4242 `
  -PlaybackExecutable .\build\Release\qwen_tts_play.exe `
  -PlaybackManifestLabel ru-short `
  -Output .\artifacts\native-python-matrix.json
```

Each manifest line may contain `label`, `text`, `language`, `speaker`,
`voice_id`, `instruction`, `reference_audio_path`, `reference_text`,
`x_vector_only`, and `seed`. The benchmark forwards those fields per request,
which makes A→B→A voice isolation and Base reference cloning reproducible.
For negative or fallback cases, `allowed_terminal_outcomes` may list values
such as `natural_eos`, `completed`, and `request_error`; optional
`expected_error_category` and `expected_error_code` constrain an error without
rejecting an explicitly allowed fallback. Global language, speaker, voice ID,
and seed values are passed as defaults and are overridden by fields present in
each manifest row. Use `allowed_errors` for backend-equivalent error pairs,
for example native `request_error/invalid_native_request` and Python
`resource_error/sequence_capacity_exceeded`.

The runner samples system GPU memory every 250 ms when `nvidia-smi` is
available. `host_peak_gpu_memory_used_mib` is a system-level peak, not a
process-exclusive allocation; retain the raw samples for interpretation. Each
run stores evidence in `<Output>.artifacts/<run-id>/`; the reported stderr,
GPU-sample, and playback paths therefore remain valid after the runner exits.
The evidence record also snapshots the request manifest, native runtime/DLL
identity, bridge commit, Python worker hash, installed Python package versions,
source-tree revisions supplied through worker arguments, and optional canary
FasterQwen manifests when those paths are supplied. Every referenced audio
file is copied into the run artifact directory and recorded with its SHA-256;
missing references remain explicit in the evidence instead of being silently
ignored.
If
`-PlaybackExecutable` is supplied, the runner performs a separate physical
WaveOut run and marks the gate failed when playback does not complete or
`queue_empty_before_later_chunk_count` is non-zero. With a multi-row manifest,
pass `-PlaybackManifestLabel` to replay one exact row, including its voice,
seed, instruction, and reference fields.

The checked-in smoke manifest intentionally has no machine-specific reference
audio. Use `docs/acceptance/native-python-full.template.jsonl` as a starting
point for target-specific workloads covering A→B→A switching, near/over
capacity, and explicit Base references.
