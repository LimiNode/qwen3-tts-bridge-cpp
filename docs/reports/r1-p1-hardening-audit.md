# R1 P1 release-hardening audit

Status: audit completed against `main` `b4df13e6` on 2026-11-12. This is a
planning and evidence document; it does not freeze an R1 candidate or promote
the native backend.

| Area | Existing implementation and coverage | Finding | Smallest corrective change | R1 impact |
| --- | --- | --- | --- | --- |
| B1 bounded memory | Python voice-profile preflight limits references to 16 MiB and 20 s. C++ `WorkerSession` bounds queued events to 4096 events/16 MiB. Native WAV decoding previously allowed a declared chunk up to 1 GiB and had no duration bound. | **Confirmed P1** for the native reference path: a large or malformed WAV could allocate excessive host memory before model validation. | PR #316 rejects declared WAV chunks above 16 MiB and decoded references above 20 s, before large allocation. | Native Base remains opt-in; merge #316 before any native release-candidate freeze. |
| B2 native reference cache | Python `VoiceProfileRegistry` uses a bounded LRU prompt cache. Native `NativeEngine` stores prepared references in an `unordered_map`; the key includes the path and decoded-sample fingerprint, and the map is cleared on engine close. | **Confirmed P1**, corrected in #316: dynamic request-created entries now have a configurable finite capacity (default 16) and fail with `resource_error/voice_reference_cache_exhausted` when full; managed profile entries remain retained. | Keep model-identity and restart invalidation coverage in the native acceptance matrix. | Native Base remains opt-in; the corrective must pass exact-head CI before any native release-candidate freeze. |
| B3 non-finite PCM | Reference float WAV input rejects non-finite samples. Generated Python and native float-to-s16le conversion previously mapped non-finite samples to zero. | **Confirmed P1**, corrected in #318: both workers reject non-finite generated chunks and fake Python/native regressions assert a terminal failure without successful audio. | Retain the regression on the frozen candidate and verify the installed CLI does not publish a successful WAV after the error. | Required for a trustworthy release receipt; no model or dtype change is implied. |
| B4 streaming SHA-256 | Native runtime-manifest hashing uses 64 KiB BCrypt chunks. Python worker/doctor/model and voice-library hashes use 1 MiB iteration. Hardware probe hashing is chunked. | **Falsified for runtime paths.** A few receipt-verifier helpers use `Path.read_bytes()` for local evidence, but that is a tooling-only bounded-gate risk rather than a worker allocation defect. | No production refactor now. If large evidence validation becomes a practical CI memory issue, convert that verifier helper to the existing chunked pattern. | No R1 blocker identified. |
| B5 atomic metrics/receipts | `PcmCapture` and native playback interruption diagnostics write a temporary file and rename with rollback. The native hardware probe wrote its final JSON with `Path.write_text()` after the worker exited; the latency benchmark also opens its result JSON directly. | **Confirmed P1 for probe receipts**, corrected in #319 for `run-native-hardware-probe.py`: a sibling temporary file is flushed/fsynced and replaced atomically, with fault-injection coverage. The benchmark writer remains a separate diagnostic follow-up. | Extend the same policy to any benchmark receipt that becomes release evidence; keep the existing WAV publication tests. | Protects acceptance evidence integrity; does not alter synthesis or playback behavior. |

## Decision

The P1 list is intentionally narrow. PR #316 contains the native input-bound
and dynamic-cache corrections; #318 covers non-finite PCM; #319 covers atomic
probe receipts. Each remains a separate Draft PR with focused regression
tests. Streaming SHA-256 is not a reason to rewrite working runtime code. R1
remains **not frozen** until the corrective PRs and the independent
CMP/RTX/package/listening gates are complete.

The Python/Faster Base route remains the release baseline. Native Base and
RU-stress stay opt-in/experimental, and no hardware result in this audit is a
support claim.
