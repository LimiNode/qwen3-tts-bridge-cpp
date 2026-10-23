# Beta release gap analysis

Baseline: `30500e9426ba1309c295f9e3228e7a80ad35d97b`.

This document narrows Phase B2 to evidence-backed work. It deliberately keeps
the Python worker as the production baseline and does not promote the native
backend, RU-stress profile, VoiceDesign, or avatar presentation merely because
their code exists.

## A — already complete for the stated scope

1. The core C++ SDK has a generated CMake package, installed headers, and a
   CI-built external consumer. The optional WinMM target is installed and
   consumed by that smoke test.
2. The async client/worker protocol, persistent Python worker, cancellation,
   restart/error paths, PCM streaming, WAV writing, terminal fade, and sample
   clock are covered by focused tests and the accepted CMP receipts.
3. The documented CMP Base 1.7B profile has long-horizon EOS, cancellation and
   recovery, persistent-worker reuse, playback receipts, and human listening
   evidence. These experiments must not be repeated without a changed build,
   model, or acceptance question.
4. The RU-stress profile has a bounded 12-case CMP listening/PCM/EOS receipt and
   explicit combining-acute behavior. It remains experimental and default-off.
5. Audio-reactive speech-animation v0 has a real Qwen OFF/ON receipt with
   contiguous sample-addressed timelines and no queue overflow. This is not a
   claim of avatar/display synchronization.
6. CI appropriately covers Windows builds, native ABI compilation, Python
   tests, installed package consumption, and portable mock-worker smoke. It does
   not pretend to be GPU model acceptance.

## B — implemented, but acceptance is missing

### B1. Real portable Python release package (P1)

The portable runtime, doctor, runtime-tree manifest, model manifest and C++
smoke scripts exist. CI proves a mock package and a no-GPU Qwen import probe;
the repository does not contain a clean-machine real-Qwen package, model-load,
physical-playback and listening receipt with final hashes.

* Owner: `scripts/package-python-worker.ps1`, `scripts/test-portable-python-qwen-worker.ps1`,
  `worker/.../doctor.py`.
* Smallest corrective: run the existing scripts on a clean Windows machine with
  one selected model, preserve the generated manifest/provenance and WAV/report.
* Acceptance: doctor passes offline; one persistent worker produces non-empty
  PCM and natural completion through the installed C++ example; a human hears
  intelligible, complete audio; no model weights are committed.

### B2. Exact model-family matrix (P1)

Evidence is strong for Base 1.7B and experimental RU-stress, but not for every
size/family listed by the API. CustomVoice 0.6B has a release runner without a
committed exact-baseline receipt; CustomVoice 1.7B, Base 0.6B and VoiceDesign
1.7B lack variant-specific real acceptance in this repository.

* Owner: Python worker plus release runner and model manifests.
* Smallest corrective: choose the beta advertised set first. For each selected
  variant, run the existing persistent-worker, PCM/EOS, playback and human
  listening gate; otherwise mark the variant unsupported/experimental.
* Acceptance: the matrix names exact model revision, runtime, voice/instruction,
  seed, device and report path for each advertised variant.

### B3. tts-front revision (P1)

The submodule is pinned to annotated v0.2.2 (`f828893b46728544041ab577215640338756a9d4`),
while upstream v0.2.3 points to `52383911290aabe6e2963ec434d195fdeaac0aad` and contains
substantial Russian genitive, numeric, currency and combining-mark admission
fixes.

* Owner: `external/cpp/tts-front-cpp` and the bridge adapter.
* Smallest corrective: update the pin in a separate dependency PR, run the
  prepared-text and adapter tests, and rerun the Russian stress corpus.
* Acceptance: exact v0.2.3 tag/provenance is recorded and all existing frontend
  regressions remain green. Do not mix this with worker hardening.

### B4. Native promotion boundary (P1/P2)

The native process worker and ABI-6 DLL path have strong CMP evidence, but they
are opt-in and not the Python release baseline. Native in-process integration,
broader package/export and multi-family coverage remain promotion gates.

* Owner: `worker/native/qwentts`, qwentts.cpp pin `130cb99`, native manifests.
* Acceptance: only after a selected beta profile passes the same lifecycle,
  package, listening and reproducibility gates as Python. Until then keep the
  option and documentation explicitly opt-in.

## C — required engineering work

### C1. Bound persistent-worker terminal history (P1)

This is a verified resource/lifecycle defect, not a documentation preference.
Python `StdioWorkerServer._terminalize_locked()` adds every completed,
cancelled or failed ID to `_terminal_request_ids`; native
`StdioServer::terminalize()` does the same in `terminal_ids_`. Neither set is
pruned. The duplicate check also rejects IDs that are no longer active, while
the protocol requires rejecting duplicate *active* IDs and only recommends
monotonic IDs during a session.

* Impact: a long-lived service accumulates one set entry per request and cannot
  reclaim the associated tombstone memory.
