# Codec decoder research

## Decision sequence

PRs #53-#57 isolated `speech_tokenizer.decode` after profiling showed it was
the dominant cold residual. Each candidate had to pass natural EOS, equal
format and length, codec-token comparison, an explicit PCM gate, and only then
a timing/physical-playback soak.

| Candidate | Correctness result | Performance result | Decision |
| --- | --- | --- | --- |
| Left-padded `decode_streaming` (#53) | Identical 63-frame codec digest, but every PCM chunk changed and the first grew by 444 samples | One smoke showed no proxy | Rejected before timing promotion |
| Right-padded fixed input (#54) | 240810 bytes, natural EOS; RMS 2.845, SNR 55.458 dB, max delta 52 | RTF 1.156/1.152 to 0.966/0.962 in first pair | Accepted foundation |
| Compiled decoder (#55) | Failed PCM quality gate | Not promoted | Rejected |
| Manual decoder CUDA Graph (#56) | Exact SHA-256 `747bfd9afd3a004cf545c92beb25e06dd55cbda1dd6b6a13f347a52689a19c1a` in tested pair | 4.09% and 5.04% synthesis reductions; 10/10 soak | Accepted |
| W48 manual graph (#57) | RMS 2.763, SNR 55.710 dB, max delta 56 | 10.78-12.33% faster than W80; mean RTF 0.860922; 10/10 soak | Accepted research, later superseded |

The quality envelope used for non-identical s16le PCM was:

```text
RMS delta <= 3
SNR >= 55 dB
maximum absolute delta <= 64
```

The right-padded input contract allowed at most 25 history frames plus the
largest configured emission chunk. The launcher and Faster implementation both
failed closed if an actual decoder input exceeded that bound.

## Reproduction

Capture deterministic control and candidate PCM separately, never as a timing
run, then compare them with:

```powershell
python .\scripts\compare-cmp50hx-pcm-parity.py `
  --expected .\tmp\control.pcm `
  --candidate .\tmp\candidate.pcm `
  --output .\tmp\pcm-parity.json `
  --max-rms-delta 3 --min-snr-db 55 --max-abs-delta 64
```

If lengths differ, generation traces must be compared before attributing the
difference to the codec. See
[PCM parity and graph evidence](../cmp50hx-playback-investigation.md#pcm-parity-gate-for-the-fixed-shape-candidate)
for run identifiers and the complete command matrix.

The local patch/shadow mechanism was retired when #58 pinned a versioned
FasterQwen source. Production #63-#66 subsequently selected W33 and W29 graphs
for the E8/E4/E3 profile ladder.
