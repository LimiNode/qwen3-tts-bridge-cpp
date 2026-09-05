# Native qwentts process worker

The bridge has an optional Windows worker target, `qwen_tts_native_worker`.
It is a separate process that speaks the same QTB protocol v1 over stdin/stdout
as the Python worker. The bridge does not compile qwentts.cpp, link against its
import library, or include GGML/CUDA headers in the normal library target.

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

The Python/FasterQwen worker remains the accepted production backend until the
native process passes the documented quality, streaming, cancellation,
lifecycle, and target-hardware gates. The native process is intentionally
opt-in; the future in-process DLL backend is a separate, higher-risk option.

## Runtime manifest generator

Generate a manifest for a prepared runtime with:

```powershell
python scripts/write-qwentts-runtime-manifest.py `
  --runtime-dir E:\models\qwentts-runtime `
  --engine-commit a69194fc `
  --backend cuda
```

The manifest `engine_commit` must match the prefix returned by `qt_version()`;
the worker rejects a DLL built from a different fork revision before sending
`ready`.

The command hashes every regular file in the runtime directory except the
manifest itself. Keep the generated runtime outside the repository; model
weights, DLLs, and packaged release artifacts must not be committed.
