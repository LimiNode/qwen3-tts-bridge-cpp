# CMP 50HX canonical native multiseed sampler rerun

After the dump-off/dump-on transparency gate, the fresh `qwentts.cpp 2e696e2`
binary was run natively for seeds `1000`, `1002`, `1006`, and `1008`. All runs
used the same F32 Base models, direct latent ICL inputs, stochastic parameters,
and `max_new_tokens=3`. Each run completed successfully and captured the actual
native sampler intermediates at frame 2 / predictor step 9 / logical codebook
10.

| seed | Philox `u` | native selected | candidate-set hash | k-th / k+1 logit |
| ---: | ---: | ---: | --- | ---: |
| 1000 | 0.5755396485 | 902 | `a02daf5b8057512d` | 23.04718971 / 23.01638412 |
| 1002 | 0.7919672728 | 1399 | `d3312a4c5af7dc74` | 23.92102623 / 23.90633202 |
| 1006 | 0.6810894608 | 1180 | `adbb0dbad1d48e54` | 23.44990921 / 23.44897461 |
| 1008 | 0.4923694134 | 832 | `a4d2a4fd04b1483f` | 23.18097878 / 23.16956902 |

This is a native-only canonical rerun. It confirms that the current binary
reaches the diagnostic gate and records the expected native intermediates; it
does not by itself prove Python parity or long-horizon/EOS acceptance. Those
interpretations remain in the earlier machine-readable Python/native sampler
evidence, which this report deliberately does not rewrite.

See [`evidence.json`](evidence.json) for provenance and per-seed SHA-256
fingerprints. Each seed directory contains the raw native log and the sampler
summary captured by the binary.
