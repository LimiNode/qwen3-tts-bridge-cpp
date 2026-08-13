# CMP 50HX code-predictor precision follow-up

Date: 2026-08-07
Scope: source-only diagnostics using the published R3 private Python runtime
read-only. The sealed R3 package was not rebuilt, patched, or used as a source
worker.

## Reproducible source provenance

| component | commit |
| --- | --- |
| broad predictor FP32 parent change | `1a86a48b5ffe37f3604f66a9a691d2b6e1f674bd` |
| broad predictor FP32 Qwen submodule | `d5a4ec4b3cac55cca0087d6a8cd8b9df26bb83c3` |
| final MLP-only diagnostic parent change | `1a5e0aba5ab7fb247ec6cb0ec7f7467c33d36531` |
| final MLP-only Qwen submodule | `1bf5e315d0837ec033e979c6fb4786318ea4bfcb` |

The parent gitlink at the final parent commit resolves to the final submodule
commit. The original broad workaround remains an explicit upstream-only option;
the newer `mlp_float32` mode is a diagnostic candidate, not a CMP runtime
profile.

## Correctness matrix: full predictor FP32

All runs used upstream, eager prefill, SDPA, FP16 main talker,
`--code-predictor-compute-dtype float32`, `--no-compile`,
`--no-cuda-graphs`, and a CUDA UUID mask selecting CMP 50HX as `cuda:0`.

| class | seeds | result |
| --- | --- | --- |
| CustomVoice short | 20260806, 20260807, 20260808 | 3/3 natural EOS |
| CustomVoice medium | 20260806, 20260807, 20260808 | 3/3 natural EOS |
| CustomVoice long | 20260806 | cancelled by external client timeout after 600.244 s; no EOS |
| Base medium, `kraftwerk_robot_ru_bootstrap_fidelity` | 20260806 | natural EOS |

The six completed CustomVoice short/medium runs recorded finite completion,
natural EOS, completion metadata, and no max-sequence or max-new-token
termination. The long run emitted 118 PCM chunks / 3,624,850 bytes / 75.518 s
of audio before the client cancelled it. This is not a numerical assertion and
is not counted as a pass; the remaining long seeds were deliberately not run.

Base smoke completed with 24 chunks, 714,214 bytes, 186 codec frames, natural
EOS, and no max-limit termination.

## WAV sanity

The seven EOS WAVs were checked mechanically for PCM format, peak, RMS, DC,
clipping, silence windows, and zero-crossing density. They had no clipping,
small DC offset, and the longest contiguous low-RMS interval was 1.3 s.
A representative CustomVoice medium WAV was rendered through the current
default audio device. These checks do not establish linguistic quality or rule
out semantic repetition; human listening remains a separate quality gate.

## One precision-island A/B diagnostic

Same medium CustomVoice request and fixed seed 20260806:

| mode | terminal | TTFA | synthesis | frames | audio | RTF |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| A: full predictor FP16 | device-side assert | — | — | — | — | — |
| B: full predictor FP32 | EOS | 9,985.730 ms | 184,376.297 ms | 280 | 22.398 s | 8.231927 |
| C: MLP-only FP32 | EOS | 10,158.100 ms | 222,278.929 ms | 309 | 24.716 s | 8.993215 |

For C, the committed source at `1a5e0aba…` was rerun with a read-only trace:
23,251 observations across code-predictor layer outputs and 2048-way softmax
inputs/outputs contained zero NaN and zero positive/negative infinity values.

C proves that the gated-MLP/down-projection FP32 island eliminates the observed
first non-finite for this request. It does not show a performance advantage:
the autoregressive trajectories differ and C has a worse observed RTF. Neither
B nor C is a realtime profile.

## Sealed package verification

Package-tree and voice-assets verifiers both passed after all source runs. The
verified package manifest digest remains
`c2a5133e843d5660b2fd0ca3c2b633f54154195c6fc1c76e7d0994542211ecfc`.

## Conclusion

The original FP16 overflow root cause remains accepted. Broad predictor FP32 is
a reproducible diagnostic/reference mitigation. The narrower MLP-only island is
causally effective for the tested medium input, but has no measured performance
win and is not promoted beyond a diagnostic candidate. The long no-EOS case and
the incomplete human quality assessment prevent promotion of either option to a
supported CMP compatibility policy.
