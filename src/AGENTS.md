# `src/` ? C++ library source

The public bridge is split by protocol, transport, session, client, audio, and
native adapter responsibilities. Read the root [`AGENTS.md`](../AGENTS.md) for
the public API and threading contracts, then read
[`qwen_tts_bridge/AGENTS.md`](qwen_tts_bridge/AGENTS.md) for source-level rules.

Keep headers and implementations under `src/qwen_tts_bridge/`; do not create
new root-level catch-all headers. Preserve dependency direction:

```text
client -> session -> transport + protocol
audio  -> client callbacks
native -> optional qwentts.cpp adapter
```

Protocol code must not know about processes, Python, CUDA, or playback.
Transport code must remain byte-oriented and must not invoke user callbacks.
Use explicit C++17 types and RAII. Add Doxygen to exported APIs.

## Anti-slop checks

- extend an existing domain type instead of creating a second equivalent DTO;
- keep parsing, lifecycle, and policy decisions in their owning subdomain;
- remove impossible branches and ensure no exception can escape a `noexcept`
  function;
- split a large implementation only at a real responsibility boundary;
- run the affected CTest target and inspect warnings before opening a PR.
