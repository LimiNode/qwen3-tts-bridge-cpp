# CMP 50HX to RTX 4090 beta handoff plan

This plan is for a reproducible beta candidate, not for comparing two GPUs by
one headline latency number. CMP 50HX is the development and freeze machine;
RTX 4090 is a later validation target. Any number is meaningful only with the
same engine, model, runtime, request corpus and playback policy recorded beside
it.

## 1. Freeze the CMP candidate

Before handoff, create a clean worktree and freeze:

* bridge commit and exact branch/tag;
* all submodule commits, including qwentts.cpp `130cb99`,
  speech-animation, Qwen streaming, FasterQwen and tts-front;
* compiler, CMake generator, build options and Release binaries;
* Python 3.11 runtime, PyTorch/CUDA versions and portable runtime-tree
  manifest;
* model directories outside git, each with a model manifest and SHA-256 of
  every file (talker/codec GGUF or Python checkpoint files);
* native runtime manifest, `qwen.dll` hash, ABI number and exported symbols;
* voice registry, reference WAV hash and selected profile identity;
* request corpus as UTF-8 bytes plus a canonical manifest/hash;
* seed, language, speaker/voice ID, instruction, sampling fields, codec
  schedule, playback prebuffer, terminal-fade policy and all environment
  overrides;
* GPU name/VRAM, driver, Windows build, CUDA runtime and process affinity.

Models and reference audio remain external artifacts. The handoff bundle should
contain manifests, hashes, scripts and reports, never model weights.

### External-model transfer procedure

For each model or reference artifact, export a manifest containing relative
path, byte length, SHA-256, model family, revision and license/provenance. Copy
the artifact tree to the RTX 4090 machine using an integrity-preserving file
transfer (for example, an archive plus its detached SHA-256 manifest). Verify
the archive hash before extraction, verify every extracted file against the
manifest, and run the portable/native doctor before the first synthesis. Record
the destination path only as configuration; the content hash is the identity.
Never regenerate, quantize or silently redownload a missing file during the
first A/B run. A changed model tree starts a new acceptance record.

The selected CMP Base profile must be explicit. The accepted evidence currently
uses the prepared Base 1.7B profile, reference-context bootstrap where enabled,
the documented right-padded codec configuration, and the WaveOut cursor/receipt
path. Do not silently substitute the old ABI-5, near-silent, or historical
RTX-era reports.

## 2. Reusable acceptance runners

Use the existing runners and preserve their machine-readable output under
`.tmp/base-acceptance/<run-id>/` during execution. Keep the final report,
manifest, logs, and listening result in that same run directory; historical
evidence migrated from older locations belongs under
`.tmp/historical/<name>/`:

```powershell
.\scripts\run-real-model-release-acceptance.ps1 ...
.\scripts\run-native-python-matrix.ps1 ...
.\scripts\run-cmp50hx-playback-etw-soak.ps1 ...
```

The first runner covers the persistent CustomVoice/player contract and optional
Base profile arguments. The second compares Python/native request and lifecycle
shapes. The ETW soak records playback cursor, queue and interruption evidence.
Do not write a parallel benchmark merely to move this handoff forward.

For each advertised model/profile, capture at minimum:

* ready, queued, started, first PCM, completed/cancelled/error timestamps;
* PCM byte/sample counts, sample format, contiguous ranges and natural EOS;
* first-audio latency, synthesis duration, RTF and playback start separately;
* WaveOut queue/starvation proxy and cursor diagnostics;
* cancellation at early, middle and backlog positions followed by a recovery
  request;
* worker restart and persistent-session reuse;
* exact model/voice/runtime hashes and seed;
* human listening verdict for intelligibility, identity, clicks, stutter,
  truncation, final word and sequential-request contamination.

The existing speech-animation receipt may be retained as optional evidence, but
it does not prove physical avatar presentation or display latency.

## 3. RTX 4090 first run

After the CMP candidate has passed the isolated clean-environment packaging
gate and its artifact bundle is frozen, reproduce that workload independently
on the RTX 4090 before changing anything. This is a separate validation
machine, not an unspecified third environment:

1. Fresh checkout/worktree at the frozen bridge and submodule SHAs.
2. Same Python/native binaries where ABI and driver compatibility permit; if a
   rebuild is required, record compiler/CUDA differences.
3. Same model files and hashes, voice registry/reference hash, request corpus,
   UTF-8 bytes, seeds, sampling settings and language/instruction values.
4. Same worker startup, warmup, codec schedule, playback prebuffer, terminal
   postprocessor and output format.
5. Run the same short/medium/long, cancellation/recovery, sequential-worker,
   and selected model-family rows.
6. Listen to the same WAV/physical playback cases and preserve the same receipt
   schema.

The only initially acceptable changes are hardware/runtime selectors that are
strictly necessary (GPU device ID, CUDA architecture selection, driver-specific
DLL path, or an explicitly recorded memory/precision setting). A change to
model, engine revision, quantization, codec window, scheduling, prebuffer or
voice profile is a new experiment, not an A/B result.

Do not compare CMP and RTX numbers directly when any of those inputs differ.
Report a pair as “same workload, different hardware” only when the provenance
manifests are otherwise identical.

## 4. Failure routing

* A driver/device setup failure with identical software artifacts belongs to the
  RTX handoff log and must be separated from a bridge defect.
* A protocol, lifecycle, PCM, packaging, model-loading or playback correctness
  failure returns to CMP development/B2. Reproduce it on CMP with the frozen
  request and attach the failing receipt before changing code.
* A quality regression (empty/near-silent PCM, wrong voice, pronunciation,
  missing EOS, clicks or queue starvation) blocks promotion until the same
  case is explained or fixed on the development machine.
* A performance-only difference is not a correctness failure. Record the
  engine/model/runtime fingerprint and do not “optimize” the code during the
  first RTX reproduction.

## 5. Final beta publication gate

Publish only when all of the following are true:

* the advertised model matrix is explicit and every advertised row has an
  exact real-model acceptance receipt or is clearly marked experimental;
* Python portable package, doctor, model manifests and C++ playback pass in an
  isolated clean environment on CMP 50HX;
* the selected CMP profile has persistent-worker, EOS, cancellation/recovery,
  playback and listening evidence with frozen hashes;
* required P1 hardening (terminal-ID policy/bounded history and bounded pending
  admission) is merged and tested;
* release-facing changelog/status text matches the actual Python baseline and
  optional native/RU-stress boundaries;
* RTX 4090 reproduces the identical workload, or its documented differences
  are accepted as a separate hardware report;
* the final artifact bundle contains binaries, manifests, SHA-256 files,
  request-corpus hash and reports, but no model weights or temporary files.

The beta release must not claim universal Qwen-family support, automatic model
download, effects processing, predictive visemes, or avatar/display sync unless
those are separately accepted in a future scope.
