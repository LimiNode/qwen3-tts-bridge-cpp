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
| Lifecycle | warmed worker, cold start, 30–100 sequential requests, cancellation after first PCM |
| Voice | Kraftwerk profile/reference, A→B→A voice switch |
| Metrics | startup, first PCM, inter-chunk cadence, total synthesis, RTF, starvation, EOS, errors, peak VRAM |

Run every row with the same model family, seed policy, and runtime settings.
The native manifest commit, ABI, model/DLL hashes, and backend must be retained
with the raw result. The Python package, model identity, and source revisions
must be retained too. Restart/recovery is a separate lifecycle phase and is not
implicitly covered by one persistent benchmark invocation.

The benchmark fails a row if an unexpected request fails or is cancelled, a
completed request has no PCM, late PCM or duplicate terminal events are
observed, EOS evidence is missing, or a protocol/stdout violation occurs. Keep
raw JSON and stderr telemetry. Add a short subjective listening check for clicks,
pauses, clipping, word endings, and voice identity after objective gates pass.

The benchmark records the backend-neutral `TtsCompletion` callback as
`completion_execution_outcome`. Native runs may provide explicit
`natural_eos`/`max_tokens` without a model generation trace; Python/Faster runs
must provide a generation trace proving natural EOS. A bare `completed` without
either form of EOS evidence is rejected, as is `max_tokens`. The stderr
`qtb_metric` line remains diagnostic only.

The repository currently has no local GGUF pair, so a real hardware comparison
is intentionally not claimed by CI. Supply model paths from outside the source
tree when running the matrix.

## Runner

`scripts/run-native-python-matrix.ps1` wraps every worker argument as a
repeated `--worker-arg`, runs the same benchmark configuration against both
workers, and stores raw JSON plus stderr logs. Use a JSONL request manifest to
exercise multiple languages, lengths, voices, and deterministic seeds:

The checked-in full manifest is a template because it contains local model and
voice paths. Copy it before editing those placeholders:

```powershell
Copy-Item .\docs\acceptance\native-python-full.template.jsonl .\docs\acceptance\native-python-full.jsonl
```

```powershell
.\scripts\run-native-python-matrix.ps1 `
  -BenchmarkExecutable .\build\Release\qwen_tts_latency_benchmark.exe `
  -PythonWorkerExecutable .\.venv\Scripts\python.exe `
  -PythonWorkerArgument @('-m', 'qwen_tts_bridge_worker', 'qwen', '--model-path', 'E:\models\qwen', '--runtime-backend', 'faster', '--runtime-profile', 'cmp50hx-low-latency') `
  -NativeWorkerExecutable .\build\Release\qwen_tts_native_worker.exe `
  -NativeWorkerArgument @('--runtime-dir', 'E:\models\qwentts-runtime', '--talker-model', 'E:\models\talker.gguf', '--codec-model', 'E:\models\codec.gguf') `
  -RequestManifest .\docs\acceptance\native-python-full.jsonl `
  -FasterQwenSourcePath .\external\python\faster-qwen3-tts `
  -QwenSourcePath .\external\python\Qwen3-TTS-streaming `
  -WarmupText "Warmup request." -WarmupReferenceAudioPath .\voices\warmup-ref.wav `
  -WarmupReferenceText "Warmup reference transcript." `
  -Warmups 5 -Requests 30 -CancelEvery 0 -GpuIndex 0 -Seed 4242 `
  -PlaybackExecutable .\build\Release\qwen_tts_play.exe `
  -PlaybackManifestLabel base-reference `
  -Output .\artifacts\native-python-matrix.json
```

Each manifest line may contain `label`, `text`, `language`, `speaker`,
`voice_id`, `instruction`, `reference_audio_path`, `reference_text`,
`x_vector_only`, and `seed`. The benchmark forwards those fields per request,
which makes A→B→A voice isolation and Base reference cloning reproducible.
Pass `-WarmupText` to keep warmup requests out of the acceptance manifest; this
prevents cancellation, negative-capacity, and voice-switch rows from being
silently consumed as warmups. For Base/reference-clone workers, also pass
`-WarmupReferenceAudioPath` and `-WarmupReferenceText` so warmup uses a valid
reference request rather than a text-only request. The runner resolves and
records this WAV as `warmup_reference_audio` with an artifact copy and SHA-256,
and stores the warmup transcript and terminal quiet period in `workload`.
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
The runner writes an `effective-request-manifest.jsonl` in which relative
reference paths are converted to absolute paths before either benchmark or
playback starts. The original and effective manifests are both retained.
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
