# CMP 50HX same-history Talker frame diagnostic

This run uses qwentts.cpp `b8b63ebb678a50e877fbca1a2376fc7e24aa2e51` and the
F32 Base Talker/codec models. It is a bounded diagnostic run, not a production
sampling or EOS change.

## Result

Native and Python follow the same sampled Talker history through step 6. The
first observed state divergence is at Talker frame 7, before token selection:

```text
Philox subsequence 112: u = 0.49091219902038574
native Talker argmax:    662
Python Talker argmax:    980
native selected token:   864
Python selected token:   980
```

Frames 1--6 remain near-identical (`hidden cosine >= 0.999999762`,
`logits cosine >= 0.999999881`). At frame 7 the hidden-state cosine falls to
`0.658544242`, and raw-logit cosine is `0.904991567`. Therefore this run does
not support an isolated CDF-selection explanation: the sampler inputs have
already diverged.

The native diagnostic stores unnormalized post-filter exponentials, while the
Python hook stores the normalized probability tensor passed to
`torch.multinomial`; their sums are not directly comparable. The Python and
native candidate sets overlap in 26 of 50 entries at frame 7, so the top-k
membership is also already different. This is evidence for a long-horizon
Talker state or numerical drift, not proof of CDF parity.

## Next gate

The next experiment is a forced same-history replay at frame 7. It must compare,
in order: Talker input/next embedding, KV/state boundary, hidden state, raw
logits, post-processing logits, top-k membership, normalized probabilities, CDF,
the shared Philox uniform, and the selected token. Production sampling, EOS,
KV, and AR behavior remain unchanged until that gate is complete.

Machine-readable provenance and all captured raw output are in
[`evidence.json`](evidence.json) and
[`native/seed1008-max16-b8b63eb.raw.log`](native/seed1008-max16-b8b63eb.raw.log).
