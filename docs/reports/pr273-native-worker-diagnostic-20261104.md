# PR #273 native-worker diagnostic pass

Date: 2026-11-04
Scope: diagnostic harness only; no production behavior changes. The native
worker sources contain bounded diagnostic instrumentation guarded by the
`QWEN_TTS_NATIVE_FRAME_DIAGNOSTIC` CMake option, which defaults to `OFF`.

The preservation commit for the original diagnostic harness is `907bea65`.
Capture instrumentation described below is diagnostic-only and is not part of
PR #273.
The stdout-boundary follow-up is `c3250c73150c6d9fafcc3fca6cf820aa63b58298`.

## Revisions and setup

| Variant | Revision |
| --- | --- |
| baseline | `b036642ed4c9ede66b94c7d044b6839f3246976f` |
| PR #273 | `bc41e3d87fe3d4a6323bed27698db26ac2665e66` |

Both variants were built with MinGW GCC 15.2.0, Ninja, `Release`, the native
worker test enabled, and the same fake native runtime. The PR diagnostic build
is `E:\_repoz\qwen3-tts-bridge-cpp\.build\pr273-native-harness`; the baseline
build is `E:\_repoz\qwen3-tts-bridge-cpp\.build\pr273-native-harness-baseline`.

The complete logs are retained under
`E:\_repoz\qwen3-tts-bridge-cpp\.tmp\umbrella-dependency-policy\`.

## Harness corrections

The diagnostic branch changes `Probe` to a `std::shared_ptr<ProbeState>` and
captures that state by value in every asynchronous callback. This removes the
potential callback-to-destroyed-stack-state reference. Callback errors now
record and print `request_id`, `category`, `code`, and `message`. The same
harness correction was applied to both revisions.

The existing `CHECK` macro returns from the current test function; it does not
call `std::exit()`. Returning therefore runs the local `RawNativeWorker` and
`QwenTtsClient` destructors. No native worker process remained after the
diagnostic runs.

## CMake guard

`cmake/qwen_tts_bridge_wrapper_guard.cmake` was configured for the PR source
targets and rejects a target that compiles a wrapper together with its included
implementation or maps two wrappers to one implementation. The negative
fixture `wrapper_source_guard_negative` completed successfully (the fixture
configure failed with the expected diagnostic). The positive fixture
`wrapper_source_guard_positive` also completed successfully, proving that one
implementation may be mapped in two independent targets. A minimal PR
configure with optional components and tests disabled completed successfully.
Full optional-target configuration with MinGW completed successfully. Full
optional-target configuration with Visual Studio 17 2022 / MSVC 19.44
(`E:\_repoz\qwen3-tts-bridge-cpp\.build\pr273-msvc-full-configure`) completed
successfully; no MSVC build was run.

The guard is specific to the PR's wrapper-TU layout; the older baseline layout
does not contain those wrapper directories and was not forced through that
layout-specific check.

## Repeated native-worker runs

The focused command was:

```text
ctest --test-dir <build> -R ^qwen_tts_native_worker_test$ --output-on-failure
```

The first baseline and PR logs were collected before the diagnostic-only
raw-test result collector was added; later runs use the collector so that the
Probe stages can still execute after a raw-stage failure. After the
`RawNativeWorker::wait_for_frame()` correction, a matching queued frame is
reported as delivered even when a later parser error is already sticky. The
overall test remains failed; malformed bytes are not hidden.

| Variant | Log | Result |
| --- | --- | --- |
| baseline | `diagnostic-baseline-run1.log` | PASS, 25.24 s |
| baseline | `diagnostic-baseline-run2.log` | SegFault, 12.39 s |
| baseline | `diagnostic-baseline-run3.log` | timeout at 60.07 s |
| baseline | `diagnostic-baseline-run4.log` | timeout at 60.07 s |
| PR #273 | `diagnostic-pr-run1.log` | failure, 0.56 s |
| PR #273 | `diagnostic-pr-run2.log` | failure, 23.17 s |
| PR #273 | `diagnostic-pr-run3.log` | timeout at 60.07 s |
| PR #273 | `diagnostic-pr-run4.log` | failure, 52.33 s |
| PR #273 | `diagnostic-pr-run5.log` | timeout at 60.07 s |
| PR #273 | `diagnostic-pr-run6-observability.log` | timeout at 60.09 s |
| baseline | `diagnostic-baseline-run5-observability.log` | SegFault, 11.61 s |

Both variants exhibit the same failure class during the raw native request-ID
sequence: the parser reports `invalid frame magic` after valid frames have
already been received. Later Probe-based runs report a protocol parse error
while a binary `QTB1` frame is being interpreted as JSON, for example:

```text
category=protocol_error
code=protocol_error
message=[json.exception.parse_error.101] ... control character U+0001 ... 'sample_QTB1...'
```

The baseline reproduces this after one successful run, and the PR reproduces
it as well. The evidence does not isolate a PR-specific semantic regression;
the native-worker acceptance remains `INCONCLUSIVE` for the long CTest route.
The baseline `SegFault` is retained as a separate harness-lifetime signal; the
`shared_ptr<ProbeState>` correction protects the probe callbacks, but does not
by itself prove safe cleanup for every asynchronous object or early-return path.

## Minimal byte-level reproducer

The standalone capture command is:

```text
python E:\_repoz\qwen3-tts-bridge-cpp\.worktrees\pr273-native-harness\scripts\diagnostic\native_worker_frame_capture.py `
  --worker E:\_repoz\qwen3-tts-bridge-cpp\.build\pr273-native-harness\qwen_tts_native_worker.exe `
  --runtime-dir E:\_repoz\qwen3-tts-bridge-cpp\.build\pr273-native-harness\native-fake-runtime `
  --manifest-path E:\_repoz\qwen3-tts-bridge-cpp\.build\pr273-native-harness\native-fake-runtime\manifest.json `
  --talker-model E:\_repoz\qwen3-tts-bridge-cpp\.build\pr273-native-harness\native-fake-runtime\talker.gguf `
  --codec-model E:\_repoz\qwen3-tts-bridge-cpp\.build\pr273-native-harness\native-fake-runtime\codec.gguf `
  --output-root E:\_repoz\qwen3-tts-bridge-cpp\.tmp\umbrella-dependency-policy\frame-captures\pr273-pair-instrumented-memory `
  --two-requests
```

