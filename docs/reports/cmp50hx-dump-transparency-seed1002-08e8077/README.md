# CMP 50HX opt-in dump transparency confirmation

This follow-up verifies the production-safe trace switch from qwentts.cpp
`08e80772e19b727dee0c756f3c1d1dcad7fb83e4`, pinned by Bridge merge
`54bf5348fd6bfe6aa2cb59e0cab078a4816bda78`.

The diagnostics-OFF invocation enabled only `QWEN_TTS_FULL_AR_TRACE=1`; it did
not pass `--dump`, so no diagnostic graph outputs or host tensor readbacks were
enabled. The diagnostics-ON invocation used the existing `--dump` path.

Both runs produced the same three Talker tokens (`1445, 1332, 845`), the same
three 16-code predictor vectors (48/48 exact), and byte-identical WAV output:

```text
C984763E6CFDB19345A2B58427689E755A8265166DF8B189DA269EB7294BAE9D
```

Without the environment switch and without `--dump`, ordinary runs retain the
previous compact `subsequence < 32` trace, avoiding full-trace formatting
overhead in the production path.

Machine-readable provenance is in [`evidence.json`](evidence.json). The exact
process output is in [`native-off.raw.log`](native-off.raw.log) and
[`native-on.raw.log`](native-on.raw.log).
