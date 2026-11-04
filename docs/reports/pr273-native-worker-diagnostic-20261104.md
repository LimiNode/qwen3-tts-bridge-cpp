# PR #273 native-worker diagnostic pass

Date: 2026-11-04  
Scope: diagnostic harness only; no production runtime or worker changes.

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
configure failed with the expected diagnostic). A minimal PR configure with
optional components and tests disabled also completed successfully.

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
Probe stages can still execute after a raw-stage failure.

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

Both variants exhibit the same failure class during the raw native request-ID
sequence: the parser reports `invalid frame magic` after valid frames have
already been received. The queued frames include the request-100 terminal
frame, but `RawNativeWorker::wait_for_frame()` treats the later parser error as
fatal. Later Probe-based runs report a protocol parse error while a binary
`QTB1` frame is being interpreted as JSON, for example:

```text
category=protocol_error
code=protocol_error
message=[json.exception.parse_error.101] ... control character U+0001 ... 'sample_QTB1...'
```

The baseline reproduces this after one successful run, and the PR reproduces
it as well. The evidence does not isolate a PR-specific semantic regression;
the native-worker acceptance remains `INCONCLUSIVE` because the shared test
route is unstable in this environment.

## Disposition

- Harness lifetime correction: confirmed in the diagnostic branch.
- Full callback diagnostics: confirmed in the diagnostic logs.
- Wrapper guard and negative fixture: passed.
- Native-worker baseline-vs-PR comparison: `INCONCLUSIVE`; no PR-specific
  regression proven.
- PR #273 remains Draft and must not be merged on the basis of this pass.

The next discriminating check is a separate investigation of native worker
stdout publication/frame serialization (including the `invalid frame magic`
condition), with a minimal reproducer that does not combine raw request-ID and
long Probe sequences.
