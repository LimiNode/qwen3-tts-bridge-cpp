# R1 corrective closeout — local candidate

Status: **conditional / NO-GO for release promotion**. This receipt records a
reviewable local candidate; it is not a tag, GitHub release, or support claim.

## Exact source and automated verification

- Integration branch: `integration/r1-corrective`
- Final production source candidate:
  `ea9ceaf2` (the lifecycle, protocol-contract, provenance and test-environment
  corrective follows the bounded diagnostics baseline).
- Tested PR/integration HEAD:
  `0c78f56b` (receipt-only documentation follows the production candidate).
- Bounded diagnostics production baseline:
  `9a4525db` (decouples diagnostics from inference with a bounded best-effort
  writer).
- The corrective source commits include `cbd58ef3`, `e8806e9b`, and
  `92a2dd53`, `7131d78d`, `9a4525db`, `43963b1b`, `e5241096`, and
  `ea9ceaf2`; Python lint/type corrective commits are `34945218`, `6ce6441b`,
  and `4598d032`.
- The existing package evidence predates this final source corrective and is
  therefore historical only; it must be regenerated before any release
  decision.
- Corrective commits include native admission/shutdown/package fixes,
  frontend-aware native defaults, and idempotent recovery of incomplete native
  voice publications.
- MSVC Release CTest with `BUILD_EXAMPLES=ON`, `BUILD_TESTS=ON`, and explicit
  `QWEN_TTS_BRIDGE_ENABLE_TEST_HOOKS=ON`: **46/46 PASS**.  The focused
  corrective subprocess suites (`qwen_tts_native_worker_test`,
  `stdio_transport_test`) also pass after the latest source changes.
  The previous failure was the forced-termination recovery path; the new
  bounded recovery handles transient Windows path/handle races and disposable
  incomplete artifacts fail closed without touching a committed manifest.
- Full model-free Python suite: **502 tests, 7 skipped, OK** with
  `PYTHONPATH=worker/src`; Pyright reports **0 errors, 0 warnings, 0
  informations**; Ruff **PASS**.
  The focused corrective lifecycle/packaging suites and
  `validate-acceptance-receipts.py` also pass, including validation of 2
  canonical receipts.
- Native packaging contract tests: **12/12 PASS**, including a real PE32+
  fixture with normal imports, delay imports, recursive dynamic-module
  traversal, and a missing transitive dependency.  The test exercises the
  production PE parser without replacing `_imports()`.
- Native publication/recovery qualification: `qwen_tts_native_worker_test`
  passed in **3 consecutive Release runs** after the corrective changes.
- Native fatal delivery under a stalled stderr consumer passed with three
  accepted requests: the active request received its internal terminal error
  and both pending requests received `worker_fatal` before diagnostics were
  released. The full native worker test uses a 120-second CTest budget.
- Direct Windows-pipe diagnostics regressions pass with stderr intentionally
  unread and at least 4096 bytes buffered before requests are submitted: two
  multi-chunk natural-EOS requests complete, and cancellation plus shutdown
  remain bounded. This proves protocol progress with a no-reader diagnostic
  backlog; it does not claim to observe the writer thread's internal blocked
  state. Diagnostics use a finite 64-record/4 MiB queue; shutdown waits at
  most 250 ms for it and drops records when full or closed.
- The direct-pipe streaming assertions require `Completed`,
  `execution_outcome: natural_eos`, `generation_trace.hit_eos`, and at least
  two PCM frames for both requests. The cancellation case waits for the fake
  engine's barrier-ready marker, then uses its release barrier and requires
  `Cancelled` for the active request and natural-EOS `Completed` for the queued
  request. The harness accounts for terminal and post-terminal frames across
  all observed request IDs while draining shutdown output.
- `tts-front-cpp` is pinned to focused upstream fix commit `64f73182`
  (`fix(russian): agree feminine book counts`). Its complete upstream Release
  corpus passed **12/12**, including feminine and masculine count cases. The
  bridge does not perform string substitution.
- The production Release worker was built with `BUILD_TESTS=OFF` and
  `QWEN_TTS_BRIDGE_ENABLE_TEST_HOOKS=OFF`; binary-string inspection found no
  `QTB_TEST_PUBLICATION`, `QTB_TEST_RECOVERY`, or `QTB_TEST_PERSISTENCE` seams.
  The separate instrumented worker intentionally contains those hooks for
  deterministic recovery tests.

## CTest configuration inventory

The reported `46/46` and `26/26` counts are different CMake configurations,
not a regression. Both were configured with `CMAKE_BUILD_TYPE=Release`,
`QWEN_TTS_BRIDGE_BUILD_TESTS=ON`, and
`QWEN_TTS_BRIDGE_ENABLE_TEST_HOOKS=ON`:

