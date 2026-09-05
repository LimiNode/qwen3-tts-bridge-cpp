# Native profile porting contract

The Python/FasterQwen and native qwentts backends expose one product-level
profile vocabulary. A profile is a policy, not a promise that both engines use
the same kernels. Each backend must publish the effective values and pass the
same acceptance gates before a profile is enabled by default.

## Profile vocabulary

| Profile | Intended use | Quality policy | Sequence policy |
| --- | --- | --- | --- |
| `safe` | long or unknown assistant replies | reference trajectory preferred | full model window |
| `low-latency` | normal real-time replies | parity-preserving | bounded window |
| `ultra-low-latency` | short avatar utterances | parity-preserving, tighter capacity | short bounded window |
| `fastest` | opt-in speed-first mode | trajectory may differ; audible sanity gate required | shortest bounded window |
| `continuous` | uninterrupted playback | extra prebuffer permitted | full/large window |

The current Python acceptance values remain the reference contract:

```text
cmp50hx-low-latency       E8 + W33 + prebuffer=1
cmp50hx-ultra-low-latency E3/E4 + W29 + bounded sequence
cmp50hx-safe              E8 + W33 + max_seq_len=2048
cmp50hx-fastest           prefix-KV reuse + W448 (experimental)
```

RTX 4090 values are a separate hardware preset. Do not copy CMP constants to
RTX 4090 or vice versa; route by adapter capabilities and measured gates.

## Native mapping

The qwentts ABI now exposes `stream_max_chunk_frames` (1, 2, 4, or 8). This is
the native counterpart of the steady streaming emission cadence. The bridge
passes it through `--stream-max-chunk-frames` and keeps the default at 8 until
hardware measurements prove a smaller cadence is stable.

The following fields still require native implementation before the matching
profile can be marked release-ready:

- codec history/window policy equivalent to W29/W33/W448;
- explicit playback prebuffer and physical WaveOut starvation gate;
- prefix-KV reuse with a documented quality policy;
- graph/kernel variants corresponding to FasterQwen CUDA Graph and MLP work;
- profile-aware sequence limits and automatic text-length routing;
- RTX 4090 and CMP 50HX hardware presets with independent measurements.

An unsupported field must be reported as unsupported by the native capability
manifest; silently ignoring it is not allowed. Until a native profile passes
the common matrix, Python/FasterQwen remains the default release backend.
