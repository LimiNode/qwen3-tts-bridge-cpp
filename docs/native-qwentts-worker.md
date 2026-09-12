# Native qwentts process worker

The bridge has an optional Windows worker target, `qwen_tts_native_worker`.
It is a separate process that speaks the same QTB protocol v1 over stdin/stdout
as the Python worker. The normal `qwen_tts_bridge` target does not compile
qwentts.cpp or include GGML/CUDA headers; the native worker and the separate
in-process adapter enable that dependency only through explicit opt-in options.

Build the target after initializing the pinned `external/cpp/qwentts.cpp`
submodule:

```powershell
cmake -S . -B build/native -DQWEN_TTS_BRIDGE_BUILD_QWENTTS_WORKER=ON
cmake --build build/native --config Release --target qwen_tts_native_worker
```

The worker loads a prepared runtime dynamically:

```text
native-runtime/
    qwen.dll
    ggml.dll / backend DLLs as required by qwen.dll
    manifest.json
```

Example launch:

```powershell
build\native\qwen_tts_native_worker.exe `
  --runtime-dir E:\models\qwentts-runtime `
  --talker-model E:\models\talker.gguf `
  --codec-model E:\models\codec.gguf
```

`manifest.json` is schema version 1 and must declare the engine name,
qwentts commit, ABI version, architecture, backend, and SHA-256 hashes for the
runtime files. The worker verifies the manifest and the selected `qwen.dll`
before loading it. It then resolves the required C ABI exports and checks
`QT_ABI_VERSION` through the default parameter structures. Missing files,
hashes, exports, or incompatible ABI fail before the worker sends `ready`.

The native process currently supports mono 24 kHz s16le output. qwentts emits
float PCM; the worker clamps/converts it to s16le before creating QTB audio
frames. Reference cloning accepts mono 24 kHz PCM16 or float32 WAV files.
Streaming cadence can be capped with `--stream-max-chunk-frames 1|2|4|8`;
the default is 8 and the ramp starts at one frame before doubling to that cap.
An optional `--max-text-bytes N` preflight bound makes the native worker return
`resource_error/sequence_capacity_exceeded` before generation for longer text.
Supervisors can use that explicit result to route the request to a safe native
worker or the Python/FasterQwen worker; `0` (the default) disables the bound.
This is a conservative byte bound, not a tokenizer-derived duration estimate.
For repeated Base reference requests, the opt-in `--precompute-voice-ref` flag
extracts and caches qwentts' reusable speaker embedding and RVQ reference codes
per decoded WAV. The raw-WAV path remains the default; use this flag only for an
explicit A/B run because precomputed conditioning must still pass the same PCM
and voice-identity gates.

Each request emits a diagnostic `native_pcm_signal` metric on stderr for the
first callback. It reports float PCM peak/RMS before Bridge conversion and
s16le peak/RMS after conversion, together with first-chunk latency. This is a
diagnostic boundary check, not a loudness normalizer: the Bridge must never
silently amplify native output.

The worker also rejects a successful qwentts EOS that emitted no PCM as
`model_error/empty_audio`. This prevents an empty natural-EOS result from being
reported as a successful synthesis; a supervisor may retry with a different
seed or use its configured fallback policy.

The Python/FasterQwen worker remains the accepted production backend until the
native process passes the documented quality, streaming, cancellation,
lifecycle, and target-hardware gates. The native process is intentionally
opt-in. The in-process `NativeQwenBackend` is also opt-in and higher risk
because it runs the qwentts engine in the application process.

## Runtime manifest generator

Generate a manifest for a prepared runtime with:

```powershell
$engineCommit = git -C external/cpp/qwentts.cpp rev-parse --short HEAD
python scripts/write-qwentts-runtime-manifest.py `
  --runtime-dir E:\models\qwentts-runtime `
  --engine-commit $engineCommit `
  --backend cuda
```

The manifest `engine_commit` must match the prefix returned by `qt_version()`;
the worker rejects a DLL built from a different fork revision before sending
`ready`.

The command hashes every regular file in the runtime directory except the
manifest itself. Keep the generated runtime outside the repository; model
weights, DLLs, and packaged release artifacts must not be committed.
