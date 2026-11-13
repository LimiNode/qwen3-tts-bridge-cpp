# R1 P1 release-hardening audit

Status: pre-freeze audit completed against `main`
`8b19399cb84eb81556f84f2542bfae337c41b46f` on 2026-11-13. PRs #316, #318
and #319 are merged and their post-merge CI is green. This document completes
the pre-freeze checks; it does not itself freeze an R1 candidate or promote
either backend.

The R1 sequence is intentionally ordered as:

`Pre-freeze checks -> Freeze RC -> hardware/package/listening acceptance -> Release`

Hardware and release-package acceptance must run against the newly frozen
candidate. They are not prerequisites for deciding which exact candidate to
freeze, and they must not be silently attached to an earlier preparation
baseline.

| Area | Existing implementation and coverage | Finding | Smallest corrective change | R1 impact |
| --- | --- | --- | --- | --- |
| B1 bounded memory | Python voice-profile preflight limits references to 16 MiB and 20 s. C++ `WorkerSession` bounds queued events to 4096 events/16 MiB. Native WAV decoding previously allowed a declared chunk up to 1 GiB and had no duration bound. | **Confirmed P1, corrected**: the native reader rejects each declared `fmt `/`data` chunk above 16 MiB and decoded references above 20 s before large allocation. The 16 MiB limit is per chunk; the duration limit is on decoded audio. | PR #316 is merged. Retain the boundary in native package and acceptance tests. |
| B2 native reference cache | Python `VoiceProfileRegistry` uses a bounded LRU prompt cache. Native `NativeEngine` stores prepared references in an `unordered_map`; the key includes the path and decoded-sample fingerprint, and the map is cleared on engine close. | **Confirmed P1, corrected** in #316: dynamic request-created entries have a configurable finite capacity (default 16) and fail with `resource_error/voice_reference_cache_exhausted` when full; managed profile entries remain retained. | PR #316 is merged. Keep model-identity and restart invalidation coverage in the native acceptance matrix. |
| B3 non-finite PCM | Reference float WAV input rejects non-finite samples. Generated Python and native float-to-s16le conversion previously mapped non-finite samples to zero. | **Confirmed P1, corrected** in #318: both workers reject non-finite generated chunks and regressions assert a terminal failure without successful audio. | PR #318 is merged. Verify the installed CLI does not publish a successful WAV after the error. | Required for a trustworthy release receipt; no model or dtype change is implied. |
| B4 streaming SHA-256 | Native runtime-manifest hashing uses 64 KiB BCrypt chunks. Python worker/doctor/model and voice-library hashes use 1 MiB iteration. Hardware probe hashing is chunked. | **Falsified for runtime paths.** A few receipt-verifier helpers use `Path.read_bytes()` for local evidence, but that is a tooling-only bounded-gate risk rather than a worker allocation defect. | No production refactor now. If large evidence validation becomes a practical CI memory issue, convert that verifier helper to the existing chunked pattern. | No R1 blocker identified. |
| B5 atomic metrics/receipts | `PcmCapture` and native playback interruption diagnostics write a temporary file and rename with rollback. The native hardware probe and matrix receipts now publish through sibling temporary files. | **Confirmed P1, corrected** in #319 for `run-native-hardware-probe.py`; the packaged-worker benchmark and native/Python matrix now use flushed/fsynced atomic publication as well. Fault-injection coverage remains on the probe path. | PR #319 is merged. Treat benchmark JSON as diagnostic/release evidence only when it is retained with its manifest and validated schema. | Protects acceptance evidence integrity; does not alter synthesis or playback behavior. |

## Decision

The P1 list is intentionally narrow. PR #316 contains the native input-bound
and dynamic-cache corrections; #318 covers non-finite PCM; #319 covers atomic
probe receipts. All three are merged with successful post-merge CI. Streaming
SHA-256 is not a reason to rewrite working runtime code. The audit is a
pre-freeze gate: after the corrective candidate passes exact-head checks, the
resulting full revision and manifests are frozen, and only then do the
independent CMP/RTX/package/listening gates run. R1 is currently **not
frozen**; the installed real-model CLI prerequisite and those post-freeze
acceptance gates remain open.

R1 now evaluates native qwentts.cpp/GGUF and Python/Faster as equally rigorous
backend tracks, with native Base as the priority candidate for local inference.
Native Base and RU-stress are still conditional until their dual-GPU,
packaging, lifecycle, quality and listening gates pass; Python remains a
maintained alternative for model families not covered by native. No hardware
result in this audit is a support claim.
