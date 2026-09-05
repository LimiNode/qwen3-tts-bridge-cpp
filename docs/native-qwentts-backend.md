# Native qwentts.cpp backend

The bridge now vendors the selected [`LimiNode/qwentts.cpp`](https://github.com/LimiNode/qwentts.cpp)
fork at a pinned commit and provides an opt-in C++ adapter over its public C
ABI. The accepted Python/FasterQwen worker remains the default release path.
The native path is experimental until it passes the same quality, streaming,
cancellation, lifecycle, and target-hardware gates.

## Build

The native dependency is excluded from normal builds. Configure it explicitly:

```powershell
cmake -S . -B build/native-qwentts `
  -DQWEN_TTS_BRIDGE_BUILD_NATIVE_BACKEND=ON `
  -DQWEN_TTS_BRIDGE_BUILD_EXAMPLES=OFF
cmake --build build/native-qwentts --config Release --target native_qwen_backend_abi_test
ctest --test-dir build/native-qwentts -C Release -R native_qwen_backend_abi_test --output-on-failure
```

This enables qwentts.cpp's `QWEN_SHARED=ON` target and builds its shared
library (`qwen.dll` on Windows). The bridge adapter target is
`QwenTTSBridge::qwen_tts_bridge_native`.

For a CUDA build, pass the backend options understood by qwentts.cpp (for
example `-DGGML_CUDA=ON` and a suitable `CMAKE_CUDA_ARCHITECTURES`) at
configure time. The exact GGUF files are not part of this repository; follow
the fork's conversion/download instructions and keep model files outside the
source tree.

## C++ adapter

Include `qwen_tts_bridge/native.hpp` and construct
`qwen_tts_bridge::native::NativeQwenBackend` with Talker and codec GGUF paths.
`synthesize()` is intentionally blocking, matching qwentts.cpp's C ABI. Pass
an `AudioChunkCallback` for streaming or a `NativeQwenAudio` output for the
buffered path. Cancellation is cooperative and polled by the native engine at
approximately one audio frame.

The adapter maps text, language, speaker/instruction, Base reference PCM,
transcript, seed, and maximum token count. It does not yet implement the
bridge's registered voice-profile file format, QTB stdio framing, or the
async `QwenTtsClient` facade. Those are the next integration layer and must be
added without changing the Python worker default.

## Promotion gates

Before enabling this backend in a product build, collect a hardware report for
each supported GPU covering:

* first PCM and inter-chunk cadence for short, medium, and long RU/EN text;
* natural EOS, cancellation, reset, and repeated-request stability;
* voice identity and reference-profile behavior;
* audible boundary artifacts and clipping;
* memory use with one and two warmed workers;
* parity against the accepted Python/FasterQwen profile where parity is an
  explicit requirement.

Until those measurements are recorded, this option is a build and ABI probe,
not a replacement for the production worker.
