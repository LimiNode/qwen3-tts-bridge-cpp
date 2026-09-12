# CMP 50HX native reference bisection — 2026-09-13

This experiment isolates the semantic long-output regression observed in the
native registered Base path. It is diagnostic evidence, not release acceptance:
the post-fix WAV still requires listening and voice-identity review.

## Method

The same Base GGUFs, mono 24 kHz reference WAV, Russian transcript, target
text, language, and seed (`1234`) were used for four pre-fix runs:

1. raw reference audio;
2. cached `qt_voice_ref` from the registered voice profile;
3. raw reference audio with 500 ms trailing silence;
4. cached `qt_voice_ref` extracted from that same padded WAV.

The raw and cached cases produced exactly the same 237 codec frames (18.96 s)
before the change. The padded cases produced 152 frames (12.16 s) in both raw
and cached modes. This rules out the cache as the semantic cause and confirms
the reference-boundary hypothesis documented by FasterQwen: the final ICL
codec frames must represent silence rather than the last phoneme of the
recording.

The native worker now appends 0.5 s of zero 24 kHz samples immediately after
every ICL reference WAV decode. Registry preload and per-request raw extraction
therefore use identical conditioning, and the cache key includes the padded
sample vector. `x_vector_only` references deliberately remain unmodified; the
speaker-embedding path does not use ICL codec context.

## Post-fix verification

Running the original (unpadded) WAV through the fixed worker produced 152
frames / 12.16 s in both modes:

| Mode | Cache hit | First PCM | Codec frames | Duration | EOS |
| --- | ---: | ---: | ---: | ---: | --- |
| raw reference | no | 3876.3 ms | 152 | 12.16 s | natural |
| registered cached reference | yes | 1474.2 ms | 152 | 12.16 s | natural |

The captured post-fix WAVs are byte-identical for the fixed seed (SHA-256
`6ac364c844431490d741e4310837f2fb49ad6c569dd1ce2745fb996de4ecaa51`). The
probe now supports `--output-wav`; the local captures remain outside git so
the repository stores only their sanitized hash and measurements.

## Multi-seed semantic soak

The 10-seed registered-voice soak confirms that the boundary fix is causal but
not sufficient to close the semantic blocker. Eight seeds produced natural EOS
between 2.08 s and 37.52 s; one seed produced 163.84 s and hit
`max_tokens`. The frame counts were:

```text
156, 147, 464, 197, 155, 156, 26, 469, 2048, 85
```

Therefore the evidence now claims a **confirmed causal factor**, not a fully
resolved cause of the old 41-second runaway. The remaining work is generation
trajectory analysis (prompt geometry, sampling/EOS behavior, and listening to
the captured WAVs), not another latency claim.

First PCM remains a separate performance characteristic: raw extraction pays
the speaker/codec conditioning cost, while the registered path reuses it. The
semantic output trajectory now matches the padded pre-fix control for the
fixed-seed bisection in both paths; the multi-seed soak still shows outliers,
including a max-token termination, so no semantic acceptance is claimed.

Sanitized machine-independent measurements are stored in
[`evidence/cmp50hx-native-reference-bisection-ab734.json`](evidence/cmp50hx-native-reference-bisection-ab734.json).

## Remaining acceptance gates

This fix does not claim that native TTS is release-ready. The next required
checks are listening and voice-identity comparison, then long-text,
cancellation, restart/recovery, direct-reference native-vs-Faster parity, and
the separate registered-voice/prefix-KV Faster baseline.