The worker must be configured with
`-DQWEN_TTS_NATIVE_FRAME_DIAGNOSTIC=ON`; the option is disabled by default for
ordinary builds.

It sends `hello`, two synthesis requests (`100` and `101`), `cancel(100)` and
`shutdown`, while saving the exact bytes received from the child's stdout before
any parser call. The worker-side diagnostic boundary records the complete
frames intended for publication in `publication.bin`. The offline validator is
`scripts/diagnostic/validate_qtb_capture.py`; it never resynchronizes after a
framing error.

Representative PR capture:

- stdout: `E:\_repoz\qwen3-tts-bridge-cpp\.tmp\umbrella-dependency-policy\frame-captures\pr273-pair-instrumented-memory\run-1793813985572384100-90088\stdout.bin`
- stdout SHA-256: `9ba13fc7f5d8b0dfbea19fa2df92f0efe1acc96a93cd2c6f493c4112579c9611`
- size: 1313 bytes
- first invalid offset: 1022
- observed bytes: `22 3a 7b 22` (expected `QTB1`)
- preceding frame: request `101`, `ControlJson`, declared payload 100; nested `QTB1` at offset 984
- publication records: 12 valid frames; concatenated SHA-256 `ca7fcf70024b359f800363d0dda905520979074640fc130e4dd78d459fecb8db`

Representative baseline capture:

