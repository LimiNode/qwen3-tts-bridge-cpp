# Final pre-release hardening ledger — 2026-10-26

This ledger records the focused batch without treating Draft PRs or missing
hardware evidence as merged release capabilities.

| Work item | Base | Exact HEAD / merge | State | Evidence boundary |
| --- | --- | --- | --- | --- |
| #231 `tts-front-cpp` v0.2.3 | `4cb6703088dc66f8f6be66e38e9fb27ba4c298ea` | `b6c7ccdf7ef601a7db50db32105c64d7fd8b8ad9` | Draft / ongoing | corpus and effective-text tests pass; targeted Russian listening remains open |
| #242 active cancellation/playback | `c4f3ee980110608befc3a8c8f87d226db8eb9eec` | `ac51dd1746377a5b27184a5e310ebb27f7f4fe41` → merge `b62f88badee963f2ad36fec68394a345c1ac63f1` | **Merged** | 6/6 CI; cancellation bounded PASS; audio-only playback PARTIAL; animation epoch NOT RUN |
| #243 production code-quality audit | `b62f88badee963f2ad36fec68394a345c1ac63f1` | `e8936442cd3f493491872f1cae40f8b37f2b5f65` | Draft / 6/6 exact-head CI | native worker, DLL loader, in-process adapter and public-header coverage added; no refactor started |
| #244 VoiceDesign 1.7B gate | `b62f88badee963f2ad36fec68394a345c1ac63f1` | `ccef14f27ddd84de1701eba0f7131d6a488f2dac` | Draft / 6/6 exact-head CI | real model artifact unavailable; status explicitly NOT RUN |
| #246 playback animation epoch initialization | `b62f88badee963f2ad36fec68394a345c1ac63f1` | `7ff46242bd049391cd0e16df08c908081e2c1827` | Draft / 6/6 exact-head CI | initializes the runtime epoch before the animation loop and adds a deterministic idle-tick regression |

## Release blockers and next independent work

- VoiceDesign 1.7B remains a required beta capability, but it needs a real
  CMP 50HX model run, provenance manifest, repeated request/restart evidence,
  and human listening. The current gate does not claim any of these.
- #231 must receive the targeted Russian number/stress listening decision before
  merge.
- Batch-2 refactors must follow the audit as narrow PRs with behavioral,
  negative-path, ABI, and exact-head CI evidence. Do not refactor by line-count
  target alone.
- #243 and #244 were rebased onto the merged #242 main and now have green
  exact-head CI; guarded review is still required before either PR is merged.
- Native DLL, RU-stress, clean-portable, and RTX 4090 validations remain
  separate acceptance gates. Speech-animation/avatar presentation is optional
  and outside mandatory beta acceptance.

Current release decision: **CONDITIONAL GO** for the merged Base/cancellation
plumbing, **NO-GO** for a final beta claim until the required model and
listening gates are complete.
