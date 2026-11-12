# Beta release gap analysis

Historical B2 baseline: `6cf272fce7358479393f0bdd7d9bb3186cd1f1fb`.
R1 audit baseline: `d0e1a629199647e908a4d945a1ce9743a68a5715`.

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
the repository does not contain a clean-environment CMP 50HX real-Qwen package,
model-load, physical-playback and listening receipt with final hashes. This is
the packaging verification gate on the development machine, not an implicit
requirement for a third computer.

* Owner: `scripts/package-python-worker.ps1`, `scripts/test-portable-python-qwen-worker.ps1`,
  `worker/.../doctor.py`.
* Smallest corrective: run the existing scripts on a clean Windows machine with
  one selected model, preserve the generated manifest/provenance and WAV/report.
* Acceptance: on CMP 50HX, in an isolated clean build/install environment,
  doctor passes offline; one persistent worker produces non-empty PCM and
  natural completion through the installed C++ example; a human hears
  intelligible, complete audio; no model weights are committed. The independent
  RTX 4090 run happens only after candidate freeze and is described in the
  handoff plan.

### B2. Exact model-family matrix (P1)

Evidence is strong for Base 1.7B and experimental RU-stress, but not for every
size/family listed by the API. CustomVoice 0.6B has a release runner without a
committed exact-baseline receipt; CustomVoice 1.7B and Base 0.6B lack
variant-specific real acceptance. VoiceDesign 1.7B has a frozen CMP receipt
with partial listening, not full current-candidate acceptance; see the
[acceptance index](reports/acceptance-index.json).

* Owner: Python worker plus release runner and model manifests.
* Smallest corrective: choose the beta advertised set first. For each selected
  variant, run the existing persistent-worker, PCM/EOS, playback and human
  listening gate; otherwise mark the variant unsupported/experimental.
* Acceptance: the matrix names exact model revision, runtime, voice/instruction,
  seed, device and report path for each advertised variant.

### B3. tts-front revision (P1) — dependency update complete

The submodule is now pinned to v0.2.5 (`d1b6a6e18e7f51f8c51fff548bb84f10e749004a`).
The bridge-level v0.2.2-to-v0.2.5 comparison is recorded in
`docs/reports/tts-front-v022-v025-effective-text.md`.

* Owner: `external/cpp/tts-front-cpp` and the bridge adapter.
* Completed corrective: update the pin, run the prepared-text and adapter
  tests, and compare effective UTF-8 text and diagnostics on the fixed corpus.
  The comparison found 13 unchanged cases, three intended effective-text
  changes, one intended diagnostic-only change, and no regressions.
* Acceptance: exact v0.2.5 tag/provenance and the comparison receipt are
  recorded. Targeted listening for the three changed text surfaces remains a
  separate release gate. Do not mix that gate with worker hardening.

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

This was a verified resource/lifecycle defect, not a documentation preference.
It is addressed by the B2-2 terminal-ID policy: Python and native workers keep
only a monotonic accepted-ID high-water mark for each session. New synthesis
IDs must be strictly greater than every ID already accepted, while completion
order remains unconstrained and active lower IDs remain valid. This prevents
unsafe reuse and late-cancel races without retaining a per-request tombstone
set.

* Impact: without the corrective, a long-lived service accumulated one set entry
  per request. The accepted-ID high-water policy keeps constant terminal-history
  memory and makes acceptance, late-cancel and reuse behavior deterministic.
* Owner: Python worker and `worker/native/qwentts` (B2-2).
* Smallest corrective: advance the accepted-ID high-water mark only when a
  synthesis request is admitted, under each worker's existing lifecycle lock;
  terminalization must not advance it.
* Acceptance: large sequential-request tests keep retained state bounded;
  duplicate active or lower IDs return `request_error/duplicate_request_id`;
  late cancel at/below the accepted-ID watermark is idempotent; unknown future
  IDs return `request_error/unknown_request_id`; tests cover the policy and
  shutdown cancellation.
* Dependencies: none for terminal history; bounded pending admission is covered
  by the separate B2-3 corrective below.

### C2. Bound pending request admission (P1) — B2-3 corrective

The former unbounded pending deques in Python `StdioWorkerServer._pending` and
native `StdioServer::pending_` are now protected by a shared admission contract.
The cap covers queued and physically running requests; output and callback
queues remain separate concerns.

