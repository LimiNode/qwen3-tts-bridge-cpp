# C++ domain ownership and filename decision - 2026-11-02

Status: **decision audit complete; implementation normalization remains open**.

This documentation-only record follows acceptance PR #268 at
`9ebce2cd6f8db8b5de43b0ba021e171a3b0e1364`. It distinguishes actual
definition locations, intended ownership, and mechanical filename work. It
does not claim that intended ownership is already implemented, and it changes
no ABI, namespace, include semantics, or runtime behavior.

## Public include contract

The supported stable entry points remain the domain umbrellas:

| Domain | Supported include | Classification |
| --- | --- | --- |
| data | `qwen_tts_bridge/data.hpp` | stable core |
| client | `qwen_tts_bridge/client.hpp` | stable core |
| audio | `qwen_tts_bridge/audio.hpp` | stable core/helpers |
| protocol | `qwen_tts_bridge/protocol/control.hpp`, `protocol/framing.hpp` | stable core |
| transport | `qwen_tts_bridge/transport.hpp` | stable core |
| session | `qwen_tts_bridge/session.hpp` | stable core |
| playback | `qwen_tts_bridge/playback.hpp` | stable playback helpers |
| native | `qwen_tts_bridge/native.hpp` | opt-in experimental backend |
| text | `qwen_tts_bridge/text.hpp` | opt-in external frontend |
| speech animation | adapter headers under `integration/speech_animation/` | opt-in integration |
| WinMM | `qwen_tts_bridge/playback/winmm_playback.hpp` | opt-in Windows sink |

Installed leaf headers are not automatically stable API merely because they
exist in the source tree. The current self-containment target checks umbrellas
and explicit optional exceptions, but the install surface still needs to be
aligned with the components actually exported before beta freeze.

## Actual definitions and intended ownership

| Type or area | Actual definition location | Intended owner | Decision | Severity |
| --- | --- | --- | --- | --- |
| `RequestId` | `data/protocol_types.hpp` | `data` | Keep in data | P3 |
| `AudioFormat` | `protocol/control/control_messages.hpp` | `data` | Move to neutral audio value types in a separate implementation PR | P2 |
| `PcmChunk` | `client/client_types.hpp` | `data` | Move to neutral audio value types in a separate implementation PR | P2 |
| `SpeechTimingChunk` | `client/client_types.hpp` | `data` | Move with the neutral PCM value types | P2 |
| `TtsRequest`, `PreparedText`, `TtsCallbacks` | `client/client_types.hpp` | `client` | Keep as client request, preparation, and callback contracts | P3 |
| `Frame`, `FrameHeader`, `ProtocolLimits` | `data/protocol_types.hpp` | `protocol/framing` | Inspect dependency cost before any move | P2 open decision |
| `SynthesizeMessage`, `ReadyMessage` | `protocol/control/control_messages.hpp` | `protocol/control` | Keep in protocol control | P3 |
| audio `playout_cursor` | `audio/playout_cursor.hpp` | `audio` | Producer-ahead PCM shaping, distinct from a physical device cursor | P3 clarification |
| playback `playback_cursor` | `playback/playback_cursor.hpp` | `playback` | Keep as sink-owned physical sample clock and add its explicit `RequestId` dependency | P2 include hygiene |
| native adapter | `native` and `worker/native/qwentts` | same domains | Keep opt-in and experimental for beta | P2 |
| text adapter | `text` | `text` | Keep optional and build-gated; correct its installed component contract | P2 packaging |
| speech animation | `integration/speech_animation` | same domain | Keep optional and build-gated | P2 packaging |

No P1 ownership violation was found. P2 work remains for neutral audio value
types, cross-domain include hygiene, and the installed optional-component
surface. These findings are intentionally outside the mechanical filename PR.

## Header/source classification

The audited 71 C++ files contain 24 same-stem `.hpp`/`.cpp` pairs, 17 headers
without a same-stem source, and 6 sources without a same-stem header. The
absence of a matching file is not itself a defect:

- header-only DTOs, interfaces, and umbrellas are intentional;
- `protocol/control/control_codec_internal.hpp` is a private implementation
  header shared by several codec translation units and needs no matching source;
