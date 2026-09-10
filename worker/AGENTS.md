# `worker/` ? Python and native workers

The Python worker owns Python/FasterQwen model loading, CUDA policy, warmup,
and model-specific streaming. The native worker owns qwentts runtime loading
and native model execution. The C++ bridge owns supervision, transport,
protocol, and callback dispatch. Keep those responsibilities separate; do not
make the IPC server depend on Qwen model classes or wire-level JSON details.

The worker must keep stdout binary/protocol-only and send logs to stderr or a
file. It must remain persistent across requests, produce exactly one terminal
event per queued/running request, and support cooperative cancellation without
blocking the input reader on inference.

Read [`src/qwen_tts_bridge_worker/AGENTS.md`](src/qwen_tts_bridge_worker/AGENTS.md)
for Python-specific boundaries and [`native/AGENTS.md`](native/AGENTS.md) for
the qwentts.cpp process worker.
