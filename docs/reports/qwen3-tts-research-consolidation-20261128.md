# Qwen3-TTS research consolidation

Date: 2026-11-28  
Status: active research; this document does not change production defaults,
ABI 6, QTB, model pins, or the frozen R1 package.

## Scope and evidence status

This note consolidates the CMP 50HX phase-2 evidence and the human listening
assessment supplied on 2026-11-28. The layers are kept separate:

1. mechanical execution and code/PCM checks;
2. semantic listening of the named WAV files;
3. release disposition.

The phase-2 source identities remain the Engine #53 and Engine #51 research
candidates (`3a896743ada11cba6bfa7e6fd69c06ec39a10283` and
`541f1f702e725dc002e0e9ebf6f1460dca8c3100`). They are not production pins.
The bridge research heads are `77f625561d40ac575fc075d91826adfa8b9cb06b`
and `ce6b0f30b12dd6b802f19dad5a2d259c6a9005b`, both draft stacked PRs.

The raw WAV, model files, tensor dumps and runner logs remain in ignored
`.tmp/` payloads. This tracked note records their paths and semantic outcome,
not a portable audio package.

## Corrected phase-2 listening result

The exact listening set was `.tmp/listening-pending-20261128/`. The following
results supersede the earlier `human_listening: not_run` handoff; earlier
negative results are preserved.

| Set | Mechanical result | Listening result | Observed semantic result |
| --- | --- | --- | --- |
| A — EOS and first frames | pass | fail | Base controls are normal, but the startup candidate speaks `All right` in the wrong voice and the CF candidate ends at `проце` in `процессор`. |
| B — terminal decoder | pass | partial | All three CF18 variants end at `проце`; all three RU06 variants are normal. Full terminal decoding does not recover the missing phoneme. |
| C — voice stability | pass | partial | The short RU case changes voice in the second half; the remaining tested short/medium/original cases are stable. |
| F — Engine #51 batch | pass | fail | Six WAVs are clean; F07 (`n3-en-short-seed-5204`) has no audible voice. |
| EOS-hold | pass | partial | Base short/long controls are normal. RU/RU-CF short controls remain non-speech; long controls are mostly complete, with a small abrupt-tail defect in two CF cases. |
| ESpeech smoke | pass as execution | fail | `ru-yes` is normal; `ru-ladno` is silent; `ru-medium` loses the final `а`; `ru-long` is complete but too fast. |

Consequently, mechanical `case_result: pass` is not a speech-quality pass.
The canonical structured receipt records the semantic failure and keeps the
release disposition blocked:
[`native-eos-phase2-cmp50hx-20261127.json`](native-eos-phase2-cmp50hx-20261127.json).

### F07 technical audit

The saved F07 records already provide a useful negative-control comparison;
no new GPU run is needed to identify the first boundary. Solo and N=3 both
produce 256 frames, 491,520 samples, `finish_reason: 2` and zero buffered
samples, then retire normally. The first code difference is at frame 125,
codebook 0 (`solo=1318`, `N=3=668`). Thus the batch path does have a numerical
divergence after lane compaction, but the semantic failure is not caused only
by batching: the matched solo artifact is also silent and hits the same
256-frame limit. A merge decision for Engine #51 therefore remains separate
from this model-quality failure; the next useful check is a clean-process
repeat only if a maintainer needs reproducibility evidence.

## Repository and publication state

- Bridge `main` is `2d6de73ab7844f0bf3e4f2b356f8fb4c4220e338`. It contains the
  earlier ledger commit, which was pushed directly to `main`; no further
  direct pushes are allowed.
- Bridge #335 (`77f62556`) and #334 (`ce6b0f30`) are draft research PRs, not
  production merges. Their descriptions must be refreshed separately from
  this consolidation.
- Engine #53 (`3a896743`) and #51 (`541f1f70`) are draft research PRs. The
  unreferenced `1f7f799` EOS-hold commit was not found in the checked remote
  refs and is not treated as published evidence.
