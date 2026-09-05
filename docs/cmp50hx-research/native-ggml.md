# Native GGML research

## What PR #59 proved

PR #59 implemented a default-off Python worker adapter that called a local
qwentts.cpp DLL for CustomVoice. It required an explicit language, rejected
unsupported Faster/upstream controls, kept DLLs and GGUF files local, and
completed a real CMP 50HX playback smoke. The focused Python suite reported 112
passing tests.

This proved that the qwentts.cpp C ABI can satisfy the Bridge engine contract.
It did not prove that Python is the right production host. Keeping Python
between QTB IPC and a native C ABI adds a layer without providing the model
runtime, so the implementation is retained as research evidence only.

## What PR #60 proved

The cross-backend harness normalized native and Faster summaries and required:

- identical text SHA-256, language, speaker, seed, workload label, attempt
  counts, and playback prebuffer;
- disabled ETW and PCM capture for timing runs;
- successful completion and physical playback for every native attempt;
- primary comparison of first audio, RTF, completion, and the WaveOut
  starvation proxy.

A matching contract smoke passed. A deliberately mismatched text digest and an
incomplete native playback attempt were rejected. This fail-closed comparison
contract should be restacked on the future native process worker.

## Architecture decision

The production native path will be a Bridge-owned persistent executable that
implements QTB and dynamically loads the generic qwentts.cpp `qwen.dll`. The
Bridge and worker do not build qwentts.cpp, link `qwen.lib`, or inherit its
CUDA/GGML toolchain. An in-process DLL session may be added later as an
explicit opt-in trade-off.

See [ADR: native engine boundaries](../architecture/adr-native-engine-boundaries.md).