| Configuration | `QWEN_TTS_BRIDGE_BUILD_EXAMPLES` | `ctest -N` | Result |
| --- | ---: | ---: | --- |
| full native-first | `ON` | 46 | 46/46 PASS |
| no-examples | `OFF` | 26 | 26/26 PASS |

The 20 tests present only in the full configuration are the example and
example-driven suites: `latency_benchmark_boundaries_test`,
`qwen_tts_play_options_test`, `tts_front_bridge_adapter_test`,
`tts_front_effective_text_corpus`, `qwen_tts_save_wav_mock_cleanup`,
`qwen_tts_save_wav_mock_example`, `qwen_tts_save_wav_mock_verify`,
`qwen_tts_save_wav_generation_trace_receipts`, `qwen_tts_save_wav_output_safety`,
`qwen_tts_voice_design_wrapper_mock`, `qwen_tts_latency_benchmark_mock_example`,
`qwen_tts_latency_benchmark_manifest_mock`, `qwen_tts_latency_benchmark_eos_contract`,
`qwen_tts_latency_benchmark_reference_warmup_mock`, `qwen_tts_play_mock_utf8_example`,
`qwen_tts_play_mock_playback_metrics`, `qwen_tts_play_mock_pcm_capture`,
`qwen_tts_play_mock_playback_failure`, `qwen_tts_play_mock_wav_capture_failure`,
and `qwen_tts_playback_lifecycle_self_test`.

The no-examples configuration therefore omits only targets guarded by
`QWEN_TTS_BRIDGE_BUILD_EXAMPLES`; it does not disable the core transport or
native-worker tests.

## Native package measurement

The package below was assembled from an earlier committed Release candidate at
implementation revision `edb483a5f13f6907fae207630de07691c95fa2eb` and the
pinned qwentts runtime (`130cb99`, ABI 6). It is retained as historical
evidence; the final package must be regenerated from source candidate
`92a2dd53` and the final packaging-script revision.

| Artifact | Result |
| --- | --- |
| ZIP | 435,248,526 bytes |
| Unpacked tree | 573,042,652 bytes, 21 files |
| ZIP SHA-256 | `5027CE22F9859EF3EA9FD8D231A8C04006B1B19D9E6C7F297E413347BBF3D763` |
| Python/PyTorch bundled | no |
| GGUF weights or user recordings bundled | no |
| PE dependency closure and extraction verification | PASS |

The review-only package is in the ignored local path
`.tmp/r1-native-package-faf54601.zip`; the previous package remains historical
evidence.  No release tag or GitHub release was created.
They are evidence, not release assets.

## PR #321-#326 coverage

| Earlier PR | Final-tree disposition |
| --- | --- |
| #321 native portable packaging | Integrated and reworked in the current packaging/manifest and audit paths. |
| #322 stale transport sends | Integrated through the later transport corrective history; the current transport tests cover the superseding implementation. |
| #323 callback boundary | Integrated through the current callback/session implementation and CMake test wiring. |
| #324 acceptance schemas | Integrated through the current schema and validator revisions. |
| #325 bounded stdout | Runtime implementation integrated; the missing protocol backpressure contract is restored in `docs/protocol-v1.md`. |
| #326 lifecycle corrective | Later stop-ownership code is retained; the omitted `WorkerSession` destructor exception boundary and throwing-transport regressions are restored in the current corrective. |

No unique implementation from #321-#325 is intentionally left only on its old
branch. Those PRs should be closed as superseded only after #327 is merged;
#326 likewise remains historical and must not be merged separately.

## Remaining gates

R1 remains NO-GO until all of the following are independently recorded for the
same frozen package/source/runtime/model identities:

- clean relocation real-model synthesis outside the checkout;
- CMP 50HX and RTX 4090 native qualification, including repeat/cancel/restart,
  physical playback and peak-memory measurements;
- matched RU/EN A/B WAV corpus and human listening;
- review-only GitHub CI for the exact tested corrective PR HEAD `0c78f56b`;

CustomVoice Python/BF16 observations remain a separate optional capability gate
and do not promote native Base/RU-stress support.

## Corrective supersession

The upstream frontend gate is closed by pinned `tts-front-cpp` fix `64f73182`;
its complete Release corpus passed 12/12 and the bridge corpus now expects the
correct feminine agreement. The remaining release gates are final package
regeneration from `ea9ceaf2`, clean relocation with real models, CMP 50HX and
RTX 4090 native qualification, matched A/B WAV listening, and review-only CI
on `0c78f56b`.