- GitHub has no workflow run for bridge `main` at `2d6de73a`; PR checks must
  not be retroactively reported as `main` CI.
- The research worktrees contain unique runners and instrumentation; they are
  not automatically equivalent to the production baseline and must be
  published through separate PRs if they are still needed.

## Durable conclusions

1. Prefill is the dominant warm TTFA component in the native traces (about
   153 ms of about 179 ms for the measured 236-context case). Shortening the
   reference can lower first-PCM latency (about 83 ms versus about 178 ms in
   one matrix), but it is an opt-in latency/voice-identity trade-off, not a
   safe default.
2. Early EOS is reproduced in the original PyTorch path and is not explained
   by terminal WAV flushing alone. `eos-hold`, temperature changes and terminal
   decoder variants do not provide a general fix for the short RU/RU-CF cases.
3. Buffered retry/rollback can recover individual failures only before the
   first irreversible PCM publication. It is a recovery policy with added
   latency, not a model correction.
4. Existing fade/smoothing is appropriate for a sharp but complete tail. It
   cannot recreate a missing phoneme; CF18 is the negative control.
5. Base is more stable on the tested short responses than RU-stress/RU-CF, but
   Base is not a replacement for the required model/profile behaviour of
   controlled Russian stress. The old RU-stress acceptance receipt remains
   historical evidence and is not silently rewritten.
6. Prefix-KV reuse produced a latency gain but failed numerical/audio parity;
   production reuse remains prohibited. ESpeech did not pass the smoke gate.
   MOSS-TTS is still `not_run`.

## Next decision-oriented work

### P0 — finish evidence before new inference

- Keep the corrected receipt and phase-2 listening table indexed.
- Audit F07 with a matched solo run, repeated batch run and clean process;
  compare complete codes, PCM, first mismatch and EOS against supported
  `master`. Make the merge decision for Engine #51 separately.
- The CPU-only fade check is now complete on the saved CF baseline, CF
  `eos-hold-2` and CF18 terminal WAVs. With the current 15 ms fade and 85 ms
  completion silence, all three preserve the emitted prefix byte-for-byte,
  keep a contiguous sample timeline and append exactly 2,040 zero frames at
  24 kHz. CF18 remains a negative semantic control: the postprocessor only
  changes the tail and cannot recreate its missing phoneme. The temporary
  probe and its command are not part of the public API or production path;
  the existing `audio_post_processor_test` and
  `qwen_tts_save_wav_callbacks_test` also passed.

### P0 — model-level hypothesis

Investigate RU-stress LoRA strength before adding another EOS heuristic. The
existing merger uses rank 16 and alpha 32, so the research equation is

\[
W_{merged}=W_{base}+\beta\frac{\alpha}{r}BA,
\qquad \beta\in\{0,0.25,0.5,0.75,1\}.
\]

Start with source-level logits and code diagnostics; do not mass-convert GGUF.
Keep reference, ICL, temperature, sampler and seed fixed. A candidate is useful
only if it improves complete speech on held-out phrases while preserving the
normative stress contrasts (`за́мок/замо́к`, `му́ка/мука́`,
`докуме́нты/до́кументы`) and voice identity. Lower EOS probability by itself
is not a success criterion.

### P1/P2 — bounded follow-up

- Compare natural reference fragments of equal length (8–12 s) to separate
  reference duration from phonetic content.
- Repeat only the three promising temperature settings on fixed new seeds;
  close the direction if no stable advantage appears.
- Keep MOSS-TTS as a separate alternative-model study. Do not continue ESpeech
  integration based on this smoke result.
- Qualify pre-commit retry by recovery rate, false intervention rate, useful
  PCM latency, cancellation and deadline behaviour.

No new broad EOS penalty/hold, full-text ICL or prefix-KV matrix is justified
without a new discriminating hypothesis.
