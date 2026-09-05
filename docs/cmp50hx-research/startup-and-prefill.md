# Startup and prefill research

## Findings

The investigation separated four values that were initially conflated:

1. worker/model load time;
2. Talker/reference prefill;
3. time to enough codec frames for the first decode;
4. playback prebuffer delay.

Selected-profile warmup moved graph capture out of the first user request and
was retained. Increasing the emission chunk reduced the number of queue-empty
observations but delayed first PCM and did not make a sub-real-time producer
realtime.

Compiled prefill was not a useful production path. Experiments either changed
the autoregressive/PCM trajectory, failed capture compatibility, or spent more
time compiling/warming than they recovered. Reducing static Talker
`max_seq_len` was repeatable: it reduced graph work and later became the
capacity dimension of the production profiles.

Reference-context bootstrap removed repeated Base reference-code decoding. The
later per-registered-voice prefix-KV experiment reused an 86-position prefix
and reduced cached fastest first PCM to about 521-543 ms. It changed the
autoregressive trajectory; listening retained phrase and voice identity, so it
was promoted only as an explicit perceptual-risk profile.

## Final profile outcomes

| Profile | Schedule / codec | `max_seq_len` | Accepted first PCM |
| --- | --- | ---: | ---: |
| `cmp50hx-fastest` | E3 then E4 / W29, prefix-KV | 448 | median 523.829 ms in final router soak |
| `cmp50hx-ultra-low-latency` | E3 then E4 / W29 | 448 | persistent median 610.901 ms |
| `cmp50hx-low-latency` | E4 / W33 | 768 | about 675-683 ms in bounded runs |
| `cmp50hx-safe` | E8 / W33 | 2048 | final median 963.912 ms |

Capacity is not audio-only: text/reference prefill and generated Talker tokens
share the same sequence. A W768 boundary request produced 42.48 seconds of PCM
and correctly ended with `sequence_capacity_exceeded`; W2048 reached natural
EOS after 128.96 seconds. The router must choose safe or segment known-long
text before submission rather than retry after already playing truncated PCM.

Detailed decomposition and rejected compiler probes:

- [Base first-PCM research](../cmp50hx-base-first-pcm-research.md)
- [Base startup profile](../cmp50hx-base-profile-startup.md)
- [AR breakdown](../cmp50hx-ar-breakdown-research.md)
- [Prefix reuse probe](../cmp50hx-prefix-reuse-research.md)
- [Latency batch](../cmp50hx-latency-batch-research.md)
