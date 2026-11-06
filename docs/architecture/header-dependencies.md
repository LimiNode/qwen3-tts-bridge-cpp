# Hierarchical header dependencies

The domain umbrella owns first-party cross-domain dependencies. It includes
dependency umbrellas before its own leaves. Internal leaves keep their required
standard-library headers, but need not compile without the enclosing umbrella.
Where context is needed, per-source domain-owned translation units provide that
umbrella before including exactly one implementation; each implementation starts
with its own local header (or the private shared header for a source-only split).
Sources whose standalone or compatibility header already supplies the context
compile directly. This changes include ownership, not namespaces, DTO layouts, protocol,
callbacks, or runtime policy.

Includes reaching outside the current directory use library-qualified paths,
not parent traversal: `<qwen_tts_bridge/audio.hpp>`. Umbrellas still include their
own leaves with local quoted paths, and implementations use short local header
names. This distinction does not authorize cross-domain leaf dependencies.

## Domain and subdomain graph

Umbrella and dependency paths below are relative to `src/qwen_tts_bridge/`;
own-header paths are relative to the umbrella's directory. Each row lists direct
dependencies in include order. Dependencies inherited through another umbrella
are not repeated in a leaf. No edge leads back to a higher-level consumer.

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
| `integration/speech_animation.hpp` (optional) | `client.hpp`, external `speech_animation/{integration,playback}.hpp` | `speech_animation/{adapter,playback_runtime}.hpp` |
| `native.hpp` (opt-in adapter) | none | `native/native_qwen_backend.hpp` |

`transport/stdio.hpp` supplies the byte-transport interface before the stdio
implementation; it must not include `transport.hpp` and create a parent cycle.
`native.hpp` does not import GGML/CUDA or make the normal SDK depend on the
native engine. Speech-animation remains build-tree-only; this refactor does
not add it to the installed SDK.

## Supported entry points and exceptions

All public umbrellas compile independently. Existing public entry paths remain
available as thin wrappers around the new owning umbrella:

- `playback/winmm_playback.hpp` -> `playback/winmm.hpp`;
- `integration/speech_animation/speech_animation_adapter.hpp` ->
  `integration/speech_animation.hpp`;
- `integration/speech_animation/playback_animation_runtime.hpp` ->
  `integration/speech_animation.hpp`.

Two existing value-type entry points intentionally remain standalone:

- `data/audio_types.hpp` retains a same-domain `protocol_types.hpp` include
  for `RequestId`;
- `playback/playback_cursor.hpp` obtains `RequestId` through `data.hpp`, not a
  cross-domain leaf include.

These are explicit compatibility exceptions, not a requirement to make every
internal leaf self-contained. Same-domain leaf edges remain for
`data/protocol_types -> enums`, `data/audio_types -> protocol_types`,
`client/qwen_tts_client -> client_types`, `protocol/control/control_codec ->
control_messages`, `audio/save_wav_callbacks -> post_processor`,
`audio/terminal_fade_post_processor -> post_processor`, and
`playback/playback_receipt -> playback_cursor`. The private
`control_codec_internal.hpp` includes same-directory codec/message headers and
private nlohmann JSON; it is not installed.

## Removed cross-domain leaf dependencies

The following dependency responsibilities moved to the owning umbrellas:

