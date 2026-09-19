# CMP 50HX forced full-history replay — seed 1008, qwentts.cpp `54d9ece`

This is the follow-up to the seed-1008 long-horizon probe. The earlier
c0-only sidecar did not hold the Talker input history fixed: the next Talker
embedding is the sum of all 16 codebook embeddings, so predictor codebook drift
could still enter the next frame. This replay therefore forces complete 16-codebook
frames 0–6 in both implementations. The diagnostic-only sidecar does not alter
production sampling or Philox consumption.

## Result

The first free frame is frame 7 (`Philox subsequence 112`). The forced prefix is
exact for 112 code values. At frame 7:

```text
uniform                 0.4909121990
native/Python token     980 / 980
hidden cosine           0.9999997942
logits cosine           0.9999999415
hidden/logits argmax    equal / equal
candidate set           50 / 50, overlap 50
```

The native sampler keeps unnormalized post-filter exponentials while Python
passes normalized probabilities to `torch.multinomial`. After normalization,
the weight views have cosine `1.0`, maximum absolute difference
`1.6874e-4`, and mean absolute difference `1.1662e-7`. Both implementations
select token `980` with the same deterministic Philox draw.

The short run records eight Talker draws on each side. Python materializes
seven code frames in its generation return, while native materializes eight;
that count is intentionally not used as an EOS or termination verdict.

## Interpretation

This gate removes the isolated sampler/CDF explanation for the earlier frame-7
mismatch. Once the complete codebook history is equal, hidden state, logits,
candidate membership, normalized weights, and selected token agree within the
expected F32/backend accumulation tolerance. The earlier divergence was caused
by accumulated predictor/code history drift before the Talker sampler was
reached.

This is not a production acceptance result. Stochastic long-horizon behavior,
EOS/termination semantics, and CUDA/PyTorch end-to-end audio parity remain
separate gates. Do not tune temperature, EOS penalties, or production sampling
from this diagnostic run.

## Provenance

Machine-readable details, artifact hashes, and the committed raw log are in
[the JSON evidence](cmp50hx-forced-full-history-seed1008-54d9ece.json).

The native binary was built from qwentts.cpp diagnostic capture commit
`54d9ece` (base `89faded`) and reports that capture commit in its runtime
banner. The diagnostic commit was subsequently merged as qwentts commit
`bc938eda`; both commits have tree SHA
`b9b36d227758e805fb0febe87ac43434f7349879`, so the merge introduced no code
change relative to the captured tree. A later test-only merge
`53d3fd5c4d23033cb56eff59f5739724b5efe730` is the Bridge submodule pin.
Python ran on
CPU because the installed local PyTorch is `2.8.0+cpu`; native ran on the CMP
50HX through GGML CUDA.
