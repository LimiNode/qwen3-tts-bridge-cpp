# CMP 50HX R3 independent hardware acceptance

> Historical hardware acceptance summary (2026-08-06). It records one bounded run and is not a current release gate. Raw machine artifacts are intentionally local-only and are not part of this curated documentation set.

Outcome: passed with observations.

The physical package under `tmp/QwenTTSBridge-technical-beta-r3` was used;
`dist` from the Git checkout was not used. No package file was created,
replaced, or rebuilt.

The pre- and post-smoke full sealed-tree checks both passed: 34,644 files and
2,793 directories match `c2a5133e843d5660b2fd0ca3c2b633f54154195c6fc1c76e7d0994542211ecfc`.
The voice-assets manifest also matched before and after:
`2681e43af18a677aac5720bb57bd9ca5355a20557ddbd8d60b50391aa45ef515`.

The packaged doctor confirmed the target device as NVIDIA CMP 50HX, capability
7.5, 20 GiB VRAM, driver 581.94, Torch 2.10.0+cu128, and CUDA runtime 12.8.
It passed before and after smoke for both external, pinned model revisions.

Both isolated native C++ smokes used only package `bin`, package private
`python.exe`, package site-packages, and external offline caches. They did not
use a development checkout, external Python, or MinGW.

| Request | Terminal evidence |
| --- | --- |
| CustomVoice | `completed`; natural `eos`; 213,930 PCM bytes; 7 chunks; 56 codec frames; no max-token or max-sequence termination |
| Base `kraftwerk_robot_ru_bootstrap_fidelity` | `completed`; natural `eos`; 174,496 PCM bytes; 6 chunks; 46 codec frames; no max-token or max-sequence termination |

No 8,8,12 frequency profile, canary manifest, compiled allowlist, or emitted
schedule was supplied. Both invocations explicitly requested eager prefill and
disabled requested compile/CUDA-graph options. The captured Base metric reports
the default chunk schedule, not 8,8,12. FasterQwen nevertheless wrote internal
predictor/talker CUDA graph capture messages to stderr; this is retained as an
observation rather than represented as absence of all internal graph behavior.

The CustomVoice external content digest matches historical R3 evidence. The
Base external content digest differs from that historical value, although the
Hugging Face API confirmed the requested pinned Base revision and packaged
doctor accepted the complete external model manifest. This discrepancy is
recorded in the JSON report and was not altered.

Three failed setup invocations (missing model manifests, malformed CLI worker
argument tokenization, and the unsupported `.cmd` launcher path) are also
recorded verbatim in the JSON. The final direct-private-Python harness path is
the published R3 relocation contract and produced the acceptance evidence.
