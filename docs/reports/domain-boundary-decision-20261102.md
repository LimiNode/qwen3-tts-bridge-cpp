# C++ domain ownership and filename decision — 2026-11-02

Status: **audit complete; no directory relocation justified before beta**.

This is a documentation-only decision record prepared after acceptance PR #268
was merged at `9ebce2cd6f8db8b5de43b0ba021e171a3b0e1364`. It inventories the
current tree and separates actual ownership defects from filename consistency
work. It does not change ABI, namespaces, include semantics, or runtime code.

## Public include contract

Supported stable entry points remain the domain umbrellas:

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
| speech animation | the two adapter headers under `integration/speech_animation/` | opt-in integration |
| WinMM | `qwen_tts_bridge/playback/winmm_playback.hpp` | opt-in Windows sink |

Installed leaf headers are implementation details unless listed above. The
existing `public_header_self_contained` target checks these umbrellas and the
explicit WinMM/speech-animation exceptions. No evidence supports promising
every installed leaf as an independently stable API before beta.

## Ownership decisions

| Area | Current owner | Direct dependencies | Decision | Severity |
| --- | --- | --- | --- | --- |
| `RequestId`, `PcmChunk`, `AudioFormat` | `data` plus client-facing DTO aliases | protocol/client/audio/playback | Keep shared value types in `data`; do not move them during filename work | P3 |
| audio `playout_cursor` | `audio` | client PCM DTO | It shapes producer-ahead PCM for interruption; it is not a physical device cursor | P3 clarification |
| playback `playback_cursor` | `playback` | `RequestId` only | It is the sink-owned physical sample clock; keep separate from audio playout shaping | P3 clarification |
| WAV callback helpers | `audio` | client callbacks, control messages, post-processing | Application-facing streaming/WAV helper; keep under audio umbrella, not core client | P3 |
| playback receipt | `playback` | PCM DTO and playback cursor | Correct optional playback observer; no ownership move | P3 |
| native adapter | `native` and `worker/native/qwentts` | qwentts ABI/runtime manifest | Opt-in backend boundary is intentional; do not promote to stable beta backend | P2 |
| text adapter | `text` | external `tts-front-cpp`, client DTO | Optional frontend integration; no relocation | P2 |
| speech animation | `integration/speech_animation` | external adapter and client PCM | Optional integration boundary is correct; keep build-gated | P2 |
| protocol control/framing | `protocol` | data DTOs, private JSON implementation | Dependency direction is correct; keep JSON private | P2 |
| client/session/transport | `client` → `session` → `transport`/protocol | lower-level domains | Facade and lifecycle ownership are coherent | P3 |

No P1 ownership violation was found. The earlier `playback_cursor` dependency
on the client umbrella has already been removed; the playback umbrella supplies
the shared data context explicitly.

## Complete current inventory

The inventory was generated on the exact tree with:

```powershell
Get-ChildItem src/qwen_tts_bridge -Recurse -File |
  Where-Object Extension -in '.hpp','.cpp'
Get-ChildItem worker/native/qwentts -Recurse -File |
  Where-Object Extension -in '.hpp','.cpp'
```

Counts: `src/qwen_tts_bridge`: 58 C++ files, of which 21 use PascalCase
filenames; `worker/native/qwentts`: 13 C++ files, of which 6 use PascalCase.
The remaining files already use snake_case and are unchanged by this decision.

### PascalCase rename map (mechanical, no symbol changes)

| Current path | Proposed path | Owner/classification | Move justified? |
| --- | --- | --- | --- |
| `audio/TerminalFadePostProcessor.{cpp,hpp}` | `audio/terminal_fade_post_processor.{cpp,hpp}` | audio, internal leaf | Yes, naming only |
| `audio/WavWriter.{cpp,hpp}` | `audio/wav_writer.{cpp,hpp}` | audio, internal leaf | Yes, naming only |
| `client/QwenTtsClient.{cpp,hpp}` | `client/qwen_tts_client.{cpp,hpp}` | client, implementation behind umbrella | Yes, naming only |
| `integration/speech_animation/PlaybackAnimationRuntime.{cpp,hpp}` | `integration/speech_animation/playback_animation_runtime.{cpp,hpp}` | opt-in integration | Yes, naming only |
| `integration/speech_animation/SpeechAnimationAdapter.{cpp,hpp}` | `integration/speech_animation/speech_animation_adapter.{cpp,hpp}` | opt-in integration | Yes, naming only |
| `native/NativeQwenBackend.{cpp,hpp}` | `native/native_qwen_backend.{cpp,hpp}` | opt-in native adapter | Yes, naming only |
| `protocol/framing/FrameParser.{cpp,hpp}` | `protocol/framing/frame_parser.{cpp,hpp}` | protocol leaf | Yes, naming only |
| `session/WorkerSession.{cpp,hpp}` | `session/worker_session.{cpp,hpp}` | session leaf | Yes, naming only |
| `text/TtsFrontTextPreparer.{cpp,hpp}` | `text/tts_front_text_preparer.{cpp,hpp}` | opt-in frontend adapter | Yes, naming only |
| `transport/ITransport.hpp` | `transport/i_transport.hpp` | transport leaf | Yes, naming only |
| `transport/stdio/StdIoTransport.{cpp,hpp}` | `transport/stdio/std_io_transport.{cpp,hpp}` | transport leaf | Yes, naming only |
| `worker/native/qwentts/NativeEngine.{cpp,hpp}` | `worker/native/qwentts/native_engine.{cpp,hpp}` | native worker | Yes, naming only |
| `worker/native/qwentts/QwenDllLoader.{cpp,hpp}` | `worker/native/qwentts/qwen_dll_loader.{cpp,hpp}` | native worker | Yes, naming only |
| `worker/native/qwentts/StdioServer.{cpp,hpp}` | `worker/native/qwentts/stdio_server.{cpp,hpp}` | native worker transport | Yes, naming only |

The table expands pairs as two files; it covers all 21 PascalCase files in
`src` and all 6 PascalCase files in the native worker. Existing snake_case
files, including protocol control/framing leaves, playback, data, and audio
helpers, remain at their current paths.

## Compatibility and sequencing decision

1. Do not move domains or DTOs before beta; the audit found no concrete defect
   that justifies an ABI or ownership change.
2. Perform filename normalization as a separate mechanical PR using `git mv`.
   Update CMake, includes, tests, examples, documentation and Doxygen paths.
3. Keep umbrella include paths stable. Do not add compatibility wrappers for
   internal leaves; document the pre-beta migration if a direct leaf include is
   found in supported examples.
4. Run installed-consumer, header self-containment, optional-feature and full
   Windows CI before considering the rename PR.

The filename PR must not be merged automatically. Any justified domain move is
deferred to a later, separately reviewed PR.
