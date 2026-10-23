# Beta capability matrix

This is the Phase B1 inventory for `qwen3-tts-bridge-cpp` at
`30500e9426ba1309c295f9e3228e7a80ad35d97b` (the merge of Phase A).  It is an
evidence ledger, not a promise that every implemented path is release-ready.
The production baseline remains the persistent Python worker.  Native Qwen,
the RU-stress profile, and speech-animation are explicitly opt-in or
experimental until their listed gates are closed.

## Evidence vocabulary

* **Verification** records what implementation, automated tests, hardware
  receipts, or human listening actually prove.
* **Support level** records the product policy separately: production baseline,
  opt-in, experimental, or deferred. A passing experiment is not automatically
  a supported production default.
* **A / verified** means the implementation and a relevant automated or real
  acceptance receipt exist for the stated scope.
* **B / partial** means code and tests exist, but a model variant, packaging,
  clean-machine, or human gate is still missing.
* **C / blocker** means a reproducible defect or missing requirement must be
  fixed before the corresponding beta scope is advertised.
* **D / deferred** means useful work outside the first coherent beta.

Hardware evidence below refers to the documented CMP 50HX runs.  No RTX 4090
run is implied by this document.

## Matrix

| Capability / requirement | Implementation and public surface | Automated evidence | CMP 50HX / human evidence | Status and remaining gate | Release disposition |
|---|---|---|---|---|---|
| Static SDK and CMake install/export | `qwen_tts_bridge` target and generated package config in `CMakeLists.txt`; installed headers and `QwenTTSBridgeTargets`; optional installed `qwen_tts_bridge_winmm_playback` and tts-front adapter | Windows default CI installs the package and builds `tests/install_consumer` with WinMM (`.github/workflows/cpp-checks.yml`, `scripts/test-installed-package.ps1`) | Not hardware-dependent | **A** for core and WinMM. Native DLL and speech-animation adapters remain build-tree-only by design | REQUIRED |
| Persistent Python worker and portable packaging | `worker/src/qwen_tts_bridge_worker`, persistent engine/output threads; `scripts/package-python-worker.ps1`, `test-portable-python-worker*.ps1` | Python suite, portable mock package, and C++ transport smoke run in CI; doctor verifies build/runtime/model manifests | Import/package probes only; no committed clean-machine real-model playback receipt | **B**. Complete one clean-machine real-Qwen package, doctor, C++ playback, and listening run | REQUIRED |
| Native worker, dynamic `qwen.dll`, ABI/runtime manifest | `worker/native/qwentts`, runtime manifest loader, ABI/export/hash checks, split talker/codec and profile resolver; opt-in `QWEN_TTS_BRIDGE_BUILD_QWENTTS_WORKER` | Native ABI CI and native worker tests; pinned qwentts.cpp `130cb99af9ae12d554962fd0920e08fb4268af01` (ABI 6) | CMP native playback/EOS/cancellation receipts and warm long-horizon listening exist | **Verification: B / Support: opt-in**. Finish promotion/package matrix before calling it a default backend | OPTIONAL for first beta; keep opt-in |
| CustomVoice 0.6B | Python routing and speaker validation; `run-real-model-release-acceptance.ps1` accepts external 0.6B model and `ryan`/`serena` | Mock routing and packaging tests; release runner is implemented | Runner/checklist exists, but no committed exact-baseline real 0.6B release receipt was found in this audit | **B**. Run the exact sealed package matrix plus human Ryan/Serena listening | REQUIRED if advertised; otherwise B/P1 |
| CustomVoice 1.7B | Same model-family route, model-size agnostic worker configuration | Mock/model-family tests | No variant-specific real acceptance receipt located | **B**. Either run and record a 1.7B acceptance or state that beta scope is 0.6B only | OPTIONAL / scope decision |
| Base 0.6B | Base routing exists in Python/Faster paths; registered voice profile and reference-audio validation are implemented | Engine and lifecycle tests cover Base request shapes | No variant-specific 0.6B hardware receipt located | **B**. Run the selected 0.6B model with registered/reference voice if this size is advertised | OPTIONAL |
| Base 1.7B and voice cloning | Python/Faster production route, registered `voice_id`, reference WAV validation; native worker has corresponding profile path | `run-real-model-release-acceptance.ps1`, lifecycle/restart tests, model/voice validation tests | CMP 50HX Base startup, persistent-worker, long-horizon, natural-EOS, cancellation/recovery, and listening receipts; `docs/cmp50hx-base-profile-startup.md`, `docs/reports/cmp50hx-abi6-playback-v2-2026-09-30.md` | **Verification: A for the documented CMP profile; Support: production Python baseline only.** Keep native opt-in and exact model/runtime/voice fingerprints with release. Direct per-request reference audio remains diagnostic in the release runner | REQUIRED for Base beta scope |
| VoiceDesign 1.7B | `tts_model_type=VoiceDesign` route, instruction validation, `start-voice-design-save-wav.ps1` wrapper | Mock wrapper and engine tests; WAV plumbing test | No committed real VoiceDesign model-quality or hardware acceptance; no GGUF | **B**. Run real model on the selected package and perform human intelligibility/identity gate, or mark unsupported in beta | OPTIONAL / P1 if advertised |
| RU-stress model and explicit U+0301 | Experimental profile-owned identity and renderer path; combining acute is passed through only for compatible profile | Native/profile and renderer tests | `docs/reports/russian-stress-cmp50hx-acceptance-2026-10-07.json`: 12/12 non-empty PCM, natural EOS, starvation-free; human listening PASS; explicit U+0301; oracle parity 310/311 payloads byte-identical, relative embedding L2 `1.36e-6` | **Verification: A for the recorded experiment; Support: experimental/opt-in, not default.** Preserve `kraftwerk_robot_ru_warm`, hashes, seed 1002 and profile provenance; repeat only if release scope changes | OPTIONAL / experimental |
| Text frontend and normalization | Pinned `external/cpp/tts-front-cpp` `f828893b46728544041ab577215640338756a9d4` (annotated v0.2.2), `TtsFrontTextPreparer`, `PreparedText` contract | Frontend/adapter tests and prepared-text call-count/wire tests | Russian stress listening matrix and receipts use the frontend boundary | **B/P1** because upstream has v0.2.3 (`52383911290aabe6e2963ec434d195fdeaac0aad`) with material Russian/numeric fixes; B2 must update and rerun adapter/regression evidence | REQUIRED before beta claims depend on v0.2.3 behavior |
| Request lifecycle, cancellation, restart, errors | `QwenTtsClient`, `WorkerSession`, Python `StdioWorkerServer`, native `StdioServer`; request IDs, terminal events, cancellation and transport errors | Broad C++/Python lifecycle, cancellation, malformed-frame, restart and error suites | CMP cancellation/recovery and natural-EOS receipts; no GPU CI required | **B/C boundary**. A verified long-lived-service defect remains: Python `_terminal_request_ids` and native `terminal_ids_` grow without bound. Also duplicate checks over-reject terminal IDs relative to protocol’s active-ID requirement. Fix and add bounded-memory/reuse tests before an unattended beta worker | REQUIRED hardening (P1) |
| Streaming PCM, WAV, WinMM playback, sample-clock receipt | PCM callbacks, `save_wav`, `AudioPostProcessorChain`, `WaveOutPlayer`, playback cursor/receipt and ETW diagnostics | C++ playback, postprocessor, WAV, malformed PCM and install consumer tests; speech-animation mock receipt tests | CMP WaveOut EOS/cancellation/recovery and speech-animation Qwen E2E receipts: contiguous PCM/animation, end alignment, queue-full 0 | **Verification: A for tested formats and CMP profile; Support: core streaming is production baseline, WinMM is optional sink.** Physical sink failures are separate from synthesis lifecycle | REQUIRED core; WinMM OPTIONAL module |
| CLI tools and options | `qwen_tts_play`, latency benchmark, save-WAV, speech-animation probe; worker args and model/voice options are documented in `examples/README.md` | CTest/mock probes and parser/unit coverage | Real player and benchmark receipts on CMP | **B/P2**. Option surfaces are intentionally not identical; `qwen_tts_save_wav` lacks direct reference-audio, seed and sampling fields exposed by player/benchmark. Decide whether registered `voice_id` is sufficient for beta, otherwise add a focused CLI corrective | REQUIRED supported subset; cleanup OPTIONAL |
| Audio-processing chain and effects | `AudioPostProcessorChain`, terminal fade and completion/cancellation silence; no EQ, compressor, limiter, denoise, reverb, pitch or speed effect implementation found | Postprocessor and playback lifecycle tests | CMP receipts include terminal fade and sample-clock alignment | **Verification: A for fade/padding only; Support: final DSP scope is a release decision.** Do not advertise a general effects rack before that decision | OPEN SCOPE |
| Model discovery, download, validation, offline operation | Native unified root/profile resolver and manifest/hash downloader; Python explicit `model_path`, local HF-cache fallback in clone launcher, portable doctor/runtime/model manifests | Native manifest tests; Python doctor/model-hash and offline/package tests | Native manifests and RU-stress provenance captured; real Python model remains external | **B**. A beta must document external model provisioning, exact manifests/hashes and offline startup. A unified Python downloader is not required unless product scope explicitly adds it | REQUIRED documentation/acceptance; downloader OPTIONAL |
| Windows binary packaging and clean-machine use | CMake install package; portable Python staging; optional Nuitka packaging scripts | Mock portable package and installed consumer CI; manual Qwen import workflow | No committed clean-machine real-model package/playback receipt | **B/P1**. Complete the real-Qwen portable package/doctor/playback/listening gate on a clean Windows machine; keep narrow Nuitka blocker visible | REQUIRED |
| Diagnostics, reproducible benchmarking, evidence capture | Metrics JSON, playback receipts, provenance/manifests, benchmark and CMP runners (`run-real-model-release-acceptance.ps1`, `run-native-python-matrix.ps1`, `run-cmp50hx-playback-etw-soak.ps1`) | Parser/script tests and CI syntax/build checks | Extensive CMP reports with model/runtime/seed hashes; no RTX execution | **A** for existing scope. Release freeze still needs one canonical artifact bundle and exact request-corpus hashes | REQUIRED |
| Optional speech-animation integration | Build-tree optional adapter, playback cursor/runtime and receipts; no Qwen headers in core | Speech-animation CI and mock probe; real Qwen CMP short/medium/long OFF/ON receipts | `docs/reports/speech-animation-qwen-e2e-cmp50hx-20261009/`: contiguous timelines, animation end equals PCM end, queue-full 0, varying mouth_open | **Verification: A for audio-reactive v0; Support: optional integration.** Predictive visemes, avatar presentation and display-latency claims are not part of this beta gate | OPTIONAL / DEFERRED |

## Current beta interpretation

The evidence supports a coherent beta built around the Python worker, the
documented Base 1.7B CMP profile, the installed core/WinMM SDK, and the
existing streaming/WAV/playback contracts. It does not support silently
claiming that every Qwen model size, VoiceDesign, native DLL, portable clean
machine, or avatar presentation path is equally accepted.

Model-family inclusion, mandatory CLI commands, and the minimum DSP surface are
still product-scope decisions for B2-0. This matrix records verification facts
without silently deciding that an unverified variant or an unimplemented effect
is either included or discarded.

The most important evidence references are:

* [real-model acceptance](real-model-release-acceptance.md)
* [native/Python acceptance matrix](native-python-acceptance-matrix.md)
* [native worker boundary](native-qwentts-worker.md)
* [model location contract](model-location.md)
* [RU-stress acceptance receipt](reports/russian-stress-cmp50hx-acceptance-2026-10-07.json)
* [CMP Base profile investigation](cmp50hx-base-profile-startup.md)
* [speech-animation CMP receipt](reports/speech-animation-qwen-e2e-cmp50hx-20261009/README.md)
