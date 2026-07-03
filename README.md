# QwenTTSBridge

QwenTTSBridge is a Windows-oriented C++17 client library for local streaming
speech synthesis with Qwen3-TTS.

The project keeps Python, PyTorch, CUDA, and Qwen3-TTS inside a standalone
worker process while exposing a stable native C++ API to applications. The
worker is started once, keeps the model loaded, and streams PCM audio chunks
back to the C++ side for every synthesis request.

Status: early architecture and repository bootstrap.

## Goals

- provide a simple C++17 API for Qwen3-TTS;
- make the C++ API async-first from the first usable implementation;
- isolate Python, PyTorch, CUDA, and model code in a separate worker process;
- keep the worker and model alive between requests;
- support low-latency streaming PCM output;
- package the worker as a standalone Windows application with Nuitka;
- avoid requiring Python to be installed on the target machine;
- keep the transport architecture open for a future WebSocket transport.

## Non-Goals

The first version does not attempt to:

- rewrite Qwen3-TTS in C++;
- replace PyTorch with LibTorch, ONNX Runtime, or TensorRT;
- embed model weights into the executable;
- provide a remote network API;
- guarantee a single-file distribution.

## Architecture

```text
C++17 application
        |
        | QwenTtsClient public API
        v
C++ bridge library
        |
        | stdin/stdout framed protocol
        v
Qwen TTS worker executable
        |
        v
Python + PyTorch + CUDA
        |
        v
Qwen3-TTS streaming engine
```

The C++ application starts and supervises the worker process. The first
transport uses the worker stdin/stdout streams. This does not make the public
API synchronous: request submission can return immediately while reader, writer,
and dispatcher threads handle streaming frames. Later, the same protocol should
be usable through a WebSocket transport.

The worker:

1. initializes Python and PyTorch;
2. loads the configured Qwen3-TTS model;
3. warms up CUDA execution when enabled;
4. waits for synthesis requests;
5. streams PCM chunks to the client;
6. remains alive for subsequent requests.

## C++ API Direction

The public API should feel like a normal C++ library, not like a command-line
wrapper around Python. The core API should be async-first; any synchronous API
should be a thin helper built on top of the async callbacks.

```cpp
QwenTtsClient tts;

tts.start("qwen_tts_worker.exe");
const auto first_id = tts.synthesize_async("First phrase", first_callbacks);
const auto second_id = tts.synthesize_async("Second phrase", second_callbacks);
const auto third_id = tts.synthesize_async("Third phrase", third_callbacks);

tts.cancel(second_id);

tts.stop();
```

The explicit request form should stay extensible:

```cpp
struct TtsRequest {
    std::uint64_t id = 0;
    std::string text;              // UTF-8 text
    std::string language = "auto";
    std::string speaker;           // optional per-request voice/speaker id
    std::string instruction;       // emotion, whispering, prosody, etc.
};

struct PcmChunk {
    std::uint64_t request_id = 0;
    AudioFormat format;
    std::vector<std::byte> bytes;
};
```

One possible callback shape:

```cpp
using RequestId = std::uint64_t;

struct TtsCallbacks {
    std::function<void(const PcmChunk&)> on_audio;
    std::function<void()> on_completed;
    std::function<void(const TtsError&)> on_error;
    std::function<void()> on_cancelled;
};

class QwenTtsClient {
public:
    RequestId synthesize_async(
        TtsRequest request,
        TtsCallbacks callbacks);

    bool cancel(RequestId request_id);
};
```

Async API and parallel inference are separate decisions. The first worker can
accept and queue multiple requests while running GPU inference sequentially:

```text
C++ accepts many requests
        |
        v
worker request queue
        |
        v
GPU synthesizes one request at a time
```

Parallel model inference can be evaluated later because it may increase VRAM
usage, conflict with static KV-cache or CUDA Graphs, and hurt per-request
latency.

Emotional speech, whispering, speaking rate, prosody, and similar controls
should be passed to the worker as UTF-8 text or a natural-language style
instruction. The C++ API should not start with a closed emotion enum because
Qwen3-TTS exposes much of this control through natural-language instructions.
Singing should be treated as an engine capability to validate before the C++ API
promises any singing-specific behavior.

