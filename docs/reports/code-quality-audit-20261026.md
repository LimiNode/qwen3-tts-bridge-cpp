# Production code-quality audit — 2026-10-26

Status: **inventory only**. This report records evidence-backed findings and
minimal corrective proposals. It intentionally does not start a refactor.

## Scope and method

The audit sampled the largest production and example files on the audited
baseline `c4f3ee980110608befc3a8c8f87d226db8eb9eec` (the `main` tip before the
B1 closeout merge). Findings include an exact
path and line range, the observed evidence, impact, and a severity. Line
ranges refer to this commit and will need refreshing after unrelated edits.
The audit covers the C++ bridge, the Python worker, the native process worker,
and the installed public-header surface. Generated artifacts, model code
outside this repository, and style-only opinions are out of scope. The native
files below were inspected directly at the audited baseline; they are not
absent or deferred merely because the in-process adapter has a similar name.

## Native implementation coverage

The native path has three distinct ownership layers, all present in the
audited baseline:

| Layer | Files and ranges inspected | Result |
| --- | --- | --- |
| In-process C ABI adapter | `src/qwen_tts_bridge/native/NativeQwenBackend.cpp:1-167`; `NativeQwenBackend.hpp:1-115` | Callback and cancellation trampolines are `noexcept` and convert callback exceptions to a failed/cancelled native call. `qt_context` and returned audio are released on all shown paths. ABI-6 parameter initialization and finish-reason mapping are explicit. No new P0/P1 finding was promoted from this pass. |
| Native DLL loader and runtime manifest | `worker/native/qwentts/QwenDllLoader.cpp:1-137`; `runtime_manifest.cpp:146-224`; `QwenDllLoader.hpp` | Manifest validation precedes `LoadLibraryExW`; architecture, ABI, declared files and selected DLL containment are checked. Required/optional exports are separated, version is matched to the manifest, and partial loads call `unload()` before rethrowing. No new P0/P1 finding was promoted; negative manifest/export coverage remains an explicit test follow-up. |
| Native process worker | `worker/native/qwentts/NativeEngine.cpp:78-641`; `StdioServer.cpp:79-673`; corresponding headers | Voice registry/preload, request validation, cancellation callback, PCM conversion, terminalization, shutdown, writer failure and fatal-error paths were reviewed. Logical terminal state and physical engine ownership are intentionally separate. No evidence was found here for a second independent lifecycle authority; the maintainability risk is retained below as a bounded P2 concern. |

This is an evidence inventory, not a claim that every native branch has been
exhaustively model-tested. Fully inspected areas are the loader/manifest
boundary, callback trampolines, request admission/terminalization, and cleanup
paths listed above. The broad example and telemetry findings remain sampled as
described below. Hardware/model behavior and third-party `qwentts.cpp` internals
remain explicitly deferred.

## Installed public-header and ownership review

The install surface was checked in `CMakeLists.txt:309-400` and the generated
self-contained header list in `CMakeLists.txt:509-565`. Stable bridge headers
are installed without exposing `nlohmann/json` or native-worker implementation
types. The native adapter, speech-animation integration headers, and WinMM
implementation details remain opt-in/build-tree or explicitly conditional;
the installed package exports only the targets and headers selected by the
corresponding build options. The header self-containment target compiles each
installed-facing leaf as its own translation unit.

Stable public classes and cross-domain DTOs carry Doxygen-style API comments,
including ownership/blocking notes where the contract is non-trivial. There is
no separate Doxygen build gate in this baseline, so documentation completeness
is a P3 follow-up rather than a release-blocking defect. No public ownership or
dependency violation was promoted from this pass.

## Findings

### P2 — telemetry normalization is coupled to the Qwen engine

**File:** `worker/src/qwen_tts_bridge_worker/engine/qwen_engine.py:2273-2353`

`_first_chunk_timing_fields()` builds the externally emitted first-chunk
metrics and contains a long, hand-maintained list of telemetry keys alongside
numeric coercion and derived-field calculation. The caller emits this mapping
from the generation loop at lines 397-403. Adding or renaming a telemetry field
therefore requires editing the model engine and risks changing the JSON
contract while changing generation code.

**Impact:** telemetry contract drift is difficult to review and test; the
engine remains responsible for transport-facing normalization.

**Minimal corrective:** extract a small private telemetry-normalization module
with a contract-focused unit test that snapshots representative fields. Keep
the current JSON names and values byte-for-byte compatible; do not change
generation scheduling in that corrective.

### P2 — CLI parsing helpers are duplicated across examples

**Files:**

- `examples/qwen_tts_play.cpp:484-544`
- `examples/qwen_tts_latency_benchmark.cpp:335-405`
- `examples/qwen_tts_save_wav.cpp:106-151`

Each example owns near-identical `require_value`, `parse_u32`, `parse_int`, and
`parse_double` implementations. The same validation rules can consequently
drift between the playback, benchmark, and WAV paths.

**Impact:** a parsing bug fixed in one CLI can remain in the others; diagnostics
and accepted numeric syntax are not guaranteed to stay aligned.

**Minimal corrective:** introduce one private example-only parsing header/source
(not a public SDK dependency), migrate one CLI at a time, and retain focused
tests for missing values, signed integers, scientific notation, and range
errors. Keep CLI-specific option mapping in each example.

