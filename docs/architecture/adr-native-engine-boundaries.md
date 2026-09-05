# ADR: native engine and transport boundaries

- Status: accepted
- Date: 2026-09-05

## Context

QwenTTSBridge currently supervises a persistent Python worker over QTB framed
stdin/stdout. qwentts.cpp provides the same model families through GGML and a
versioned plain-C shared-library ABI. Directly adding qwentts.cpp to the Bridge
CMake graph would make a lightweight client library inherit GGML, CUDA backend,
compiler, architecture, and packaging constraints.

The existing Bridge `ITransport` is deliberately byte-oriented and
protocol-neutral. A DLL function-call surface is not a byte transport and must
not be forced into that interface.

## Decision

Engine identity and communication mechanism are independent dimensions:

| Engine | Process session | In-process session |
| --- | ---: | ---: |
| Python/FasterQwen | supported and accepted | not applicable |
| qwentts.cpp | target default native path | future opt-in |

The target ownership is:

```text
faster-qwen3-tts
    Python/Faster engine implementation

qwentts.cpp
    native engine implementation
    generic qwen.dll C ABI and runtime dependencies

qwen3-tts-bridge-cpp
    public client API
    QTB protocol and byte transports
    Python worker integration
    native qwentts QTB worker
    optional in-process DLL session
```

The recommended native deployment is:

```text
Application -> QwenTTSBridge -> persistent native worker -> qwen.dll
```

The native worker belongs to the Bridge because it implements QTB. It loads
`qwen.dll` dynamically, validates the ABI/export table before sending `ready`,
and remains independently restartable. qwentts.cpp continues to own and build
its generic DLL; it contains no Bridge-specific worker protocol.

The Bridge build must not:

- call `add_subdirectory(qwentts.cpp)` in the normal or native-worker build;
- link against `qwen.lib`;
- include GGML or CUDA headers;
- require nvcc or the qwentts.cpp compiler configuration;
- package model weights in source control.

The current `QwenTtsClient`, `WorkerSession`, `ITransport`, and QTB path already
support any conforming process executable. No public backend abstraction is
needed merely to add the native worker.

If an in-process DLL path is later accepted, introduce a semantic internal
session boundary:

```text
QwenTtsClient
    -> IEngineSession
        -> WorkerProcessSession -> ITransport + QTB
        -> NativeDllSession -> qwen.dll C ABI
```

`NativeDllSession` is not an `ITransport`. It must retain the same async
request/callback/cancellation behavior while documenting that native crashes,
CUDA runtime state, GPU memory, and DLL collisions share the application
process.

## Packaging and compatibility

qwentts.cpp should publish a standalone runtime bundle containing `qwen.dll`,
its GGML/backend DLLs, `qwen.h`, licenses, and a machine-readable manifest. The
Bridge native-worker package consumes a prepared bundle and validates its
engine commit, ABI version, architecture, required exports, and file hashes. It
does not compile the engine.

Protocol compatibility and engine ABI compatibility are separate gates. QTB
version negotiation protects the application/worker boundary; the worker's
loader protects the worker/qwen.dll boundary.

## Consequences

The process path adds negligible IPC cost relative to model inference and 24
kHz mono PCM bandwidth, while providing crash isolation, deterministic
shutdown, independent restart, and toolchain separation. Distribution contains
more files and requires a runtime manifest.

The in-process option can later remove IPC and offer direct callbacks, but is
not the recommended default because an engine assertion or access violation can
terminate the application.

## Superseded prototype

PR #67 directly added qwentts.cpp to the Bridge CMake graph and linked an
adapter against its shared target. It remains useful evidence that
`QWEN_SHARED=ON`, ABI version 4, streaming callbacks, cancellation symbols, and
Windows linkage work. That source-linked shape is superseded by this decision
and must not be merged as the production backend.
