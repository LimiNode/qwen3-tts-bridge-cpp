# Final pre-release hardening ledger — 2026-10-26

This ledger records the focused batch without treating Draft PRs or missing
hardware evidence as merged release capabilities.

| Work item | Base | Exact HEAD / merge | State | Evidence boundary |
| --- | --- | --- | --- | --- |
| #231 `tts-front-cpp` v0.2.3 | `4cb6703088dc66f8f6be66e38e9fb27ba4c298ea` | `b6c7ccdf7ef601a7db50db32105c64d7fd8b8ad9` | Draft / ongoing | corpus and effective-text tests pass; targeted Russian listening remains open |
| #242 active cancellation/playback | `c4f3ee980110608befc3a8c8f87d226db8eb9eec` | `ac51dd1746377a5b27184a5e310ebb27f7f4fe41` → merge `b62f88badee963f2ad36fec68394a345c1ac63f1` | **Merged** | 6/6 CI; cancellation bounded PASS; audio-only playback PARTIAL; animation epoch NOT RUN |
| #243 production code-quality audit | `b62f88badee963f2ad36fec68394a345c1ac63f1` | `e8936442cd3f493491872f1cae40f8b37f2b5f65` → merge `db3012401c9385470b832eb97fde8fd53e5e73ab` | **Merged** | native worker, DLL loader, in-process adapter and public-header coverage added; no production refactor started |
| #244 VoiceDesign 1.7B gate | `b62f88badee963f2ad36fec68394a345c1ac63f1` | `ccef14f27ddd84de1701eba0f7131d6a488f2dac` → merge `713f3a4bdafed86338260f99b4fe49e1ca659433` | **Merged** | documentation gate was intentionally NOT RUN; superseded by the real conditional receipt below |
| #246 playback animation epoch initialization | `b62f88badee963f2ad36fec68394a345c1ac63f1` | `7ff46242bd049391cd0e16df08c908081e2c1827` → merge `dda89a7186a682bc8d0d0299a3b47eddf2cf5a5a` | **Merged** | initializes the runtime epoch before the animation loop and adds a deterministic idle-tick regression |
| #247 VoiceDesign 1.7B hardware receipt | `713f3a4bdafed86338260f99b4fe49e1ca659433` | `76136c32241538fad34bb67161791fa9d11485b1` | Draft / acceptance evidence | CMP 50HX real model load, WAV, persistent repeat and restart pass; natural EOS is conditional on faster runtime trace corrective; human listening remains open |

## Release blockers and next independent work

- VoiceDesign 1.7B now has a real CMP 50HX receipt: the exact Hugging Face
  revision and 13-file SHA-256 manifest are recorded, upstream full-audio and
  faster streaming WAV generation pass, and persistent repeat/restart evidence
  is present. Natural EOS is blocked only by the missing VoiceDesign trace in
  the pinned faster runtime; the corrective is tracked separately in
  `faster-qwen3-tts` PR #4. Human intelligibility and instruction-adherence
  listening remains open.
- #231 must receive the targeted Russian number/stress listening decision before
  merge.
- Batch-2 refactors must follow the audit as narrow PRs with behavioral,
  negative-path, ABI, and exact-head CI evidence. Do not refactor by line-count
  target alone.
- #243, #244 and #246 are merged with guarded exact-head CI. #247 is the
  evidence-only VoiceDesign follow-up and must not be treated as a beta support
  claim until the EOS corrective and human listening gates are complete.
- Native DLL, RU-stress, clean-portable, and RTX 4090 validations remain
  separate acceptance gates. Speech-animation/avatar presentation is optional
  and outside mandatory beta acceptance.

Current release decision: **CONDITIONAL GO** for the merged Base/cancellation
plumbing and **CONDITIONAL** for Python VoiceDesign model execution; **NO-GO**
for a final beta claim until the faster-runtime EOS corrective, human listening,
and the remaining native/RU-stress/portable/RTX gates are complete.