* Impact addressed: memory growth and poor failure behavior under load were
  distinct from the already bounded output queues.
* Owner: both worker implementations and protocol tests.
* Implemented corrective: define an admission cap covering queued **and running**
  request accounting, reject excess work with `resource_error/resource_exhausted`,
  and expose the effective limit in diagnostics. Queued cancellation releases
  capacity deterministically.
* Acceptance: fill the queue to the cap, observe exact rejection and no growth
  beyond the cap, cancel queued work, admit a replacement after cancellation or
  completion, and verify both Python and native paths.
* Implementation status: B2-3 defines a default limit of 16, exposes a runtime
  override in both workers, and covers queued plus physically running
  occupancy. Exact-head CI and direct QTB-frame tests passed for the corrective
  implementation.

## D — optional or deferred

| Item | Why it is deferred |
|---|---|
| Targeted listening for the v0.2.5 frontend delta | The dependency pin and 17-case comparison (13 unchanged cases) are complete with no regressions. Listen only to the leading-zero year, contextual year-agreement, and genitive-decimal cases before making those changes part of a release claim. |
| Further CLI decomposition | Shared C++ example parsing and focused implementation splits landed in #302–#305. Do not reopen that refactor without a concrete defect. |
| Save-WAV direct reference-audio/seed/sampling options | Registered Base `voice_id` is the release-facing clone path. Keep this an explicit B2-0 scope decision; add fields only if direct reference input is a beta requirement. |
| Full audio effects rack (EQ, compressor, limiter, denoise, reverb, pitch, speed) | Only terminal fade/padding and the generic postprocessor chain exist. Keep the minimum DSP surface as an explicit B2-0 scope decision; do not add presets before a product requirement. |
| Implicit model provisioning | Python `models download` is implemented as an explicit operation. Synthesis stays offline after provisioning and never downloads silently. |
| Predictive visemes, Unity/Godot/VRM presentation and display-latency claims | Audio-reactive v0 is accepted; presentation must follow a separate playback-cursor and avatar contract. |
| Native in-process adapter promotion | It is a separate high-risk boundary and not needed for the Python beta. |

## Architecture and quality review

### Verified findings

* **Persistent worker resource growth:** C1 terminal-ID retention is bounded,
  and C2 pending admission is capped in both implementations. Earlier
  unbounded-growth observations remain historical evidence, not current status.
* **CLI surface drift:** `qwen_tts_play` and the benchmark expose reference
  audio, seed and sampling controls that `qwen_tts_save_wav` does not. This is a
  documented capability difference, not yet a demonstrated bug.
* **Large maintenance surfaces:** `qwen_tts_play.cpp`,
  `qwen_tts_latency_benchmark.cpp`, `stdio_server.py`, `qwen_tts_client.cpp` and
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

The release-facing `CHANGELOG.md` now describes the unreleased Windows beta
scope and keeps native routing explicitly opt-in, matching
`docs/project-status.md` and the capability matrix. The historical v0.2.0
checklist and old ABI/near-silent reports remain historical; they must not be
rewritten as current failures or current passes.

## Current remaining order

The B2 terminal-history and pending-admission correctives below are already
implemented, as described in C1/C2; they need frozen-candidate regression, not
another implementation. The installed Python CLI completion wave #306–#309
is also merged. The remaining release work is exact-candidate acceptance,
clean packaging, listening and independent RTX validation.

1. B2-0: decide the advertised model matrix, backend policy, required CLI
   commands and minimum DSP surface; update the release-facing changelog to
   match it.
2. Complete the targeted listening gate for the v0.2.5 frontend delta, then
   keep the comparison receipt as the dependency provenance.
3. Regression-test the implemented strict acceptance-order terminal-ID/late-cancel
   contract, then verify bounded history in Python and native workers.
4. Regression-test the implemented bounded pending-request admission covering queued and
   running requests, with cancellation and recovery tests.
5. Execute the existing isolated clean-environment CMP portable real-Qwen
   package and selected
   model-family acceptance gates; do not create parallel runners.
6. Freeze CMP artifacts and run the handoff plan before any RTX 4090 work.

This order intentionally leaves predictive visemes, a general effects rack,
automatic Python downloads, and native-default promotion outside B2.