The protocol should keep spoken text and style instruction separate:

```json
{
  "message_type": "synthesize",
  "text": "I thought you were not coming.",
  "language": "English",
  "speaker": "Alice",
  "instruction": "Speak with relief, but keep a little resentment.",
  "output": {
    "sample_format": "s16le",
    "sample_rate": 24000,
    "channels": 1
  }
}
```

`speaker` is an optional per-request voice override. If it is omitted or empty,
the bridge does not select a voice on behalf of the application. A worker engine
may use its own default, or it may reject the request when the selected model
requires an explicit voice.

Model families use this control differently:

```text
CustomVoice    text + language + speaker + instruction
VoiceDesign    text + language + instruction as voice/style description
Base/clone     text + language + reference audio or prompt data
```

Optional C++ helpers may map simple presets such as `Emotion::Happy` or
`Emotion::Sad` into instruction strings, but the main API should remain
open-ended through `request.instruction`.

## Transport Plan

The first implementation uses a persistent worker process and framed binary
messages over stdin/stdout:

```text
stdin   client -> worker protocol frames
stdout  worker -> client protocol and PCM frames
stderr  worker logs only
```

Worker logs must never be written to stdout because stdout is reserved for
protocol frames and binary PCM data.

The worker may also write structured diagnostics to stderr. Metric lines use
the `qtb_metric ` prefix followed by compact JSON, for example:

```text
qtb_metric {"duration_ms":4821.37,"event":"engine_loaded"}
```

These metrics are not protocol frames and must never appear on stdout. Current
events cover model load, warmup, ready delivery, request queueing, request
start, first PCM chunk, and terminal request state. Request metrics include
durations, chunk and byte counts, and real-time factor when the PCM format is
known.

Recommended runtime flow:

```text
application threads
        |
        v
QwenTtsClient::synthesize_async()
        |
        v
outgoing request queue -> writer thread -> stdin

stdout -> reader thread -> frame parser -> event queue -> dispatcher thread
        |
        v
user callbacks
```

The transport layer should remain byte-oriented:

```cpp
enum class SendResult {
    Accepted,
    WouldBlock,
    Closed,
    Failed
};

class ITransport {
public:
    using Bytes = std::vector<std::byte>;
    using ReceiveHandler = std::function<void(Bytes)>;

    virtual ~ITransport() = default;

    virtual bool start(ReceiveHandler receive_handler) = 0;
    virtual SendResult send(const std::byte* data, std::size_t size) = 0;
    virtual bool is_running() const = 0;
    virtual void stop() = 0;
};
```

The exact interface may evolve, but `ITransport` should not know anything about
Qwen, synthesis requests, JSON payloads, or PCM meaning. Protocol parsing and
request state live above the transport.

## Audio And Unity Notes

The core bridge returns streaming PCM and does not own physical audio playback.
Future native playback helpers, Unity/Salsa integration, and one-active-sink
rules are captured in
[docs/audio-and-unity-integration.md](docs/audio-and-unity-integration.md).

## Communication Protocol

The protocol must be versioned from the beginning.

The byte-level v1 specification lives in
[docs/protocol-v1.md](docs/protocol-v1.md).

Suggested frame header fields:

```text
magic
protocol_version
header_size
frame_type
flags
payload_size
request_id
```

The frame header owns protocol versioning, payload size, frame type, and
`request_id`. Control payloads may be UTF-8 JSON and use `message_type`; they do
not duplicate `protocol_version` or `request_id`. PCM audio must use binary
frames and must not be Base64-encoded.

Request terminal states:

```text
completed
cancelled
failed
```

Every request that reaches `queued` or `running` must produce exactly one
terminal event.

Request lifecycle should include queued async work:

```text
created -> queued -> running -> completed
created -> running
queued -> cancelled
running -> cancelled
running -> failed
```

## Repository Layout

Planned layout:

