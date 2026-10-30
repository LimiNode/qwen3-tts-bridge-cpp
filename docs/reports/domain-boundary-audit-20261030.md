# C++ domain/include boundary audit — 2026-10-30

Status: **inventory with one minimal corrective**.

This audit records the supported public include contract and checks the
cross-domain dependencies under `src/qwen_tts_bridge`. It does not change
namespaces, DTO ownership, ABI, or the runtime architecture.

## Contract

The supported public surface is domain-first. Applications should include the
domain umbrellas below; implementation leaf headers are not independently
supported unless explicitly called out.

| Domain | Supported entry point | Notes |
| --- | --- | --- |
| shared data | `qwen_tts_bridge/data.hpp` | protocol DTOs, enums, and `RequestId` |
| client | `qwen_tts_bridge/client.hpp` | async client and request/callback DTOs |
| audio | `qwen_tts_bridge/audio.hpp` | optional capture, cursor, and post-processing helpers |
| protocol | `qwen_tts_bridge/protocol/control.hpp`, `protocol/framing.hpp` | JSON control and binary framing |
| transport | `qwen_tts_bridge/transport.hpp` | byte transport interfaces and stdio transport |
| session | `qwen_tts_bridge/session.hpp` | worker/session orchestration |
| playback | `qwen_tts_bridge/playback.hpp` | neutral sample-clock receipt helpers |
| native | `qwen_tts_bridge/native.hpp` | optional qwentts.cpp adapter |
| text | `qwen_tts_bridge/text.hpp` | optional `tts-front-cpp` adapter |
| WinMM | `qwen_tts_bridge/playback/winmm_playback.hpp` | explicitly supported optional build-tree entry point |

The CMake `public_header_self_contained` target now compiles these umbrellas
and the explicitly supported WinMM entry point. It no longer treats every
installed leaf as a standalone API promise.

## Dependency observations

| Area | Observed dependency | Assessment |
| --- | --- | --- |
| `client` → `data`, `protocol/control`, `session`, `transport` | Facade composes the lower layers | Intended direction |
| `session` → `data`, `protocol`, `transport` | Session owns lifecycle and wire routing | Intended direction |
| `protocol/framing` → `data` | Frame DTOs use protocol types | Intended direction |
| `audio` → `client/client_types` | Audio callbacks consume `PcmChunk` and `AudioFormat` | Intentional shared DTO use; no ownership move |
| `text` → `client/client_types` | Prepared text is part of request-facing API | Intentional integration dependency |
| speech-animation integration → `client/client_types` | Adapter receives bridge PCM/timing DTOs | Optional integration boundary; remains opt-in |
| playback receipt → `client/client_types` | Receipt observes `PcmChunk` | Intentional for PCM observation |
| playback cursor → `client/client_types` | Only `RequestId` was needed | Corrected below |
| WinMM playback → `audio`, `data`, playback cursor | Optional sink consumes public audio/data contracts | Intentional optional module |

## Corrective finding

`playback/playback_cursor.hpp` previously included the client DTO umbrella to
obtain only `RequestId`. That made a neutral playback-clock value type depend
on the client domain. It now includes the minimal public data definition,
`data/protocol_types.hpp`, without changing the type or namespace.

No evidence justified moving `PcmChunk`, `AudioFormat`, or other DTOs in this
pass. Doing so would broaden the ABI and ownership change without a concrete
boundary defect.

## Deferred decisions

- Keep leaf headers private-by-convention until a deliberate installed public
  include layout is introduced.
- Keep `winmm_playback.hpp` independently usable because it is an optional
  sink entry point used by build-tree consumers.
- Revisit `playback_receipt.hpp` and audio helpers only if the project splits
  media DTOs from client request DTOs as a separate API decision.
- Keep speech-animation and native headers opt-in; this audit does not promote
  experimental backends into the stable SDK contract.

## Verification

- `git diff --check`
- CMake header self-containment target with umbrella list
- Existing C++ test matrix on the exact corrective HEAD