| Former leaf | Removed dependency paths (relative to `qwen_tts_bridge/`) |
| --- | --- |
| `protocol/control/control_messages.hpp` | `data/audio_types.hpp` |
| `protocol/framing/{frame_codec,frame_parser}.hpp` | `data/protocol_types.hpp` |
| `client/client_types.hpp` | `data/audio_types.hpp`, `data/protocol_types.hpp`, `protocol/control/control_messages.hpp` |
| `client/qwen_tts_client.hpp` | `protocol/control/control_messages.hpp`, `session/worker_session.hpp`, `transport/stdio/std_io_transport.hpp` |
| `session/worker_session.hpp` | `data/protocol_types.hpp`, `protocol/control/control_messages.hpp`, `protocol/framing/frame_parser.hpp`, `transport/i_transport.hpp` |
| `audio/playout_cursor.hpp` | `data/audio_types.hpp` |
| `audio/post_processor.hpp` | `data/audio_types.hpp`, `client/client_types.hpp` |
| `audio/save_wav_callbacks.hpp` | `client/client_types.hpp`, `data/audio_types.hpp`, `protocol/control/control_messages.hpp` |
| `playback/playback_receipt.hpp` | `data/audio_types.hpp` |
| `text/tts_front_text_preparer.hpp` | `client/client_types.hpp`, external `tts_front.hpp` |
| former `playback/winmm_playback.hpp` implementation | `audio.hpp`, `data.hpp`, `playback_cursor.hpp` supplied through the new umbrella |
| former `integration/speech_animation/speech_animation_adapter.hpp` implementation | `data/audio_types.hpp`, `client/client_types.hpp`, external `speech_animation/integration.hpp` |
| former `integration/speech_animation/playback_animation_runtime.hpp` implementation | sibling adapter and external `speech_animation/playback.hpp` |

Additionally, `transport/stdio/std_io_transport.hpp` no longer includes its
parent-domain `transport/i_transport.hpp`: the stdio umbrella supplies it.
The standalone playback-cursor exception replaces its former
`data/protocol_types.hpp` dependency with `data.hpp`.

## Verification contract

`public_header_self_contained` compiles each supported entry point in a separate
translation unit, including optional umbrellas and compatibility paths when
enabled. Two more translation units include the complete list in forward and
reverse order. Internal leaves are not separately tested as public API.

The installed CMake consumer independently compiles the stdio entry point and,
when requested, both WinMM entry paths, so a missing installed leaf cannot be
masked by another umbrella. Feature-disabled installs must not acquire optional
dependencies. Full CTest, mock playback, and optional native-worker and
speech-animation configurations remain the behavior regression gates.

## Domain translation units

The audio prototype established the two-level contract. Its five implementation
sources retain local includes such as `"playout_cursor.hpp"`; wrappers use:

```cpp
#include <qwen_tts_bridge/audio.hpp>
#include <qwen_tts_bridge/audio/playout_cursor.cpp>
```

The contract now covers every implementation under `src/qwen_tts_bridge/`,
including the optional components. The [source audit](../reports/pr273-sdk-source-audit-20261104.md)
lists all 23 implementation files, their classification and CMake mapping.
There are 18 wrappers and five direct-compilation entries. CMake compiles
wrappers instead of their included implementations, never both in one target.
Source-only control codec splits retain `control_codec_internal.hpp`; no
artificial public headers were added.

A single unity TU was intentionally rejected:
`playout_cursor.cpp` and `terminal_fade_post_processor.cpp` both define an
anonymous-namespace `formats_match`, which collides when their sources share one
translation unit. Per-source wrappers preserve symbol isolation and incremental
rebuild granularity without renaming helpers.

## Tooling context

CMake's `compile_commands.json` describes the actual wrapper TUs. Included
implementations intentionally have no separate build command. Compiler
diagnostics still refer to the original implementation, and generated dependency
information rebuilds the wrapper when that implementation changes.

clangd can infer flags from the wrapper but cannot infer its preceding umbrella
include. The repository `.clangd` supplies this context only for editor parsing
of the corresponding implementation paths; CMake uses neither forced includes
nor PCH. Configure Ninja with `-DCMAKE_EXPORT_COMPILE_COMMANDS=ON`, then start
clangd with `--compile-commands-dir=<build-directory>`. Allow the trusted local
MinGW driver through `--query-driver` when using clangd's Windows build.

The selected database must come from a configuration enabling the optional
component being edited. The native adapter needs its qwen C ABI include path;
the audit checks it separately against the test ABI without loading GGML/CUDA.
For whole-file `--check` diagnostics, `--tweaks=NoTweaks` disables clangd's
developer refactoring probes; it does not disable parsing or semantic diagnostics.
This avoids the unrelated clangd 22.1.4 ExtractFunction break/continue probe
failure recorded during the audit.