- stdout: `E:\_repoz\qwen3-tts-bridge-cpp\.tmp\umbrella-dependency-policy\frame-captures\baseline-pair-instrumented-memory2\run-1793814133120423300-48384\stdout.bin`
- stdout SHA-256: `9d9b21d2d9a0642b5a7e24be857db863397583b6324235aae3522ff67025a63d`
- size: 1189 bytes
- first invalid offset: 898
- observed bytes: `22 3a 7b 22` (expected `QTB1`)
- preceding frame: request `101`, `ControlJson`, declared payload 100; nested `QTB1` at offset 860
- publication records: 12 valid frames; concatenated SHA-256 `0504eee731ba3f7624a1d509b93451c0c7c9c622befa41517c86ebbf81af475c`

With the diagnostic `QTB_NATIVE_SYNC_STDIO=1` switch, both revisions produced
valid streams in 5/5 runs. Representative PR stdout SHA-256 is
`f2c718f02437ecfe42bee0c02f2b6529bf445e21be0d831e845ee415c7a182b1`, equal to
the concatenated publication digest. This is a controlled correlation, not an
accepted production fix: no runtime change was made to PR #273.

## Publication-versus-reception classification

Repository search of the exercised native-worker sources found one stdout
publication site:
`StdioServer::OutputWriter::run()` calls `std::cout.write()` and `flush()`.
No additional writer was found in the linked qwentts sources or the exercised
fake runtime by that search. The publication records are valid complete frames,
while the parent-side pipe capture is malformed in the same run. Therefore the
observed case is **B: valid intended publication, different bytes received by
the parent**. The evidence localizes the fault to the `std::cout`/CRT/pipe
boundary, not to `FrameParser` or JSON decoding. `std::ios::sync_with_stdio(false)`
is a supported diagnostic lead, but causality is not yet proven independently
of the timing-sensitive capture.

## Disposition

- Harness lifetime correction: confirmed in the diagnostic branch.
- Full callback diagnostics: confirmed in the diagnostic logs.
- Raw capture and offline validator: passed; malformed stream offsets and
  publication digests are recorded.
- Wrapper guard, negative fixture and positive fixture: passed.
- MinGW and MSVC full configure checks: passed; MSVC build not run.
- Native-worker baseline-vs-PR comparison: `INCONCLUSIVE`; no PR-specific
  regression proven.
- PR #273 remains Draft and must not be merged on the basis of this pass.

The next corrective work is a separate diagnostic/engineering PR for the
`std::cout`/CRT/pipe publication boundary. It must first establish a minimal
write-completion reproducer and then choose the smallest production-safe write
primitive or buffering policy. Do not change PR #273 based solely on the
`sync_with_stdio(true)` correlation.

## Follow-up boundary experiment (2026-11-05)

The diagnostic worker was rebuilt from this branch with
`-DQWEN_TTS_NATIVE_FRAME_DIAGNOSTIC=ON`. The harness fixes the diagnostic
session identifier to `diagnostic-session` so the ready frame does not vary with
the process ID. The immediate two-request sequence was run ten times per
variant under
`E:\_repoz\qwen3-tts-bridge-cpp\.tmp\umbrella-dependency-policy\frame-captures\boundary-variants-10`:

The base command is the existing capture command with `--two-requests`; B adds
`--sync-stdio`, and C adds `--writefile-stdout`. The latter selects the
diagnostic-only `QTB_NATIVE_WRITEFILE_STDOUT=1` environment path and leaves
`sync_with_stdio(false)` unchanged.

| Variant | stdout valid | publication records valid | writer traces | Result |
| --- | ---: | ---: | ---: | --- |
| A: `sync_with_stdio(false)`, `iostream` | 3/10 | 10/10 | 10/10, 12/12 successful | corruption reproduced |
| B: `sync_with_stdio(true)`, `iostream` | 10/10 | 10/10 | 10/10, 12/12 successful | no corruption |
| C: `sync_with_stdio(false)`, exclusive `WriteFile` | 10/10 | 10/10 | 10/10, 12/12 successful | no corruption |