```text
src/                    C++17 client implementation
worker/                 Installable Python worker package
worker/src/             Python worker import root
external/cpp/           C++ dependencies as git submodules
external/python/        vendored or patched Python projects as git submodules
scripts/                setup, build, packaging, and diagnostics scripts
config/                 runtime configuration examples
tests/                  C++, Python, mock-worker, and integration tests
models/                 local model storage, not committed
dist/                   generated release packages, not committed
```

C++ headers and source files are stored together in `src/` during the initial
phase.

The Python worker uses a `src` package layout. For local development, install
it in editable mode or run tests with `worker/src` on `PYTHONPATH`:

```text
py -3 -m pip install -e worker
py -3 -m unittest discover -s tests/python
```

Python development checks use locked tool versions:

```text
.\scripts\setup-python-dev.ps1
.\scripts\check-python.ps1
```

The setup script installs `worker/requirements-dev.lock.txt` and the worker
package in editable mode. The check script runs Ruff, Pyright, and Python
unittests with `worker/src` available on `PYTHONPATH`.

To keep the tools isolated in a local virtual environment, use:

```text
.\scripts\setup-python-dev.ps1 -UseVenv
.\scripts\check-python.ps1 -UseVenv
```

CI runs the same scripts with the Python executable provided by
`actions/setup-python`.

Current Python worker engine backends:

```text
python -m qwen_tts_bridge_worker mock
python -m qwen_tts_bridge_worker qwen --model-path <model-or-repo>
```

The `qwen` backend lazily loads the vendored or installed Qwen3-TTS streaming
package only when selected. CustomVoice and VoiceDesign requests use the fork's
incremental PCM streaming path when the loaded wrapper exposes it. Base
voice-clone requests and reference audio remain planned follow-ups.

CustomVoice models require an explicit per-request speaker name. Set
`TtsRequest::speaker` in C++ or pass `--speaker <name>` to the WAV example.

## Dependencies

All source dependencies are managed as git submodules and pinned to exact
commits. Keep submodules linear and avoid recursive submodules when practical.

Initial C++ dependency:

```text
external/cpp/tiny-process-library/
https://gitlab.com/eidheim/tiny-process-library
```

Qwen streaming fork:

```text
external/python/Qwen3-TTS-streaming/
https://github.com/NewYaroslav/Qwen3-TTS-streaming
```

Future WebSocket dependencies:

```text
external/cpp/Simple-WebSocket-Server/
https://gitlab.com/eidheim/Simple-WebSocket-Server

external/cpp/asio/
https://github.com/chriskohlhoff/asio
```

Normal Python packages should be installed from locked requirements files and
must not be committed into the repository.

Model weights are stored locally under `models/` and are excluded from Git.

## Build Strategy

The repository will produce two primary artifacts:

```text
qwen_tts_client.exe
qwen_tts_worker.exe
```

The C++ component is built with CMake and a C++17 compiler.

The Python worker is packaged using Nuitka in standalone directory mode.
Onefile packaging is not the initial target because PyTorch and CUDA
distributions are large and often need runtime files next to the executable.

The initial worker packaging scaffold uses a separate pinned tool environment:

```text
.\scripts\setup-python-packaging.ps1 -UseVenv
.\scripts\package-worker.ps1 -UseVenv -DryRun
.\scripts\package-worker.ps1 -UseVenv -Clean -AssumeYesForDownloads
.\scripts\test-packaged-worker.ps1 -UseVenv
```

Packaging scripts require Python 3.11 by default and call `py -3.11` when no
explicit interpreter is provided. With `-UseVenv`, they default to
`.venv-packaging` so Nuitka and future packaging-only packages do not pollute
the development `.venv`. If an existing `.venv-packaging` was created with a
different Python version, remove it and rerun setup with Python 3.11.

The dry run prints the exact Nuitka command without compiling. A real run stages
the worker into:

```text
dist/QwenTTSBridge/
    worker/
        qwen_tts_worker.exe
    config/
    models/
```

By default, the script packages the bridge worker code and installed runtime
dependencies visible to the selected Python environment. Use `-QwenProfile` when
the `qwen_tts` package is installed and Qwen runtime modules should be forced
into the Nuitka dependency graph:

