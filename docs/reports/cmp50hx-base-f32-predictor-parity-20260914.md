# Base F32 predictor parity probe — 2026-09-14

This is a diagnostic comparison, not a production acceptance result. It
compares the official Qwen3-TTS 1.7B Base checkpoint through the Python
reference path and qwentts.cpp with F32 GGUF weights. No EOS, sampling,
minimum-token, temperature, top-k/top-p, repetition-penalty, or Philox policy
was changed.

## Provenance

| Item | Value |
| --- | --- |
| Hugging Face checkpoint | Qwen3-TTS-12Hz-1.7B-Base |
| HF revision | fd4b254389122332181a7c3db7f27e918eec64e3 |
| qwentts.cpp runtime | ed3c6658d448d762f71e903b53676d5561dd7cee |
| predictor-logit diagnostic | qwentts PR #11, 7ef9182 (not yet merged at capture time) |
| quantization | F32 Talker and F32 12 Hz tokenizer GGUF |
| mode | Base ICL / greedy, English, seed 42, two generated frames |
| reference | examples/freeman.wav + examples/freeman.txt |

The raw dumps and WAV are machine-local diagnostic outputs and are not
committed. The run used the opt-in dump path; normal qwentts execution does
not read predictor logits back from the device.

## Observed results

The textual prompt tokenization matched exactly (38/38 IDs). Reference codec
codes matched at 96.34% (3314/3440 values), so this run is not yet a strict
same-conditioning model parity test: the native codec encoder and the Python
tokenizer still produce 126 different reference code values.

The Talker prefill logits nevertheless had cosine similarity 0.999965.
First-frame predictor logits were:

| Predictor step | Cosine similarity | Max absolute error |
| ---: | ---: | ---: |
| 0 | 0.999959 | 2.16e-1 |
| 1 | 0.999960 | 2.72e-1 |
| 2 | 0.999991 | 1.83e-1 |
| 3 | 0.999995 | 1.79e-1 |
| 4 | 0.999996 | 2.04e-1 |
| 5 | 0.999997 | 2.01e-1 |
| 6 | 0.999996 | 1.76e-1 |
| 7 | 0.999997 | 1.80e-1 |
| 8 | 0.999998 | 1.75e-1 |
| 9 | 0.999998 | 1.62e-1 |
| 10 | 0.999998 | 1.31e-1 |
| 11 | 0.999998 | 1.37e-1 |
| 12 | 0.999999 | 1.26e-1 |
| 13 | 0.999999 | 1.21e-1 |
| 14 | 0.998731 | 3.79 |

The first selected-token divergence occurred at predictor step 13
(codebook index 14): native selected 122, Python selected 1100. The two
logits were nearly tied, so this is a numerically sensitive argmax boundary,
not evidence of an RNG or sampler bug. Once that token differs, step 14
diverges substantially (max absolute error about 3.79) because its history
contains a different preceding code.

## Forced same-conditioning replay

The harness then exported the Python speaker embedding as raw F32 and the
Python reference codes as the native packed RVQ stream. Native qwentts was
rerun with --ref-spk and --ref-rvq, so both stacks consumed exactly the same
conditioning tensors.

The forced replay produced:

| Check | Result |
| --- | --- |
| Reference codes | 3440/3440 exact |
| Speaker embedding | cosine 1.000000, max error 0 |
| Talker prefill logits | cosine 1.000000, max error 5.63e-5 |
| Predictor logits, steps 0–14 | cosine 1.000000 at every step, max error 2.67e-5 |
| First predictor frame codes | 16/16 exact |
| Philox subsequences | identical (1..15 for frame 0) |

This is the decisive model-level result: with the same prompt, conditioning
tensors, F32 weights, and explicit random schedule, qwentts.cpp and Python
select the same predictor tokens.

## Interpretation

The run does not justify changing production sampling or EOS behavior. It
does establish three useful facts:

1. F32 qwentts Talker and predictor logits match Python under frozen
   same-conditioning replay.
2. The first mismatch in the independent-encoder run was a near-tie caused by
   small conditioning or numerical differences, not a Philox sequence
   mismatch.
3. The native model implementation and sampler are not the cause of the
   earlier runaway hypothesis.

Remaining investigations should focus on independently computed reference
encoder parity and multi-seed AR trajectory statistics. Production
sampling/EOS parameters must remain unchanged until those experiments provide
separate evidence.
