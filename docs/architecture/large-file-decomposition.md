# Large-file responsibility audit

Baseline: `1cd7cb74cecb93b86feb7b834cc89bc243b14da4` (PR #301).
Scope: tracked first-party C++ and Python files larger than 30,000 bytes in
`src/`, `examples/`, `worker/`, and `tests/`; dependencies and generated output
are excluded. Size selects candidates for inspection, not a splitting target.

## Selected batch

Each row is an independent draft PR from the same baseline. None requires a
new public SDK surface, changed CLI, protocol, runtime profile, or model policy.

| Owner at baseline | Responsibilities and extracted boundary | Dependencies after extraction | Risk and regression checks |
| --- | --- | --- | --- |
| `examples/qwen_tts_play.cpp` (87,900 B) | CLI/options and validation; console encoding/input; interactive controls; request terminal transitions; lifecycle self-test. Keep playback callbacks and application composition together. | Private `play.hpp` supplies SDK umbrellas and example-owned options/state. Options and commands do not own worker/playback lifetime. The self-test calls the same state transitions as the executable. | Low–medium: UTF-8, CLI errors, interactive capability gates, mock playback/capture, cancellation, and optional speech animation. |
| `worker/src/qwen_tts_bridge_worker/voice_library.py` (55,909 B) | Separate native preparation subprocess/protocol I/O into `voice_native_prepare.py`. Keep registry publication, artifact verification, path safety, and preparation orchestration in their existing owner. | Registry facade and native I/O share one `voice_library_errors.py` error type; native I/O never imports the facade. Preserve the existing public functions and the patched `_run_native_prepare` name by importing the same callable. | Medium: native timeout, stderr bound, structured preparation evidence, manifest verification, atomic publication, and CLI tests. No real GGUF is required. |
| `worker/src/qwen_tts_bridge_worker/engine/qwen_engine.py` (103,323 B) | Extract standalone prefill warmup operations/snapshot checks, RNG preservation/seeding, and chunk telemetry into existing `engine/qwen/`. Keep model ownership, warmup orchestration, streaming, cancellation, and request validation in `QwenTtsEngine`. | Engine coordinates `prefill_warmup.py`, `rng.py`, and `telemetry.py`; shared `errors.py` has no dependency back to engine orchestration. Helpers continue lazy Torch/NumPy imports. Existing tested helper imports remain aliases, not duplicate implementations. | High: engine-family adapters, warmup failure/reset checks, RNG restoration, telemetry fields, and mocked streaming. No latency, quality, or hardware-acceptance claim. |
| `examples/qwen_tts_latency_benchmark.cpp` (71,398 B) | Extract options, JSONL manifest parsing, result acceptance/contract evaluation, and report serialization. Keep request execution, metric collection, and process composition together. | Private `latency_benchmark.hpp` supplies SDK umbrellas and example-only result/config types. Evaluation and reporting consume snapshots; they never own requests or threads. JSON remains private to the executable. | Low–medium: parser errors, explicit negative outcomes, EOS, cancellation prefix, report fields/nulls/escaping, aggregate exclusion, and existing mock/reference-warmup probes. |

The remaining engine coordinator is deliberately still large. Moving its
stateful methods into a mixin or a helper that receives the entire engine
would reduce line count without creating an independent owner. This batch does
not do that. Native preparation orchestration likewise stays beside registry
publication until a smaller, explicit artifact-publication boundary is needed.

## Other production and diagnostic candidates

| File (baseline bytes) | Observed boundary | Decision |
| --- | --- | --- |
| `worker/src/qwen_tts_bridge_worker/server/stdio_server.py` (51,494) | Output writer versus admission, engine scheduling, and exactly-once terminalization. | Defer. Writer has a real lifecycle boundary, but moving request/state methods would cross shared queues, conditions, and shutdown state. Require targeted failure/shutdown regression work, not a size-only split. |
| `worker/src/qwen_tts_bridge_worker/user_cli.py` (45,215) | Parser, models/voices commands, synthesis/play/design composition, diagnostic tails. | Defer to a CLI-focused batch. Resolver and voice-library services already exist; avoid introducing another service layer or coupling this change to engine refactoring. |
| `worker/src/qwen_tts_bridge_worker/cli.py` (32,496) | Worker parser and configuration/profile validation. | No split in this batch: these implement the same startup configuration contract. Revisit if validation becomes reusable outside this entry point. |
| `src/qwen_tts_bridge/client/qwen_tts_client.cpp` (34,306) | Request IDs, callback delivery, text preparation, terminalization, shutdown. | Keep together. Ownership and locking, not file size, define this stateful implementation. |
| `src/qwen_tts_bridge/transport/stdio/std_io_transport.cpp` (30,993) | Process registration, dispatch, termination, and thread joins. | Explicitly excluded after lifecycle fixes #294–#300. Do not relocate synchronized methods just to reduce size. |
| `src/qwen_tts_bridge/playback/winmm_playback.cpp` (33,497) | Device buffers, playback epochs, cursor/reset and interruption. | Keep together; this is one resource/locking owner. |
| `worker/native/qwentts/native_engine.cpp` (34,597) | Runtime/model ownership, prepared voices and generation callbacks. | Defer; no new runtime acceptance is part of this batch. Preserve the native-engine ADR. |
| `worker/native/qwentts/prepared_voice_reference.cpp` (33,151) | Bounded artifact verification and crash-recoverable publication. | Defer. Recovery/publication could eventually be isolated, but its transaction and reparse-point safety invariants must move together. |
| `examples/qwen_tts_speech_animation_probe.cpp` (30,463) | Probe options, observations/continuity checks and receipt output. | Defer. Keep the probe's playback/animation receipt semantics together; not a generic animation library candidate. |
| `tests/python/benchmark_packaged_worker_restart.py` (80,124) | Diagnostic command, per-run acquisition, metric mapping, pair/outlier/correlation reporting. | Later candidate for pure report analysis extraction. It is an executable diagnostic, not a unit-test fixture; preserve receipt fields and pairing semantics with its dedicated tests. |

## Large tests

These are inspected, not automatically split. Shared fixtures belong to the
tests that require the same semantics; do not create a global fixture registry.

| File (baseline bytes) | Responsibility groups and decision |
| --- | --- |
| `tests/python/test_qwen_engine.py` (100,084) | Timing fields, fake upstream/Faster model families, warmup/prefill/RNG, generation and validation. Keep shared fake models local for this batch. A later split can separate telemetry and warmup tests once their modules settle; it must not copy the model fixtures. |
| `tests/native/qwen_tts_native_worker_test.cpp` (83,298) | Raw frame/admission probes, reference artifact/publication/recovery fixtures, synthesis/lifecycle checks. Defer a test-driver/fixture split; preserve subprocess crash isolation and native fixture ownership. |
| `tests/python/test_user_cli.py` (80,149) | Models/voice/config resolution, synth/play/design invocation, output publication and diagnostic tails. Defer together with a user-CLI batch; no cross-command fixture framework now. |
| `tests/python/test_stdio_server_lifecycle.py` (47,913) | Startup failures, output-writer failures, request terminalization and shutdown using injected engines/streams. Keep one shared server harness while the writer boundary is deferred. |
| `tests/qwen_tts_client_test.cpp` (44,529) | Async request routing/cancellation, callback failures, prepared text, admission and ID limits. Keep fixtures local; no transport/client lifecycle rewrite in this batch. |
| `tests/stdio_transport_test.cpp` (41,258) | Byte/frame collectors, environment tests, lifecycle/watchdog child scenarios. Keep watchdog ownership intact after #298/#300. |
| `tests/python/test_voice_library.py` (39,466) | Registry/path safety and native preparation fixtures. Existing IPC tests already exercise the extracted operation through its historical entry point; add narrow direct boundary tests without duplicating the subprocess fixtures. |
| `tests/python/test_benchmark_packaged_worker_restart.py` (37,550) | Runtime provenance, report shaping, pairing/statistics and worker arguments. Preserve as the regression owner for a later diagnostic-report extraction. |

## Verification and review boundaries

- Compile added implementation files directly and explicitly in CMake, with
  private example umbrellas first. No `.cpp` inclusion, forced include, PCH,
  unity build, or installed example-helper library.
- Keep public import names and exception identity; do not use a reverse import
  from a helper module into its coordinator.
- Run focused boundary tests, the configured Python checks for worker changes,
  and CTest plus exact-head Windows CI. Exercise the speech-animation player
  configuration because its feature macro affects playback options.
- Treat static moved-body comparison as supplemental evidence only. Mock tests
  do not establish GPU parity, native synthesis quality, or physical playback.
- Leave models, historical reports, acceptance receipts, and machine-local
  archives unchanged. Draft PRs require review; this audit does not authorize
  their automatic merge.
