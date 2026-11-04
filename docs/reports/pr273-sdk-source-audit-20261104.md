# PR #273: complete SDK source and translation-unit audit

Scope: all first-party `.cpp` files under `src/qwen_tts_bridge/`. This covers
the SDK and optional adapters, not the separate worker or example source trees.
The implementation policy is applied throughout that scope, not only audio.
PR #272, model acceptance and release promotion remain separate.

## Source classification and CMake mapping

Paths in the table are rooted at `src/qwen_tts_bridge/`. `Context` means the
local header requires its owning umbrella; `private` means a source-only split
uses the existing private shared header. Each wrapper includes its umbrella
and exactly one implementation using library-qualified paths without `../`.
Every implementation starts with a short local own/private-header include.

| Implementation examined | Classification / local header | CMake compilation source |
| --- | --- | --- |
| `audio/playout_cursor.cpp` | Context: `playout_cursor.hpp`, audio | `audio_domain/playout_cursor.cpp` |
| `audio/post_processor.cpp` | Context: `post_processor.hpp`, audio | `audio_domain/post_processor.cpp` |
| `audio/save_wav_callbacks.cpp` | Context: `save_wav_callbacks.hpp`, audio | `audio_domain/save_wav_callbacks.cpp` |
| `audio/terminal_fade_post_processor.cpp` | Context: `terminal_fade_post_processor.hpp`, audio | `audio_domain/terminal_fade_post_processor.cpp` |
| `audio/wav_writer.cpp` | Standalone: `wav_writer.hpp`; retain accepted audio prototype mapping | `audio_domain/wav_writer.cpp` |
| `client/qwen_tts_client.cpp` | Context: `qwen_tts_client.hpp`, client | `client_domain/qwen_tts_client.cpp` |
| `playback/playback_receipt.cpp` | Standalone through existing value-type compatibility: `playback_receipt.hpp` | Same implementation, direct |
| `protocol/control/control_codec.cpp` | Context: `control_codec.hpp`, control; also private codec header | `protocol/control_domain/control_codec.cpp` |
| `protocol/control/control_decode.cpp` | Private: `control_codec_internal.hpp`, control context | `protocol/control_domain/control_decode.cpp` |
| `protocol/control/control_encode.cpp` | Private: `control_codec_internal.hpp`, control context | `protocol/control_domain/control_encode.cpp` |
| `protocol/control/control_json.cpp` | Private: `control_codec_internal.hpp`, control context | `protocol/control_domain/control_json.cpp` |
| `protocol/control/control_validation.cpp` | Private: `control_codec_internal.hpp`, control context | `protocol/control_domain/control_validation.cpp` |
| `protocol/control/error_codec.cpp` | Private: `control_codec_internal.hpp`, control context | `protocol/control_domain/error_codec.cpp` |
| `protocol/framing/frame_codec.cpp` | Context: `frame_codec.hpp`, framing | `protocol/framing_domain/frame_codec.cpp` |
| `protocol/framing/frame_parser.cpp` | Context: `frame_parser.hpp`, framing (including codec declarations) | `protocol/framing_domain/frame_parser.cpp` |
| `session/worker_session.cpp` | Context: `worker_session.hpp`, session | `session_domain/worker_session.cpp` |
| `transport/stdio/std_io_transport.cpp` | Context: `std_io_transport.hpp`, stdio interface | `transport/stdio_domain/std_io_transport.cpp` |
| `playback/winmm_playback.cpp` | Optional compatibility: `winmm_playback.hpp` already supplies umbrella | Same implementation, direct |
| `playback/playback_interruption_diagnostics.cpp` | Optional private: `playback_interruption_diagnostics.hpp`; WinMM context completes diagnostic DTO | `playback_domain/playback_interruption_diagnostics.cpp` |
| `text/tts_front_text_preparer.cpp` | Optional context: `tts_front_text_preparer.hpp`, text | `text_domain/tts_front_text_preparer.cpp` |
| `integration/speech_animation/speech_animation_adapter.cpp` | Optional compatibility: `speech_animation_adapter.hpp` already supplies umbrella | Same implementation, direct |
| `integration/speech_animation/playback_animation_runtime.cpp` | Optional compatibility: `playback_animation_runtime.hpp` already supplies umbrella | Same implementation, direct |
| `native/native_qwen_backend.cpp` | Optional standalone: `native_qwen_backend.hpp` | Same implementation, direct |

Totals: 23 implementations, 18 one-source wrappers, five direct sources.
No wrappers were added for the standalone native/receipt or existing compatible
WinMM/speech-animation sources. The existing WAV writer wrapper is retained
from the accepted five-source audio prototype; standalone compilation remains
possible but is not needed in that target.

The core `qwen_tts_bridge` target uses 16 wrappers plus the direct receipt
source. `qwen_tts_bridge_winmm_playback` uses the direct WinMM source plus the
diagnostic wrapper. `qwen_tts_bridge_tts_front` uses the text wrapper.
`qwen_tts_bridge_speech_animation` uses its two direct compatibility sources.
The opt-in `qwen_tts_bridge_native` and its independent finish-test target use
the direct native source; compilation in distinct targets is intentional.

