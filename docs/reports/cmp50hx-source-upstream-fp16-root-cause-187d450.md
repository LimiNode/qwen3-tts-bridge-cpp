# CMP 50HX upstream FP16 root-cause diagnostic

> Historical diagnostic summary (August 2026). It records a bounded experiment and is not a current release gate. Raw machine artifacts are intentionally local-only and are not part of this curated documentation set.

Date: 2026-08-07. This was a source-built diagnostic worker at commit
`187d450eb6a9c76e9334b3488468d7949fc34f9f` with Qwen streaming submodule
`6db590f3614a2243239f8047066d190ae9125852`. The physical R3 package supplied
only read-only private Python/Torch dependencies and was not modified.

## Finding

The matching medium CustomVoice request reproduced a non-finite FP16 path in
the upstream code-predictor generation. The first sampling call produced a
finite probability row; the second produced a row containing NaN. The invalid
row violated the positive-sum invariant required by `torch.multinomial`, which
then raised the observed `aten::_assert_async` / `TensorCompare.cu:109`
device-side assertion. Worker exit and Event ID 153 were consequences of the
poisoned CUDA context, not the primary cause.

## Boundary

The first sampling call in the main talker was correct. The failing path was
the legacy `self.code_predictor.generate()` branch used by the sub-talker or
codebook predictor. The exact layer creating the first non-finite score was not
instrumented, so this report does not claim a more specific layer-level cause.
The evidence establishes a precision-sensitive FP16 path on Turing CC 7.5; it
does not establish a hardware defect or a playback-buffer defect.

## Control conditions

- CMP 50HX UUID `GPU-40361931-6cb5-ac58-a059-5ba3e70986fb`, worker `cuda:0`;
  the GTX 1060 was not visible to the worker.
- External CustomVoice model, Russian medium request, speaker `ryan`, seed
  `20260806`, 24 kHz mono.
- Upstream runtime, eager execution, `--no-compile`, `--no-cuda-graphs`, and
  `CUDA_LAUNCH_BLOCKING=1`.
- FP16 produced no PCM and no EOS. A matching BF16 smoke reached natural EOS;
  that is a precision control, not a performance comparison.

## Decision

Do not promote FP16 to a CMP profile or continue FP16 throughput/playback
tuning from this evidence. BF16/eager remained the checked fallback, although
the separate realtime measurements were still above RTF 1. A later
source-only code-predictor tracing experiment or mitigation requires its own
acceptance; it does not change the sealed R3 package.

Raw stderr, provenance, and JSON artifacts are retained locally and
intentionally omitted from this curated documentation set.
