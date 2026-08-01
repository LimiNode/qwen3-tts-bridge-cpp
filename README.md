# QwenTTSBridge

[Russian README](README-RU.md)

QwenTTSBridge is a Windows-first C++17 client library for local, streaming
Qwen3-TTS inference. It keeps Python, PyTorch, CUDA, and the model in one
persistent worker process while C++ applications receive PCM through an
async-first API.

The project is a bridge, not a C++ reimplementation of Qwen3-TTS. The worker
loads the model once, accepts multiple requests, streams framed PCM over local
stdin/stdout, and supports request-ID cancellation.

## Highlights

- Persistent local worker with async C++ request submission and PCM callbacks.
- Framed binary protocol, bounded queues, deterministic worker shutdown, and
  mock-worker tests that do not require CUDA.
- Qwen CustomVoice support through text, language, optional speaker, and
  natural-language style instruction.
- WAV and default-device playback examples.
- A narrowly scoped, measured `torch.compile` internal opt-in profile for one
  pinned RTX 4090 48 GiB runtime; the default remains eager and unchanged.

Voice cloning is a planned worker capability, not yet a supported public
workflow.

## Quick Start

Configure and build with CMake:

```powershell
cmake -S . -B build -DQWEN_TTS_BRIDGE_BUILD_TESTS=ON
cmake --build build --config Release
ctest --test-dir build -C Release --output-on-failure
```

With a single-config MinGW build, executables are written directly to
`build`; multi-config generators such as Visual Studio use `build\Release`.

The mock WAV example needs no CUDA model:

```powershell
.\build\qwen_tts_save_wav.exe --mock --output sample.wav --text "Hello from QwenTTSBridge"
```

For a real worker, point the examples at the packaged worker or the selected
Python worker launcher and model profile. Runtime configuration is deliberately
not hard-coded in C++.

## Interactive Playback CLI

`qwen_tts_play` is a Windows example and smoke tool. It sends streamed
16-bit PCM to the default output device via the Windows multimedia API.

For the pinned internal RTX 4090 profile, create the ignored local runtime
file once from `config/playback-runtime.local.example.json`, then start the
interactive CLI without repeating worker arguments:

```powershell
Copy-Item config\playback-runtime.local.example.json config\playback-runtime.local.json
# Set the three local paths in playback-runtime.local.json.
scripts\start-qwen-tts-play.ps1
```

The launcher defaults to the sealed R10 profile and runs its preflight. Use
`-Text "Hello"` for a one-shot playback smoke or `-DryRun` to inspect the
resolved command without starting a worker. `-Speaker`, `-Language`, and
`-Instruction` override the saved defaults for one run. Its five-minute worker
startup timeout covers the measured R10 compile/prime startup and can be
changed with `-StartupTimeoutMs`.

```powershell
scripts\start-qwen-tts-play.ps1 -Text "Hello" -Speaker serena -Language English
```

Enter text to synthesize. While it runs, a new line cancels the prior
generation and queued playback before starting the replacement request. Use
`/cancel` to stop the current request, `/voice <name>` to select a speaker,
`/language <name>`, `/style <text>`, `/help`, or `/quit`.

Use `--text "..."` for a one-shot playback smoke, or `--mock` to exercise the
CLI against the bundled mock worker. The playback example is intentionally a
small Windows utility, not the library's future cross-platform audio layer.

## Public C++ Surface

Include only the domain surface an application uses:

```cpp
#include <qwen_tts_bridge/client.hpp>
#include <qwen_tts_bridge/audio.hpp>
#include <qwen_tts_bridge/transport.hpp>
```

There is deliberately no catch-all `qwen_tts_bridge.hpp`: `client.hpp`,
`audio.hpp`, `transport.hpp`, `session.hpp`, `data.hpp`, and protocol umbrellas
keep dependencies explicit and follow the repository's domain layout.

```cpp
qwen_tts_bridge::QwenTtsClient client;
client.start(worker_options);

qwen_tts_bridge::TtsRequest request;
request.text = "Hello";
request.speaker = "serena";

const auto id = client.synthesize_async(request, callbacks);
client.cancel(id);
```

`synthesize_async()` returns after local acceptance; it does not wait for model
inference. Audio, completion, cancellation, and errors are delivered through
callbacks on the client's dispatcher thread.

## Measured Internal Profile

The project default is not compiled. A separate internal profile has been
validated on a **pinned NVIDIA GeForce RTX 4090 reporting 48 GiB VRAM** with a
pinned model/runtime/source bundle:

| Metric | Result |
| --- | ---: |
| Verified compiled prefill lengths | `18, 19, 20, 26, 27, 29` |
| Compiled schedule | `8, 8, 12` |
| Frozen 500-record holdout mean / p95 first audio | 368.7 ms / 428.3 ms |
| Frozen holdout RTF | about 0.372 |
| Exact compiled coverage on that holdout | 99 / 500 (19.8%) |
| Python operational soak | 504 operations; 396 completed, 108 cancelled |
| C++ API soak | 250 operations; 225 completed, 25 cancelled |

Most holdout shapes are intentionally eager. The operational eager tail reached
about 1.17--1.18 s p95 first audio, so the table is not an arbitrary-text SLA.
Other capable CUDA GPUs can use the generic eager path, but require their own
measurements before receiving this compiled profile.

Read [the RTX 4090 report](docs/reports/frequency-r10-rtx4090.md) for method,
scope, evidence links, and a non-A/B external comparison. The full profile
contract is [frequency-r10-internal-opt-in-candidate.md](docs/frequency-r10-internal-opt-in-candidate.md).

## Research and Evidence

- [Research report index](docs/reports/README.md)
- [Representative corpus v4](docs/reports/benchmark-corpus-v4.md)
- [Optimization decisions](docs/reports/optimization-decisions.md)
- [R10 operational evidence](docs/benchmark-artifacts/rtx4090-2026-08-01/frequency-exact-allowlist-operational-r10/README.md)

The benchmark corpus has 2,000 unique Russian, English, and mixed-language
records covering game and live-stream scenarios. It was LLM-assisted using
real-stream language/scenario patterns, then validated and human-adjudicated;
it is not a verbatim transcript corpus. The frozen holdout is retained for
evaluation and is not used to tune the exact allowlist.

## Current Boundaries

- No remote network API or WebSocket transport yet.
- No bundled model weights.
- No public voice-cloning request flow yet.
- The packaged worker path is Windows x64 and Python 3.11 oriented.
- The RTX 4090 compiled profile is opt-in and fail-closed; it does not enable
  compilation for unknown input shapes.

## Development

Install and check the Python worker with the project scripts:

```powershell
scripts\setup-python-dev.ps1 -UseVenv
scripts\check-python.ps1 -UseVenv
```

See [AGENTS.md](AGENTS.md) for repository architecture, dependency policy,
documentation language policy, and test expectations.