## Structural and tooling checks

- All 23 implementation first includes resolve to local own/private headers.
- All 18 wrapper/implementation mappings are one-to-one. In the full MinGW
  compile database, none of the wrapped implementations has a separate command.
- The 42-header first-party include graph has no cycles. Public umbrellas and
  compatibility paths compile as independent TUs and in both include orders.
- No project C++ include under `src/qwen_tts_bridge/` traverses `../`.
- GCC dependency tracking was exercised by touching the included
  `audio/playout_cursor.cpp`: its wrapper object and core archive rebuilt.
- A temporary `#error PR273_ORIGINAL_SOURCE_DIAGNOSTIC_PROBE` in that source
  produced a GCC diagnostic at `audio/playout_cursor.cpp:2:2`, with the wrapper
  shown as include context. The probe was removed immediately; no probe remains.
- clangd 22.1.4 parses all 23 original implementations with zero semantic
  errors using the appropriate compile context and the repository `.clangd`.
  The 22 normal/optional implementations use the full MinGW database; the native
  adapter uses a separate test-C-ABI database because the source-linked native
  backend is disabled in the normal SDK configuration. The native finish
  executable also builds and runs successfully against that test ABI.
- Before `.clangd`, directly opening the included audio source lost umbrella
  declarations (11 semantic errors). Editor-only context fixes that; no forced
  includes or PCH were added to CMake. Whole-file `--check` uses
  `--tweaks=NoTweaks` to skip unrelated developer refactoring probes: the default
  ExtractFunction probe reports three break/continue extraction failures even
  after semantic parsing succeeds. These are not suppressed compiler errors.

Tooling reproduction, with a trusted local GCC driver and a configured Ninja
build directory:

```text
cmake -S <worktree> -B <build> -DCMAKE_EXPORT_COMPILE_COMMANDS=ON
clangd --check=<implementation.cpp> --compile-commands-dir=<build> --query-driver=<trusted-driver> --tweaks=NoTweaks
```

The actual database describes wrappers. The `.clangd` path filters provide
umbrella context only to their included implementations; direct native,
receipt and compatibility sources do not need such filters. Optional components
must be enabled in the selected database; this does not make disabled features
or arbitrary internal leaves independently supported.

## Local validation and MinGW differential result

Windows x64, MinGW GCC 15.2.0 (posix/seh/msvcrt), C++17, Ninja, Release
(`-O3 -DNDEBUG`), Python 3.11.9. No local MSVC installation is available.

- Full examples/frontend/WinMM/speech-animation/native-process-worker build:
  PASS. Full CTest: **32/33 PASS**, native-worker failed; this is not a green
  MinGW suite. The mock playback, audio, frontend, protocol and client/session
  tests passed in this complete run.
- Minimal examples/frontend/WinMM/speech-animation/native-worker OFF build:
  PASS; CTest **12/12 PASS**.
- Fresh full and minimal installs plus external CMake consumers:
  configure/build/run PASS. Full consumer enables WinMM and frontend and
  separately compiles both WinMM public paths and the stdio entry point.
- The native finish test against the test ABI builds/runs PASS; no GPU,
  qwentts/GGML runtime or model acceptance is claimed by that test.

Native-worker differential baseline is exact PR base
`b036642ed4c9ede66b94c7d044b6839f3246976f`. Both builds use the same compiler,
Release flags, dependency source revisions, enabled options, inherited test
environment, CTest command, and unmodified 60-second test timeout. Runs are
sequential, alternating baseline and PR. Source/build/fixture directory paths
differ necessarily; no attempt was made to turn those into identical binaries.

| Run | Observed native-worker result |
| --- | --- |
| Complete PR suite | Raw request-ID probe fails waiting for terminal/error for ID 100; outer assertion at line 535 |
| Baseline repeat 1 | Same ID-100 wait condition; outer raw request-ID assertion at line 535 |
| PR repeat 1 | `history_probe.completed == 1` at line 679, then CTest timeout at 60.09 seconds |
| Baseline repeat 2 | Wait for error for ID 42; outer raw request-ID assertion at line 535 |
| PR repeat 2 | Wait for error for ID 2; outer raw admission assertion at line 536 |

Conclusion: **INCONCLUSIVE**. Failures are reproducible on both revisions but
the symptoms differ; no common root cause or absence of a PR-specific effect
has been established. This supersedes the earlier overly strong
"no regression" characterization. Do not mix native lifecycle fixes or timeout
changes into this structural PR. Exact-head MSVC CI is a separate gate, not a
substitute for reporting this MinGW failure.

Raw local logs, fresh install trees and the test-ABI tooling harness are under
`E:\_repoz\qwen3-tts-bridge-cpp\.tmp\umbrella-dependency-policy\`;
all build outputs are under the repository's `.build/umbrella-*` profiles.
These ignored payloads are not independently reviewable through GitHub; the
tracked summary above distinguishes results from unresolved diagnosis.

No runtime bodies, DTO layouts, namespaces, PCM bytes, JSON schema, callbacks,
worker lifecycle, model pins or release gates changed. Keep PR #273 Draft;
the final exact-head MSVC run and revision are recorded in its PR description.
