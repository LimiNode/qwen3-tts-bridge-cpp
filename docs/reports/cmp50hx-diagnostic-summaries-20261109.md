# Curated CMP 50HX diagnostic summaries

Status: historical documentation only. These summaries preserve the decision-relevant
human-readable conclusions from the August 2026 CMP 50HX work. They are not a
current release gate, a production-support declaration, or a replacement for
the canonical acceptance receipts.

Raw JSON, JSONL, worker logs, profiler reports, and audio artifacts remain
local-only. Their omission from this PR is deliberate: the summaries retain
the tested revision, hardware binding, observed result, and decision boundary
without pretending that untracked raw files are available to downstream
readers.

## Included summaries

| Summary | Evidence status | Decision-relevant result |
| --- | --- | --- |
| [R3 independent hardware acceptance](cmp50hx-r3-hardware-acceptance-rerun-2026-08-06.md) | Passed with observations | Sealed R3 package completed CustomVoice and Base natural-EOS smokes on CMP 50HX; package and voice manifests remained unchanged. |
| [PCM production diagnostic](cmp50hx-audio-underrun-diagnostic-2026-08-06.md) | Confirmed diagnostic observation | PCM arrival was slower than realtime for the tested CustomVoice and Base requests; pull-level physical sink underrun was not measured. |
| [FasterQwen realtime profile](cmp50hx-realtime-profile-187d450.md) | Realtime gate failed | BF16/eager completed the sampled corpus but remained above RTF 1; FP16 reproduced the failure and was rejected for that wheel/runtime. |
| [Upstream FP16 root cause](cmp50hx-source-upstream-fp16-root-cause-187d450.md) | Root-cause diagnostic | The sampled CMP failure was a code-predictor FP16 non-finite path, not evidence of a playback-buffer defect or a FasterQwen-only graph defect. |
| [Upstream FP16 mitigation](cmp50hx-source-upstream-fp16-fix-187d450.md) | Correctness validated, performance gate failed | An upstream-only FP32 code-predictor option reached natural EOS, but the measured RTF was 8.04 and no realtime claim follows. |
| [Upstream source smoke](cmp50hx-source-upstream-smoke-187d450.md) | Smoke passed, realtime not established | The pinned source upstream path completed natural EOS on CMP 50HX, but the run was diagnostic-only and measured RTF 11.43. |

## Interpretation

The reports form an evidence chain, not six independent release approvals:

1. The sealed R3 package was exercised successfully on the target device.
2. The same hardware then showed that the tested streaming production path could
   not sustain realtime PCM arrival.
3. Separate source diagnostics localized an FP16 numerical failure and tested
   an upstream correctness mitigation.
4. None of those experiments promoted a FasterQwen profile, a playback-buffer
   change, or an R4/runtime policy.

The older blocked A/B attempts and intermediate FP32-island reports remain
local historical material. They are omitted here because they duplicate these
decision boundaries or depend on raw artifacts that are not published.