```text
.\scripts\package-worker.ps1 -UseVenv -QwenProfile CustomVoice
.\scripts\package-worker.ps1 -UseVenv -QwenProfile VoiceDesign
.\scripts\package-worker.ps1 -UseVenv -QwenProfile VoiceClone
.\scripts\package-worker.ps1 -UseVenv -QwenProfile Full
```

`CustomVoice` and `VoiceDesign` apply the bridge's narrow Qwen runtime profile:
they include `qwen_tts.inference`, the specific `qwen_tts.core` runtime modules
used by model and tokenizer registration, Qwen package data, and Torch
distribution metadata required by Transformers, while excluding
`qwen_tts.cli`/demo UI paths such as Gradio, external development/test tools,
non-Torch `einops.layers` backends, and PyTorch compile/dynamo/inductor paths
that the bridge worker does not call. Internal `torch._functorch` is still
packaged because regular eager `torch` startup imports it, and
`torch.testing._internal` is not excluded globally because parts of eager Torch
startup can import it through checkpoint/export utilities. Top-level
`functorch` also remains available because it belongs to the Torch distribution
metadata that Transformers expects. The profile also applies
`worker/packaging/nuitka-qwen-runtime.yml`, which disables Transformers'
debug-only model addition context, replaces Transformers' Dynamo masking
context with a tested eager-inference shim, and replaces Qwen's
`librosa.filters.mel` lookups with the tested
`qwen_tts_bridge_worker.packaging` `torchaudio` mel-filter shim during
packaging. It also removes Transformers' Dynamo-only graph decorator and stubs
the flex-attention import because the narrow profile does not package
`torch._dynamo`, and stubs Transformers
DTensor/tensor-parallel imports because the packaged worker runs single-process
eager inference. It also
stubs Transformers quantizer loading; the narrow profile targets unquantized
Qwen checkpoints. It also stubs the encoder-decoder config import in
Transformers' auto-tokenizer path because the Qwen narrow profile does not
package the generic encoder-decoder model family.
CustomVoice and VoiceDesign also apply
`worker/packaging/nuitka-qwen-narrow-audio.yml`, which disables Qwen
reference-audio loading helpers that belong to the VoiceClone profile, keeps
Transformers' generation runtime and distributed config helpers available for
Qwen `GenerationMixin`/`PreTrainedModel` imports, includes Transformers'
adapter mixin module used by `PreTrainedModel`, includes the EnCodec feature
extractor used by Mimi/AutoFeatureExtractor without packaging the full EnCodec
model implementation, and rewrites Qwen's root-level Transformers `Auto*`
lookups to direct submodule imports. The packaged layout
also creates minimal `transformers.models`, `transformers.models.auto`, and
`transformers.models.mimi` package shells with `qtb_packaging_placeholder.py` so
Transformers can build lazy import tables without packaging the full model zoo.
The `auto` shell re-exports only the narrow `Auto*` classes needed by Qwen and
Transformers startup. Compiled Transformers import sites that need these
classes are still patched to direct submodule imports instead of depending on
the staged shell.
The profile permits Nuitka optional-module availability probes to observe excluded
modules without turning those probes into fatal startup failures. That
keeps Torch Dynamo's symbolic-shapes branch, Torch
FakeTensor/ProxyTensor/runtime-assert `sympy` helper branches, plus the
reference-audio `librosa` path, out of the narrow Qwen Nuitka graph unless a
profile explicitly needs those paths. SciPy may still be included through
unrelated Transformers or Accelerate paths; reducing that graph is separate
packaging work. The profile nofollow rules intentionally target only known
eager-unused symbolic helper imports, not the whole `torch.fx` package or all
of `sympy`, because plain eager `torch` startup still uses some FX modules and
downstream dependencies may legitimately import `sympy`.
`VoiceClone` adds audio-reference dependencies explicitly. `Full` is a
diagnostic fallback that includes the broad `qwen_tts` package.
`-IncludeQwenPackage` is kept as a compatibility alias for
`-QwenProfile CustomVoice`.