* Owner: Python worker and `worker/native/qwentts`.
* Smallest corrective: define one bounded policy (for example, active-only
  duplicate rejection plus a bounded recent tombstone window, or an explicit
  monotonic high-water rule), implement it symmetrically, and document it.
* Acceptance: a large sequential-request test keeps tombstone memory/count
  bounded; duplicate active IDs still return `request_error/duplicate_request_id`;
  terminal-ID reuse and late cancel have deterministic, documented results.
* Dependencies: settle the protocol policy before changing either worker.

### C2. Bound pending request admission (P1, scope confirmation required)

Both workers append accepted work to an unbounded pending deque:
Python `StdioWorkerServer._pending` and native `StdioServer::pending_`. Output
and client callback queues are bounded, but a direct or misbehaving QTB client
can enqueue requests indefinitely before the engine drains them.

* Impact: memory growth and poor failure behavior under load; this is distinct
  from the already bounded output queues.
* Owner: both worker implementations and protocol tests.
* Smallest corrective: add a configurable pending-request cap, reject excess
  work with `resource_error/resource_exhausted`, and expose the effective cap in
  diagnostics. Keep cancellation of queued requests deterministic.
* Acceptance: fill the queue to the cap, observe exact rejection and no growth
  beyond the cap, cancel queued work, and verify both Python and native paths.
* Dependency: confirm the beta threat model and default cap before API freeze.

## D — optional or deferred

| Item | Why it is deferred |
|---|---|
| `tts-front` v0.2.3 update if beta text normalization is frozen elsewhere | It is a focused dependency update, not a reason to redesign the bridge; still P1 when Russian normalization is in advertised scope. |
| Shared CLI parsing helpers | Four examples duplicate parsing/JSON helpers, but no correctness drift was demonstrated. Extract only after a concrete option bug or during a small P2 cleanup. |
| Save-WAV direct reference-audio/seed/sampling options | Registered Base `voice_id` is the release-facing clone path. Add fields only if direct reference input is a beta requirement. |
| Full audio effects rack (EQ, compressor, limiter, denoise, reverb, pitch, speed) | Only terminal fade/padding and the generic postprocessor chain exist. Do not add effects before a product requirement. |
| Automatic Python model downloader | Native has a validated URL/hash downloader; Python can use explicit external paths and doctor manifests. A unified downloader is optional if offline provisioning remains the contract. |
| Predictive visemes, Unity/Godot/VRM presentation and display-latency claims | Audio-reactive v0 is accepted; presentation must follow a separate playback-cursor and avatar contract. |
| Native in-process adapter promotion | It is a separate high-risk boundary and not needed for the Python beta. |

## Architecture and quality review

### Verified findings

* **Persistent worker resource growth:** the terminal tombstones and pending
  queues described in C1/C2 are visible in both implementations and have
  reproducible unbounded-growth scenarios.
* **CLI surface drift:** `qwen_tts_play` and the benchmark expose reference
  audio, seed and sampling controls that `qwen_tts_save_wav` does not. This is a
  documented capability difference, not yet a demonstrated bug.
* **Large maintenance surfaces:** `qwen_tts_play.cpp`,
  `qwen_tts_latency_benchmark.cpp`, `stdio_server.py`, `QwenTtsClient.cpp` and
  `package-python-worker.ps1` are large files. Treat this as review pressure,
  not a license for speculative refactoring.

### Boundaries that should remain unchanged

* The worker owns model loading, CUDA/PyTorch and model-specific streaming;
  the C++ bridge owns protocol, supervision, request state and callbacks.
* Physical playback remains an optional sink. Playback failure must not rewrite
  a successful synthesis lifecycle.
* Speech-animation observes post-processed PCM and the playback sample cursor;
  it must not delay or mutate PCM.
* `nlohmann/json`, Qwen headers and speech-animation types stay out of the
  stable core public API.

### Documentation contradictions to resolve before publication

`CHANGELOG.md` still describes an “Unreleased — v0.2.0 release candidate” and
mentions native routing, while `docs/project-status.md` correctly says that the
Python worker is the production baseline. Before beta publication, reconcile
the release-facing changelog with the actual supported/opt-in matrix. The
historical v0.2.0 checklist and old ABI/near-silent reports should remain
historical; they must not be rewritten as current failures or current passes.

## Recommended B2 order

1. Decide the advertised model matrix and update the release-facing changelog
   to match it.
2. Update `tts-front-cpp` to v0.2.3 in an isolated dependency PR and rerun
   adapter/Russian stress regressions.
3. Fix and test bounded terminal history in Python and native workers.
4. Confirm the threat model and add bounded pending-request admission in both
   workers if beta accepts untrusted/direct QTB clients.
5. Execute the existing clean-machine portable real-Qwen package and selected
   model-family acceptance gates; do not create parallel runners.
6. Freeze CMP artifacts and run the handoff plan before any RTX 4090 work.

This order intentionally leaves predictive visemes, a general effects rack,
automatic Python downloads, and native-default promotion outside B2.
