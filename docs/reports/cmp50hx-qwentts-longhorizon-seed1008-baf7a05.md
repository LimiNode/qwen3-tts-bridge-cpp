# CMP 50HX long-horizon AR/KV probe — seed 1008, qwentts.cpp `baf7a05`

This is a bounded follow-up to the frame-2 sampler evidence. It repeats the
same F32 frozen-conditioning stochastic run for sixteen frames with the
canonical qwentts.cpp #22 diagnostic build and captures the actual Python
`torch.multinomial` input at the first long-horizon mismatch.

## Result

The native run generated 16 frames. The Python reference remained exact through
semantic frames 0–6 and reported the first mismatch at frame 7:

```text
Philox subsequence = 112
u                  = 0.4909121990
native Talker      = 864
Python Talker      = 980
```

The Python side materialized 15 frames before aborting on the intentional parity
assertion. This is a diagnostic stop, not an EOS measurement.

## Actual sampler inputs at the mismatch

Both sides were instrumented without changing production sampling:

```text
native candidate count = 50
native representation  = unnormalized post-filter exponentials
native weight sum       = 2.1130456924
native selected         = 864 (weight 0.0984548479)
native top token        = 980 (weight 0.8092966080)

Python candidate count  = 50
Python representation   = normalized probabilities passed to torch.multinomial
Python probability sum  = 1.0
Python selected         = 980 (probability 0.9043745995)
Python probability[864] = 0.0012493390
```

The actual candidate lists are preserved by the Python diagnostic hook and the
native bounded sampler dump. They are not equal at this frame, and the token
weights differ by orders of magnitude. Therefore this frame is not a clean
same-conditioning sampler/CDF comparison like the earlier frame-2 predictor
gate. It is already downstream of accumulated Talker state or numerical drift.

The sums above are different representations of the same distribution and are
not evidence by themselves: native retains unnormalized exponentials while
Python receives normalized probabilities. The useful comparison is candidate
membership and normalized relative weights. Those already differ materially at
this frame. The native and Python uniform is the same deterministic Philox draw,
and the different selections are lawful for their different probability inputs.

## Interpretation and next gate

This run strengthens the existing classification:

```text
first frame-7 Talker mismatch
→ different Talker sampler inputs
→ accumulated Talker AR/KV or numerical-state drift
```

It does not prove a new sampler implementation defect, softmax/CDF mismatch, or
EOS problem. Do not tune temperature, EOS penalties, or production sampling
from this run. The next useful experiment is a forced same-history replay that
compares Talker logits/state before subsequence 112, followed by a separate
long-horizon EOS/termination gate.

## Provenance

The machine-readable [JSON evidence](cmp50hx-qwentts-longhorizon-seed1008-baf7a05.json)
records the Bridge base, qwentts commit, binary and harness hashes, model and
reference-latent hashes, GPU, CUDA/PyTorch versions, and raw-log hash.