### P2 — `stdio_server` distributes lifecycle invariants across state holders

**File:** `worker/src/qwen_tts_bridge_worker/server/stdio_server.py:134-145,
260-283, 697-733, 1117-1129, 1200-1209`

Request lifecycle is represented by `_RequestSlot.state` and
`terminal_notified`, by `_active`, by `_physical`, and by the scalar
`_admitted_requests`. Cancellation removes a running request from `_active`
while retaining it in `_physical` (`worker/src/qwen_tts_bridge_worker/server/stdio_server.py:711-718`),
and a later engine-thread cleanup calls `_terminalize_locked()`
(`worker/src/qwen_tts_bridge_worker/server/stdio_server.py:1124-1126`).
This is deliberate: logical terminalization and physical engine ownership are
different states. The finding is therefore a maintainability risk, not evidence
of multiple independent lifecycle authorities or a demonstrated correctness
failure.

**Impact:** future lifecycle changes can accidentally emit duplicate terminal
events or release admission twice; the distinction between logical terminal
state and physical engine ownership is easy to break.

**Minimal corrective:** keep the existing behavior, but centralize transitions
in one private request-lifecycle helper (or a narrowly documented invariant
block) and add table-driven tests for queued cancel, running cancel, late
cancel, and shutdown. Do not collapse the logical/physical distinction.

### P2 — playback ownership, receipts, and WinMM teardown share one large unit

**File:** `src/qwen_tts_bridge/playback/winmm_playback.cpp:1-953`

The translation unit combines epoch-gated queue admission, playback metrics and
receipt serialization (roughly lines 1-343), WinMM reset/position handling
(357-526), buffer submission (680-790), and fail-closed teardown with driver
ownership retention (806-953).

**Impact:** receipt-format changes have a large review surface in the same file
as the unsafe-to-get-wrong `WAVEHDR` ownership and reset paths. This increases
the chance that diagnostic work accidentally changes teardown behavior.

**Minimal corrective:** first extract receipt/metrics formatting behind a small
private interface and preserve `WaveOutPlayer` ownership, epochs, reset, and
close in one implementation. Add no new public dependency and do not split the
teardown state machine until dedicated fault-injection coverage exists.

### P3 — the playback example is a multi-role integration executable

**File:** `examples/qwen_tts_play.cpp:1-2134`

One executable currently owns option parsing, request/callback orchestration,
PCM capture, playback diagnostics, terminal-tail handling, and optional
speech-animation receipt glue. The option parser alone spans lines 484-733,
while playback/animation option handling continues at lines 1626-1671.

**Impact:** changes to a diagnostic or presentation path require rebuilding and
reviewing a large integration file; isolated unit coverage is difficult.

**Minimal corrective:** keep the executable as composition code, but move
option parsing and PCM-capture/receipt helpers into private example modules.
Leave playback ordering and the existing playback-first assertions unchanged.

### P3 — latency benchmark duplicates product request plumbing

**File:** `examples/qwen_tts_latency_benchmark.cpp:1-1715`

The benchmark contains its own full CLI parser and request lifecycle loop,
including the same numeric parsing helpers as the playback example. It is
useful as an experiment harness, but its plumbing is not clearly separated
from the measurements it reports.

**Impact:** benchmark-only behavior can diverge from the supported CLI without
being noticed, and measurement changes can accidentally alter request setup.

**Minimal corrective:** isolate benchmark option parsing and emit a typed,
immutable benchmark configuration before starting timing. Reuse the private
example parsing module from the P2 corrective; do not make the benchmark a
runtime library dependency.

## Non-findings and deferred work

- No evidence in this inventory justifies a large architectural refactor.
- `worker/src/qwen_tts_bridge_worker/cli.py` and `config.py` were reviewed for
  parser/config ownership; no correctness or beta-blocking finding was
  promoted from that pass.
- `src/qwen_tts_bridge/client/QwenTtsClient.cpp` and
  `src/qwen_tts_bridge/session/WorkerSession.cpp` were reviewed for callback
  locking and lifecycle boundaries; the existing callback-copy-before-invoke
  pattern and mutex boundaries were retained.
- The native implementation is split deliberately between the in-process
  `NativeQwenBackend`, the native worker's `NativeEngine`/DLL loader, and
  `StdioServer`. All three layers were inspected in this inventory; no finding
  is attributed to a nonexistent file. Manifest negative cases, ABI mismatch
  injection, and full native-worker hardware acceptance remain separate test
  work.
- `request_admission_released` and logical cancellation semantics are covered
  by the existing B1 evidence; this audit does not reinterpret those results.
- Native backend files were not changed by this report; native quality
  hardening and VoiceDesign acceptance remain separate work items.

## Recommended order

1. Add lifecycle invariant tests around `stdio_server` without changing
   behavior.
2. Extract the private CLI parsing helpers.
3. Extract Qwen telemetry normalization with a compatibility snapshot.
4. Extract playback receipt formatting only after WinMM fault-injection tests
   remain green.

Each item should be an independent PR with its own exact-head CI and should not
be mixed with model acceptance or release-scope changes.