For diagnostics, `package-worker.ps1` also accepts `-NuitkaReportPath`,
`-ShowNuitkaProgress`, `-ShowNuitkaMemory`, `-StrictBloatChecks`,
`-GenerateCOnly`, and `-ExtraNuitkaOptions`. Use `-GenerateCOnly` with a report
path when iterating on Qwen dependency graph reductions; it stops after Nuitka
Python-level optimization and C source generation instead of expecting a staged
worker executable.
Full PyTorch/CUDA runtime validation, model-file layout, and transitive
packaging locks remain follow-up packaging work.

The packaged-worker smoke test launches `qwen_tts_worker.exe`, speaks the real
QTB stdin/stdout protocol, sends one mock synthesis request, verifies that at
least one PCM frame is returned, and shuts the worker down gracefully.

As a more conservative release fallback, the project also has a portable Python
worker layout. It copies the selected Python 3.11 base runtime plus the
packaging environment's `site-packages` into `dist/QwenTTSBridge/worker-python`
and writes a `qwen_tts_worker.cmd` convenience launcher:

```text
.\scripts\setup-python-packaging.ps1 -UseVenv
.\scripts\package-python-worker.ps1 -UseVenv -Clean
.\scripts\test-portable-python-worker.ps1 -UseVenv
```

For the C++ bridge path, launch the staged Python executable directly rather
than using the `.cmd` file:

```text
dist\QwenTTSBridge\worker-python\python\python.exe -P -s -m qwen_tts_bridge_worker
```

Set these environment variables on the worker process or on the parent process
before starting `StdIoTransport`:

```text
PYTHONHOME=dist\QwenTTSBridge\worker-python\python
PYTHONPATH=dist\QwenTTSBridge\worker-python\python\Lib\site-packages
PYTHONNOUSERSITE=1
```

When launching through `StdIoTransportOptions`, prefer
`environment_overrides` so the worker inherits `PATH`, `SystemRoot`, `TEMP`,
and other parent-process values:

```cpp
StdIoTransportOptions options;
options.arguments = {
    R"(dist\QwenTTSBridge\worker-python\python\python.exe)",
    "-P",
    "-s",
    "-m",
    "qwen_tts_bridge_worker",
};
options.environment_overrides = {
    {"PYTHONHOME", R"(dist\QwenTTSBridge\worker-python\python)"},
    {"PYTHONPATH", R"(dist\QwenTTSBridge\worker-python\python\Lib\site-packages)"},
    {"PYTHONNOUSERSITE", "1"},
};
```

`StdIoTransportOptions::environment` is a complete replacement environment
block. Do not set only the three Python variables there unless you also copy
the parent environment first.

The `.cmd` launcher sets the same environment and is meant for manual
command-line use. The repository smoke test validates the direct `python.exe`
path through the C++ example and `StdIoTransport`:

```text
.\scripts\test-portable-python-worker-cpp.ps1 -UseVenv
```

For Qwen probes, install the vendored fork first and include its source package
in the portable layout:

```text
.\scripts\setup-python-packaging.ps1 -UseVenv -InstallQwenFork
.\scripts\package-python-worker.ps1 -UseVenv -Clean -IncludeQwenFork
.\scripts\test-packaged-qwen-worker.ps1 -UseVenv -WorkerExe dist\QwenTTSBridge\worker-python\qwen_tts_worker.cmd -ModelPath models\<model-dir> -Speaker <speaker-name>
```

This path is intentionally less slim than Nuitka and may be large when the
packaging environment contains PyTorch/Qwen dependencies. Its purpose is to
provide a debuggable private Python runtime beside the C++ application while
the narrow Nuitka runtime remains an optimization track. Models still stay
external under `models/`.

For a local packaged Qwen probe, install the vendored streaming fork into the
packaging environment, include the Qwen runtime profile, and run the packaged
executable against a real local model:

```text
.\scripts\setup-python-packaging.ps1 -UseVenv -InstallQwenFork
.\scripts\package-worker.ps1 -UseVenv -Clean -AssumeYesForDownloads -QwenProfile CustomVoice -NuitkaReportPath tmp\nuitka-worker\qwen-report.xml
.\scripts\test-packaged-qwen-worker.ps1 -UseVenv -ModelPath models\<model-dir> -Speaker <speaker-name>
```

