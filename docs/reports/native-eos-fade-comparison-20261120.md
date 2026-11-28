# Offline seed-65 ending-level comparison

Research diagnostic, 2026-11-20; CMP 50HX / RU-stress Q8_0 / Kraftwerk,
frontend OFF. No new inference, listening, normalization or runtime change.
R1 remains **NO-GO**. This is not a new acceptance receipt.

## Finding

The user heard gradual fading toward the end of the batch seed-65 WAV while
confirming its full correct phrase. The
[listening receipt](native-eos-prefix-listening-cmp50hx-20261120.json) preserves
that observation. A matched-seed offline comparison finds a similar quieter
late portion in the retained single-slot seed-65 output. It does **not**
support a substantial batch-only global attenuation ramp for this pair.

The contour is not monotonically decreasing. In the batch output, RMS rises
again to 0.0532894 at 6.0–6.5 s, then falls to 0.0272038 at 6.5–7.0 s and
0.00800446 at 7.0–7.2 s. Lower late energy is not explained solely by the final
low-level tail. Its perceptual severity and cause remain unresolved: these
measurements do not isolate prosody, conditioning, model or codec behavior.

## Matched cases and method

All paths below are relative to
`.tmp/base-acceptance/eos-reseed-branching-20261120/matrix-final-006/`:

| Case | Raw/WAV stem | Continuation seed |
| --- | --- | ---: |
| Single slot | `single-seed-2-frames-1/group-3-lane-0` | 65 |
| Batch, user-reported fade | `dual-seed-2-frames-1/group-1-lane-1` | 65 |
| Repeated batch | `dual-seed-2-frames-1/group-5-lane-1` | 65 |

These are baseline continuations with one complete seed-2 frame teacher-forced,
not live forks. Source manifests match the text, conditioning, model/codec,
reference length, generation cap, deadline and chunk cap; max batch is 1/2.
All three have natural EOS, 90 identical complete 16-codebook frames and
172800 samples (7.20 s). The repeated batch raw PCM is bit-identical.

The retained stdlib Python 3.11.9 script reads little-endian f32 without gain
processing and checks the WAV structure and every PCM16 sample. RMS is
`sqrt(sum(x*x)/N)`; the batch/single ratio is `20*log10(RMS_batch/RMS_single)`.
The fitted scalar gain is `sum(single*batch)/sum(single*single)`.
Nonoverlapping windows are 500 ms, with a final 200-ms window. Separately,
20-ms RMS windows are filtered at 0.005 and 0.01; medians are calculated within
each fixed 2.4-s third. These thresholds are descriptive, **not** VAD, phoneme
alignment, perceptual loudness or a production gate.

## Measurements

| Property | Single | Batch |
| --- | ---: | ---: |
| Whole-file RMS | 0.04989142 | 0.04987829 |
| Whole-file RMS dBFS | -26.03948 | -26.04177 |
| Median 20-ms RMS >=0.01, 0–2.4 s | 0.04994684 | 0.04994921 |
| Same, 2.4–4.8 s | 0.06479260 | 0.06490888 |
| Same, 4.8–7.2 s | 0.03379642 | 0.03377299 |

The batch late-third median is about -3.40 dB relative to the early third and
-5.67 dB relative to the middle; the single output has essentially the same
trend. Both contain 20-ms windows with RMS >=0.005 through 7.06 s, followed
by about 0.14 s of lower-level audio, not a proven silence/VAD boundary.
Different phonemes naturally have different energy; the thirds do not align
identical spoken words and cannot establish an unwanted prosody defect.

The whole-file batch-minus-single RMS ratio is **-0.002285 dB**. Fitted gain
is 0.99955087 (-0.003902 dB); windowed fitted gains range from -0.014698 to
+0.007700 dB. Correlation is 0.99981391. Nevertheless, raw PCM differs:
difference RMS is 0.00096248 and peak absolute difference is **0.06440735**.
These are not bit-equivalent outputs or an inaudibility finding. The peak is
specific to this pair, not the smaller differences in other lane comparisons.

## Capture and conversion boundary

Every sample of each WAV exactly matches
`clip(round(raw_f32*32768), -32768, 32767)`. All samples are finite, peaks are
below 0.268, and none clips. Thus WAV conversion introduces no fade or gain.
The research probe appends callback floats unchanged and writes them verbatim;
the runner only applies that fixed quantization. Source inspection found no
explicit fade/normalization in the inspected capture and codec path. It does
not establish the cause of the shared contour.

Chunk boundaries match through 6.96 s. Single ends with boundaries at 7.12 and
7.20 s, batch at 7.04 and 7.20 s after the other lane retires. This final split
cannot explain a contour beginning substantially earlier. Other possible
batch-dependent artifacts are not ruled out by one matched pair.

## Retention and next boundary

The [diagnostic metadata](native-eos-fade-comparison-20261120.json) records
exact artifact identities and descriptive results. The ignored script,
generated comparison and envelope CSV remain in `fade-analysis-008/` under
the same payload root; five model-free self-checks passed. Do not overwrite
these hashed files. The script and raw audio are **not transferred by Git**;
an independent reproduction needs those verified payloads. The formulas and
case mapping above permit an independent offline calculation.

At the time of this offline analysis, single seed 65 had no listening verdict;
the earlier listened single candidate was seed 64. Numerical checks alone
did not change that status.

On 2026-11-21 the user listened to the specifically linked single seed-65 WAV
and reported slight fading, no noticeable difference from the earlier track,
and that the effect was less noticeable at medium/high playback volume. The
follow-up assessment was that the effect was effectively absent. The
[new scoped receipt](native-eos-seed65-listening-cmp50hx-20261121.json) preserves
this uncertainty and leaves general quality and text-coverage reassessment
open. This is an informal comparison, not calibrated loudness equivalence or
an inaudibility finding. No actionable fade defect is established here.

No state fork, selector, EOS fix, default change or release promotion follows
from this diagnostic or feedback. Preserve the earlier listening history;
broader corpus and actual streaming decision/commit timing remain next work.