For every run, the publication records contain the same number of complete
frames as the writer trace. In A, the trace reports successful iostream
operations for all 12 frames even when the parent capture is malformed. This
is a stream-level status, not proof that the same bytes reached the OS pipe.
In C, every `WriteFile` call completed the entire frame; partial writes are
looped and zero-progress or failed writes terminate the writer.

Representative A capture:

- stdout: `E:\_repoz\qwen3-tts-bridge-cpp\.tmp\umbrella-dependency-policy\frame-captures\boundary-variants-10\A-default\run-1793855769720950900-44144\stdout.bin`
- stdout SHA-256: `54f00cdb4a10bc9e1ac91025e986b792c57a6401627fb38bd33b5020d0fe159f`
- publication-concatenated SHA-256: `7c784caf2ce34bfca20dcf7c56f8bdaf4fbb94af0873c657b45717c98e5e6ba2`
- parent bytes: 1184; intended bytes: 1098
- first byte difference against intended concatenation: offset 855
- parser first invalid header offset: 893, observed `22 3a 7b 22` instead of `QTB1`
- last unaffected frame: request 100 `completed`, ending at offset 769
- first affected frame: request 101 `started`, with nested `QTB1` at offset 855

Representative B capture has stdout SHA-256 equal to its publication-
concatenated SHA-256:
`7c784caf2ce34bfca20dcf7c56f8bdaf4fbb94af0873c657b45717c98e5e6ba2`.
Representative C capture has equal raw/publication SHA-256
`d8a84b721bd76dcb5575dd0e041b3e9e682c463c9b16f8059778cfc82dc841b4`.

The immediate sequence has a scheduler-dependent `queued.position` field, so
publication SHA-256 values are not identical across all runs. The byte-for-
byte comparison is therefore made within each run: raw stdout is compared with
that run's own publication concatenation. A staggered sequence
(`--stagger-requests`) produced valid streams in all 9/9 runs, which confirms
that timing is a required condition for the observed corruption but does not
identify which buffering boundary loses or duplicates bytes.

### Current conclusion

The evidence now distinguishes the layers more sharply:

1. `OutputWriter` serialization and frame ordering are correct for the tested
   runs; its diagnostic trace records all 12 successful frame writes.
2. With `iostream` and `sync=false`, the parent receives a stream that differs
   from the serialized frames, including an inserted nested frame and an 86-byte
   length increase in the representative run.
3. The same workload with `sync=true` or with an exclusive `WriteFile` path is
   byte-for-byte identical to the publication records in the tested samples.

This is strong evidence for an iostream/CRT stdout boundary defect under the
concurrent timing pattern, but it is not yet a complete causal proof for every
possible writer or Windows runtime configuration. The smallest justified
production candidate is the exclusive `WriteFile` path, to be implemented only
in a separate engineering PR with a deterministic regression test. The
diagnostic branch itself remains separate from PR #273.

## Validation of the follow-up branch

- MinGW diagnostic build with `QWEN_TTS_NATIVE_FRAME_DIAGNOSTIC=ON`: worker and
  native test targets built successfully.
- MinGW feature-disabled build with the option explicitly `OFF`: worker built
  successfully; only the pre-existing `-Wsubobject-linkage` warnings appeared.
- Wrapper guard CTest (`wrapper_source_guard_negative` and
  `wrapper_source_guard_positive`): 2/2 passed.
- Offline validator: all 30 boundary captures had valid publication records;
  raw stdout was valid for 23/30 runs (3/10 in A, 10/10 in B, 10/10 in C).
- The long `qwen_tts_native_worker_test` remained `INCONCLUSIVE`: one MinGW
  run timed out at 60.09 seconds after reproducing `invalid frame magic`.
- MSVC build and exact-head CI for this diagnostic branch were not run locally;
  the branch remains diagnostic-only and is not merged into `main`.