- the five control-codec sources without matching public headers are an
  intentional responsibility split;
- `main.cpp` is a normal source-only entry point;
- `playback_interruption_diagnostics.{hpp,cpp}` is a private WinMM JSON
  formatter introduced in `1b3824d`; it belongs under `playback`, has a focused
  test, and must not be added to `playback.hpp`;
- implementation-private helpers must not become installed public SDK API only
  because their declarations live in a header.

## Filename inventory

The pre-normalization tree contains 58 C++ files under
`src/qwen_tts_bridge`, including 21 PascalCase filenames, and 13 native-worker
C++ files, including 6 PascalCase filenames. The mechanical rename map is:

| Current path | Proposed path | Classification |
| --- | --- | --- |
| `audio/TerminalFadePostProcessor.{cpp,hpp}` | `audio/terminal_fade_post_processor.{cpp,hpp}` | audio leaf |
| `audio/WavWriter.{cpp,hpp}` | `audio/wav_writer.{cpp,hpp}` | audio leaf |
| `client/QwenTtsClient.{cpp,hpp}` | `client/qwen_tts_client.{cpp,hpp}` | client leaf |
| `integration/speech_animation/PlaybackAnimationRuntime.{cpp,hpp}` | `integration/speech_animation/playback_animation_runtime.{cpp,hpp}` | opt-in integration |
| `integration/speech_animation/SpeechAnimationAdapter.{cpp,hpp}` | `integration/speech_animation/speech_animation_adapter.{cpp,hpp}` | opt-in integration |
| `native/NativeQwenBackend.{cpp,hpp}` | `native/native_qwen_backend.{cpp,hpp}` | opt-in native adapter |
| `protocol/framing/FrameParser.{cpp,hpp}` | `protocol/framing/frame_parser.{cpp,hpp}` | protocol leaf |
| `session/WorkerSession.{cpp,hpp}` | `session/worker_session.{cpp,hpp}` | session leaf |
| `text/TtsFrontTextPreparer.{cpp,hpp}` | `text/tts_front_text_preparer.{cpp,hpp}` | opt-in frontend adapter |
| `transport/ITransport.hpp` | `transport/i_transport.hpp` | transport interface |
| `transport/stdio/StdIoTransport.{cpp,hpp}` | `transport/stdio/std_io_transport.{cpp,hpp}` | transport leaf |
| `worker/native/qwentts/NativeEngine.{cpp,hpp}` | `worker/native/qwentts/native_engine.{cpp,hpp}` | native worker |
| `worker/native/qwentts/QwenDllLoader.{cpp,hpp}` | `worker/native/qwentts/qwen_dll_loader.{cpp,hpp}` | native worker |
| `worker/native/qwentts/StdioServer.{cpp,hpp}` | `worker/native/qwentts/stdio_server.{cpp,hpp}` | native worker transport |

The table expands pairs as two files and covers all 27 PascalCase filenames.

## Include and install policy selected for the corrective

- cross-directory first-party includes use `<qwen_tts_bridge/...>`;
- private same-directory includes may use `"local_header.hpp"`;
- cross-domain `../` and `../../` paths are not retained;
- third-party headers keep their own include roots;
- optional headers are installed only with a supported exported component;
- private implementation headers such as `control_codec_internal.hpp` are not
  installed as public SDK headers;
- existing stable umbrella paths continue to expose their existing types.

## Compatibility and sequencing decision

1. Integrate this corrected decision record first.
2. Keep filename normalization mechanical: no DTO moves, include normalization,
   or install/export changes in that PR.
3. Rebase the filename PR after this record lands and rerun exact-head CI.
4. Implement neutral audio ownership, include-path normalization, and install
   component corrections in one separately reviewed structural PR.
5. Preserve namespaces, public names, member defaults, layouts, protocol JSON,
   and existing umbrella behavior in the structural correction.
6. Leave framing DTO relocation open unless its dependency cost proves small
   and independently reviewable.
7. Run installed-consumer, leaf and umbrella self-containment,
   optional-feature, and full Windows CI before beta freeze.

Neither the filename PR nor the later structural PR is merged automatically.
