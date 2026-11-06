# Native worker stdout `WriteFile` corrective report

Date: 2026-11-05

Initial base revision: `c04f7898` (local `main` at the start of this work)

Validation base: `b036642e` (`origin/main`, after rebase)

Worktree: `fix/native-stdout-writefile`

## Scope

The native worker now publishes each complete QTB frame through a small
Windows `WriteFile` helper. The helper keeps writing until the whole frame is
published, reports the number of bytes accepted on failure, rejects invalid
handles, and treats a successful zero-byte write as a write fault.

The existing bounded output queue, writer thread, drain-on-shutdown behaviour,
and stderr-only diagnostics remain in place. No protocol frame layout or
worker lifecycle state was changed.

Two tests cover the boundary:

- `native_stdout_write_contract_test` writes a 2 MiB payload through an
  anonymous pipe and compares every received byte with the source payload.
- `native_stdout_pipe_integrity_test` starts the fake native worker through
  anonymous stdin/stdout/stderr pipes, sends `Hello`, requests `100` and `101`,
  waits for both short fake syntheses, sends a late `Cancel` for `100`, and
  shuts the worker down. It parses the complete stdout byte stream and checks
  the expected frame count, four PCM frames, two terminal events, no error
  frames, and the shutdown acknowledgement.

Both test harnesses own their process, pipe handles, and reader threads. An
early assertion therefore terminates an owned child, joins readers, and closes
only handles created by that test.

## Corrective verification (2026-11-06)

The regression harness was tightened without changing the native worker:

- `native_stdout_pipe_integrity_test` now drives the original timing-sensitive
  sequence: `hello`, two back-to-back syntheses (`100`, `101`), bounded delay,
  late `cancel(100)`, bounded delay, and `shutdown` without waiting for
  terminal events first;
- the case is repeated ten times, rejects parser fatal errors, and requires
  `FrameParser::buffered_size() == 0` at EOF;
- truncated headers, truncated payloads, and incomplete trailing bytes are
  explicit negative parser cases;
- every control and error payload is decoded; `Ready`, `ShutdownAck`, queue
  events, starts, terminal events, and request IDs are checked without relying
  on scheduling-dependent frame order;
- PCM frames are restricted to request IDs `100`/`101`, the expected fake
  runtime `s16le` format, and the two known fake PCM chunks;
- `native_stdout_write_contract_test` now closes the anonymous-pipe read end
  and verifies a failed `WriteFile` returns zero progress, a non-success
  Win32 error, and no handle/liveness regression.

The focused MinGW run passed:

```text
native_stdout_write_contract_test       Passed
native_stdout_pipe_integrity_test      Passed (10 timing repetitions)
2/2 tests passed
```

The configured MinGW CTest suite also passed after the corrective:

```text
17/17 tests passed, 0 failed
Total Test time: 90.27 s
```

For direct regression relevance, the diagnostic worker at the pre-`WriteFile`
revision was run with the exact same capture sequence ten times. Strict raw
stdout validation produced:

| implementation | valid raw streams | valid publication records | raw equals publication |
| --- | ---: | ---: | ---: |
| old iostream writer | 1/10 | 10/10 | 0/10 |
| diagnostic `WriteFile` writer | 10/10 | 10/10 | 10/10 |

Thus the bounded integration test exercises the timing that reproduced the
old defect and fails closed on the same malformed stream class; the historical
diagnostic comparison demonstrates that the old iostream implementation does
not pass that sequence reliably. The comparison artifacts remain local under
`.tmp/native-stdout-writefile-corrective-comparison/` and are not release
evidence.

## Verification

Configuration and build used the MinGW Windows toolchain:

```text
cmake -S .worktrees/native-stdout-writefile -B .worktrees/native-stdout-writefile/.build/native-stdout-writefile-mingw -G Ninja -DCMAKE_BUILD_TYPE=Release -DQWEN_TTS_BRIDGE_BUILD_TESTS=ON -DQWEN_TTS_BRIDGE_BUILD_QWENTTS_WORKER=ON -DQWEN_TTS_BRIDGE_BUILD_EXAMPLES=OFF -DQWEN_TTS_BRIDGE_BUILD_NATIVE_BACKEND=OFF -DQWEN_TTS_BRIDGE_BUILD_TTS_FRONT=OFF -DQWEN_TTS_BRIDGE_BUILD_SPEECH_ANIMATION=OFF
cmake --build .worktrees/native-stdout-writefile/.build/native-stdout-writefile-mingw --parallel 4
```

The focused stdout checks completed successfully:

```text
native_stdout_write_contract_test       Passed
native_stdout_pipe_integrity_test      Passed
2/2 tests passed
```

The existing `qwen_tts_native_worker_test` also completed successfully on the
same worker and fake runtime (`25.21 s`). The complete configured CTest set
completed successfully in the initial documentation-only pass:

```text
17/17 tests passed, 0 failed
Total Test time: 82.41 s
```

The existing `examples/common/pcm_capture.hpp` already contains the direct
`<string>` include and describes sequential PCM/metadata publication with
rollback at this base revision; no unrelated change was needed for that
review note.

## Limits

This is a Windows MinGW/fake-runtime verification. It does not claim MSVC
toolchain coverage, real model synthesis, CUDA behaviour, or hardware
acceptance. Those remain separate checks.