Current Qwen packaging checkpoint: the narrow `CustomVoice` profile has reached
a successful local Nuitka standalone build, and the packaged smoke gets far
enough to start Qwen/Transformers model loading. The latest known runtime
blocker is Transformers processor loading expecting root-level lazy mappings
such as `transformers.IMAGE_PROCESSOR_MAPPING`. Treat that as a deliberate
follow-up for the narrow-Nuitka optimization track, not as a casual "add one
more import" fix. The next practical release path should be a portable Python
worker baseline with a private Python runtime and installed Qwen dependencies
beside the C++ app, while keeping models external.

Before a long real package build, the import probe can confirm that the selected
vendored Qwen import path does not eagerly load audio-reference dependencies:

```text
.\.venv-packaging\Scripts\python.exe worker\packaging\probe_qwen_imports.py all
```

The probe forbids eager `librosa` and `soundfile` imports by default. If
Dynamo, SymPy, SciPy, or joblib reappears in a CustomVoice/VoiceDesign package
build, inspect the Nuitka report first and add a narrow package-configuration
replacement rather than widening the Qwen include graph.

The Qwen probe uses the same QTB stdin/stdout protocol as the mock packaged
smoke test, but it starts the packaged worker with the `qwen` backend and sends
one real synthesis request. CustomVoice models require `-Speaker`; VoiceDesign
models usually need an `-Instruction` instead. This probe is intentionally
manual for now because it depends on local model files, CUDA/PyTorch runtime
availability, and the selected Qwen model family.

GitHub Actions also provides a manual `Packaged Worker Smoke` workflow. It is
started with `workflow_dispatch`, builds the standalone worker on
`windows-2022`, runs the same mock packaged-worker smoke test, and can upload
`dist/QwenTTSBridge` as an artifact. It is intentionally manual because Nuitka
compilation is slower than the normal PR checks.

## Planned Milestones

### Milestone 1: Protocol Prototype

- define versioned frames and control messages;
- implement a mock Python worker;
- start the worker from C++;
- exchange health-check messages;
- stream deterministic test PCM data.

### Milestone 2: Async Persistent Client

- add `QwenTtsClient`;
- keep the worker alive across multiple requests;
- add `synthesize_async()`;
- add request IDs, active request tracking, callbacks, cancellation, and
  terminal events;
- add outgoing and incoming queues;
- save streamed PCM into a WAV file from a C++ example.

### Milestone 3: Qwen3-TTS Integration

- integrate `external/python/Qwen3-TTS-streaming/`;
- load Qwen3-TTS in the Python worker;
- synthesize complete audio;
- pass natural-language style instructions to the engine;
- add structured model and worker errors.

### Milestone 4: Streaming and Packaging

- expose incremental PCM streaming from the Qwen engine;
- measure first-audio latency and real-time factor;
- package the worker with Nuitka;
- verify the packaged worker runs without system Python.

### Milestone 5: Production Transport

- add heartbeat, startup timeout, and graceful shutdown;
- capture stderr diagnostics;
- add forced termination fallback;
- evaluate WebSocket transport with Simple-WebSocket-Server and asio.

## Roadmap Shape

The project should skip a sync-only public API and aim directly at the async
`0.2` shape:

```text
0.2:
    persistent worker
    stdio transport
    async C++ API
    request queue
    streaming callbacks
    cancel
    heartbeat
    restart

0.3:
    optional WebSocket transport
    optional external clients
```

WebSocket is not required for async behavior. It is only a different connection
model.

## References

- Qwen3-TTS upstream: https://github.com/QwenLM/Qwen3-TTS
- Qwen3-TTS streaming fork: https://github.com/NewYaroslav/Qwen3-TTS-streaming
- Qwen3-TTS streaming documentation: https://qwenlm-qwen3-tts.mintlify.app/guides/streaming
- Nuitka user manual: https://nuitka.net/user-documentation/user-manual.html
