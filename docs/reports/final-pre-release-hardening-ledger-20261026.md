# Final pre-release hardening ledger — 2026-10-26

This ledger records the focused batch without treating Draft PRs or missing
hardware evidence as merged release capabilities.

| Work item | Base | Exact HEAD / merge | State | Evidence boundary |
| --- | --- | --- | --- | --- |
| #231 `tts-front-cpp` v0.2.3 | `4cb6703088dc66f8f6be66e38e9fb27ba4c298ea` | `b6c7ccdf7ef601a7db50db32105c64d7fd8b8ad9` | Draft / ongoing | corpus and effective-text tests pass; targeted Russian listening remains open |
| #242 active cancellation/playback | `c4f3ee980110608befc3a8c8f87d226db8eb9eec` | `ac51dd1746377a5b27184a5e310ebb27f7f4fe41` → merge `b62f88badee963f2ad36fec68394a345c1ac63f1` | **Merged** | 6/6 CI; cancellation bounded PASS; audio-only playback PARTIAL; animation epoch NOT RUN |
| #243 production code-quality audit | `c4f3ee980110608befc3a8c8f87d226db8eb9eec` | `998f971519bfe291ed69fc4c8611dad78c030a0a` | Draft | evidence-backed inventory only; no refactor started |
| #244 VoiceDesign 1.7B gate | `c4f3ee980110608befc3a8c8f87d226db8eb9eec` | `a1f00f79cce7efa2a6ff112c6ffb437935f181be` | Draft | real model artifact unavailable; status explicitly NOT RUN |
| #246 playback animation epoch initialization | `b62f88badee963f2ad36fec68394a345c1ac63f1` | `5c46d7cc51cf5987c6b4bfc3e0da1cbefd41be7b` | Draft | fixes early animation-loop tick publishing epoch zero; exact-head CI pending |

## Release blockers and next independent work

- VoiceDesign 1.7B remains a required beta capability, but it needs a real
  CMP 50HX model run, provenance manifest, repeated request/restart evidence,
  and human listening. The current gate does not claim any of these.
- #231 must receive the targeted Russian number/stress listening decision before
  merge.
- Batch-2 refactors must follow the audit as narrow PRs with behavioral,
  negative-path, ABI, and exact-head CI evidence. Do not refactor by line-count
  target alone.
- Native DLL, RU-stress, clean-portable, and RTX 4090 validations remain
  separate acceptance gates. Speech-animation/avatar presentation is optional
  and outside mandatory beta acceptance.

Current release decision: **CONDITIONAL GO** for the merged Base/cancellation
plumbing, **NO-GO** for a final beta claim until the required model and
listening gates are complete.
