# R1 P1 release-hardening audit

Status: audit completed against `main` `b4df13e6` on 2026-11-12. This is a
planning and evidence document; it does not freeze an R1 candidate or promote
the native backend.

| Area | Existing implementation and coverage | Finding | Smallest corrective change | R1 impact |
| --- | --- | --- | --- | --- |
| B1 bounded memory | Python voice-profile preflight limits references to 16 MiB and 20 s. C++ `WorkerSession` bounds queued events to 4096 events/16 MiB. Native WAV decoding previously allowed a declared chunk up to 1 GiB and had no duration bound. | **Confirmed P1** for the native reference path: a large or malformed WAV could allocate excessive host memory before model validation. | PR #316 rejects declared WAV chunks above 16 MiB and decoded references above 20 s, before large allocation. | Native Base remains opt-in; merge #316 before any native release-candidate freeze. |
| B2 native reference cache | Python `VoiceProfileRegistry` uses a bounded LRU prompt cache. Native `NativeEngine` stores prepared references in an `unordered_map`; the key includes the path and decoded-sample fingerprint, and the map is cleared on engine close, but dynamic entries have no capacity or eviction. | **Confirmed P1** resource risk for repeated unique clone references in one persistent native worker. Managed profiles are loaded intentionally; request-created entries can grow without a configured bound. | Add an explicit native dynamic-reference capacity with deterministic rejection or eviction, preserving managed-profile entries and reporting the effective limit. Keep this separate from model identity and restart invalidation tests. | Blocks native promotion only; it does not change the Python/Faster R1 baseline. |
| B3 non-finite PCM | Reference float WAV input rejects non-finite samples. Generated Python and native float-to-s16le conversion currently maps non-finite samples to zero. Existing tests cover malformed prepared reference data, but not generated NaN/Inf failure receipts. | **Confirmed P1** correctness risk: invalid model output can become apparently successful silence instead of a failed request. | Reject non-finite generated chunks before conversion in both workers and emit a terminal model/resource error without publishing a successful WAV. Add mock-engine and fake-native regression cases. | Required for a trustworthy release receipt; no model or dtype change is implied. |
| B4 streaming SHA-256 | Native runtime-manifest hashing uses 64 KiB BCrypt chunks. Python worker/doctor/model and voice-library hashes use 1 MiB iteration. Hardware probe hashing is chunked. | **Falsified for runtime paths.** A few receipt-verifier helpers use `Path.read_bytes()` for local evidence, but that is a tooling-only bounded-gate risk rather than a worker allocation defect. | No production refactor now. If large evidence validation becomes a practical CI memory issue, convert that verifier helper to the existing chunked pattern. | No R1 blocker identified. |
| B5 atomic metrics/receipts | `PcmCapture` and native playback interruption diagnostics write a temporary file and rename with rollback. The native hardware probe writes its final JSON with `Path.write_text()` after the worker exits; the latency benchmark also opens its result JSON directly. | **Confirmed P1 for probe receipts:** an interrupted process can leave a partial-looking JSON file at the requested path. Core WAV publication already has atomic handling. | Add one shared local atomic-JSON writer for probe/benchmark receipts (temporary sibling, flush/close, replace; preserve an existing target policy) and fault-injection tests. | Protects acceptance evidence integrity; does not alter synthesis or playback behavior. |

## Decision

The P1 list is intentionally narrow. PR #316 is the first corrective for the
confirmed native input-allocation defect. Native cache capacity, non-finite
PCM rejection, and atomic probe receipts should be separate Draft PRs with
focused regression tests. Streaming SHA-256 is not a reason to rewrite working
runtime code. R1 remains **not frozen** until the corrective PRs and the
independent CMP/RTX/package/listening gates are complete.

The Python/Faster Base route remains the release baseline. Native Base and
RU-stress stay opt-in/experimental, and no hardware result in this audit is a
support claim.
