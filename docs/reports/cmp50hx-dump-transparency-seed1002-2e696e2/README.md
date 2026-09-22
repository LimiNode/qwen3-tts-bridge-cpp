# CMP 50HX dump-off/dump-on transparency probe

This canonical seed-1002 smoke uses qwentts.cpp `2e696e2f359d722f8797995e447b19f34cdacfbf`, which adds only a bounded (128-frame) AR log. Bridge remains pinned to the runtime tree from qwentts.cpp `114f7732e832ec7df1a474d8160aedbeda5bca43`; the trace-only merge is identified separately because this binary was rebuilt after that merge. The same F32 models, `.spk/.rvq`, prompt, seed, sampling parameters, and `max_new_tokens=3` were used for diagnostics OFF and ON.

## Result

Both runs exited successfully and reported three generated frames. The full
bounded trace is now emitted in both modes, without enabling diagnostic graph
outputs in the OFF run:

```text
Talker c0: 1445, 1332, 845
Philox subsequences: 0, 16, 32
Predictor code vectors: 16/16 exact at frames 0, 1, and 2
Compared predictor values: 48/48 exact
```

The decoded WAV files are also byte-identical:

```text
off/on audio SHA-256 = C984763E6CFDB19345A2B58427689E755A8265166DF8B189DA269EB7294BAE9D
```

The only qwentts code change relative to the diagnostic runtime is bounded
logging. It does not retain graph outputs, read device tensors, consume extra
RNG, or change sampler/EOS/AR/KV control flow. The exact OFF and ON traces are
available in the committed raw logs.

## Evidence boundary

This closes the dump-off/dump-on transparency gate for the bounded seed-1002
trajectory. It does not claim stochastic Python/native parity, long-horizon
AR/KV acceptance, or EOS equivalence. Those remain separate research gates.

Machine-readable provenance and comparisons are in
[`evidence.json`](evidence.json); raw logs are
[`native-off.raw.log`](native-off.raw.log) and
[`native-on.raw.log`](native-on.raw.log).
