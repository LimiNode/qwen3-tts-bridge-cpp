# Header dependency architecture

The bridge uses hierarchical umbrella headers to make the dependency graph
visible at domain boundaries. An umbrella owns the first-party cross-domain
includes for its domain, then includes the domain's own headers with local
quoted paths. The graph is directed and acyclic; lower-level domains never
depend on their higher-level consumers.

This is an include-ownership rule, not a C++ translation-unit mechanism.
Public umbrellas and documented compatibility entry points are independently
compilable. Internal leaf headers inherit the context of their owning umbrella
and are not required to compile as standalone public headers. CMake compiles
the real implementation `.cpp` files directly. A first-party `.cpp` must never
be included from another source file, and no wrapper, forced include, PCH, or
unity-build trick supplies a missing header dependency.

## Domain graph

Paths below are relative to `src/qwen_tts_bridge/`. An owning umbrella provides
the dependency context for its internal leaves; supported standalone entry
points are listed explicitly below.

| Umbrella | Dependency umbrellas | Own headers, in order |
| --- | --- | --- |
| `data.hpp` | none | `data/{enums,protocol_types,audio_types}.hpp` |
| `protocol/control.hpp` | `data.hpp` | `control/{control_messages,control_codec}.hpp` |
| `protocol/framing.hpp` | `data.hpp` | `framing/{frame_codec,frame_parser}.hpp` |
| `transport/stdio.hpp` | none | `i_transport.hpp`, `stdio/std_io_transport.hpp` |
| `transport.hpp` | `transport/stdio.hpp` | none |
| `session.hpp` | `data.hpp`, `protocol/control.hpp`, `protocol/framing.hpp`, `transport.hpp` | `session/worker_session.hpp` |
| `client.hpp` | `data.hpp`, `protocol/control.hpp`, `session.hpp`, `transport.hpp` | `client/{client_types,qwen_tts_client}.hpp` |
| `audio.hpp` | `data.hpp`, `client.hpp` | `audio/{wav_writer,post_processor,playout_cursor,save_wav_callbacks,terminal_fade_post_processor}.hpp` |
| `playback.hpp` | `data.hpp` | `playback/{playback_cursor,playback_receipt}.hpp` |
| `text.hpp` (optional) | `client.hpp`, external `tts_front.hpp` | `text/tts_front_text_preparer.hpp` |
| `playback/winmm.hpp` (optional) | `audio.hpp`, `playback.hpp` | `winmm/wave_out_player.hpp` |
| `integration/speech_animation.hpp` (optional) | `client.hpp`, external speech-animation headers | `speech_animation/{adapter,playback_runtime}.hpp` |
| `native.hpp` (opt-in) | none | `native/native_qwen_backend.hpp` |

The root umbrella is optional. `transport/stdio.hpp` is the public connection
point for the stdio subdomain and must not include its parent `transport.hpp`.
Optional native and speech-animation umbrellas do not make their external
runtime dependencies part of the normal SDK.

## Include and implementation rules

- Public code includes a stable domain umbrella such as
  `<qwen_tts_bridge/client.hpp>` or `<qwen_tts_bridge/protocol/framing.hpp>`.
- Umbrellas include their own leaves with local quoted paths.
- Internal leaf headers may rely on the owning umbrella for cross-domain
  declarations. Same-domain and implementation-private dependencies may use
  local leaf includes. A documented standalone entry point remains
  self-contained by contract.
- Each implementation starts with its owning domain/subdomain umbrella (or a
  documented compatibility umbrella), followed by standard-library and
  implementation-private dependencies. The implementation is compiled
  directly by CMake as its own translation unit.
- First-party `.cpp` inclusion is forbidden. The source tree is not a set of
  include fragments, and there are no domain translation-unit wrappers.
- No `.clangd` forced include, PCH, unity build, or fake declaration may be
  used to hide a missing header dependency.

The distinction between a domain dependency and a translation unit is
intentional: umbrellas govern visibility between domains, while normal C++
compilation governs each source file independently.

## Supported entry points and exceptions

All public umbrellas compile independently. Existing compatibility paths remain
thin wrappers around their owning umbrella:

- `playback/winmm_playback.hpp` -> `playback/winmm.hpp`;
- `integration/speech_animation/speech_animation_adapter.hpp` ->
  `integration/speech_animation.hpp`;
- `integration/speech_animation/playback_animation_runtime.hpp` ->
  `integration/speech_animation.hpp`.

Supported standalone leaf entry points are:

- `data/audio_types.hpp` retains its same-domain `protocol_types.hpp` include
  for `RequestId`;
- `playback/playback_cursor.hpp` obtains `RequestId` through `data.hpp`.
- `playback/playback_receipt.hpp` is an installed playback timeline entry point
  and retains its direct `data.hpp` and cursor dependencies.

These are documented compatibility entry points, not a requirement to make
every internal implementation detail public. The private
`control_codec_internal.hpp` remains outside the installed API and may include
same-directory control codec headers and private nlohmann JSON.

## Verification contract

`public_header_contract` compiles each public umbrella and documented
compatibility entry point in its own translation unit. Internal leaf headers
are intentionally not generated through a recursive standalone-header check.
Forward- and reverse-order consumer fixtures cover the complete public list.
CMake source lists include each real implementation exactly once; a source
guard rejects any first-party `.cpp` include under `src/qwen_tts_bridge/`.

The installed consumer independently compiles the stdio entry point and, when
requested, both WinMM entry paths. Feature-disabled installs must not acquire
optional dependencies. Full CTest, mock playback, and optional native-worker
and speech-animation configurations remain the behavior regression gates.

The architecture change does not alter namespaces, DTO layouts, protocol
semantics, callbacks, worker behavior, or runtime policy.
