# Python worker package

Keep the package layered as `cli` → server/application lifecycle → engine and
protocol mappings. The engine interface must not know stdin/stdout framing or
JSON payload shapes. Keep the mock engine usable so protocol and lifecycle
tests do not require CUDA.

Use immutable typed DTOs where practical, validate configuration at startup,
and keep model-family behavior behind `engine/`. Runtime profiles are resolved
before model construction; never mutate a CUDA graph or static sequence limit
while a request is running.

When changing generation, warmup, prefix-KV, or profile routing, add a
deterministic test for the relevant telemetry/error contract and a hardware
acceptance note if latency or quality is claimed. Avoid adding another option
when an existing profile or request field expresses the same policy.
