# CMP 50HX latency batch research

Date: 2026-09-04  
Target: idle CMP 50HX 20 GiB, Qwen3-TTS 1.7B Base, registered Kraftwerk
voice, one-chunk playback prebuffer.

This batch tested the remaining bounded-graph and scheduling candidates for a
faster first PCM while preserving sustained real-time delivery. The accepted
production candidate is:

```text
cmp50hx-ultra-low-latency
max_seq_len=448
emit_chunk_schedule=3,4
emit_every_frames=4
right-padded codec W29 with CUDA graph
prebuffer=1
```

It does not replace `cmp50hx-low-latency` or `cmp50hx-safe`. The smaller graph
has a lower utterance capacity and must be selected only for bounded text.

## Accepted W448 result

Three fresh-worker runs produced first PCM at `606.687`, `608.346`, and
`606.002 ms`. Median later-chunk cadence was `285.102`, `284.566`, and
`282.924 ms`; the worst cadence was `288.301 ms`. All runs reached natural EOS
with zero starvation observations.

A 30-request persistent RU/EN soak completed 30/30 requests without restarting
the worker:

| First PCM statistic | Result |
| --- | ---: |
| minimum | 602.275 ms |
| median | 610.901 ms |
| p95 | 614.177 ms |
| maximum | 617.460 ms |

A 39-token English request produced `12.88 s` of PCM, reached natural EOS, and
had `613.166 ms` first PCM with zero starvation. Cancellation after the first
PCM also passed: the cancelled request emitted one 240 ms chunk and reached the
`cancelled` terminal state; the next request completed with `599.405 ms` first
PCM.

Raw local evidence is under:

```text
tmp/research-20260904/e3-e4-w29-seq448-soak3/
tmp/research-20260904/ultra-w448-persistent-30.json
tmp/research-20260904/capacity-en-w448-e3-e4-w29/
```

## Candidate comparison

### Static Talker capacity

E4/W33 was stable in three W384 runs at about `666-669 ms` first PCM. W448
measured `711-736 ms`. Single W512, W640, and W768 probes observed respectively
21, 14, and 8 late-chunk starvation events; those isolated results were
sensitive to runtime/GPU state and are not used as an acceptance ranking.

W384 with E3 then E4 and W29 is the absolute measured latency minimum:

* fresh first PCM about `601-604 ms`;
* WaveOut start about `669-675 ms`;
* steady cadence about `279-281 ms`;
* zero starvation in the accepted runs.

Its capacity is too narrow for the default ultra profile. The same 39-token
English request reached 147 frames / `11.76 s` and correctly failed with
`resource_error / sequence_capacity_exceeded`. In a 30-request persistent soak
W384 had `606.385 ms` median and `611.629 ms` p95 first PCM, but a rare
`664.905 ms` maximum. W448 costs only about 4-5 ms at the median while providing
materially more capacity and a tighter distribution, so W384 remains
research-only.

### W29 codec window

Reducing W33 to W29 at W384 changed first PCM from `724.057` to `692.615 ms`.
The codec-token hash remained identical:

```text
176fa3f522f79dffd4e6d08a17e076533912f084f875ee850f157c6f5f6d7b0d
```

PCM differed only at the already accepted floating-point boundary: SNR was
`52.509 dB`, maximum sample delta `100`, and RMS delta `4.512`. An automated
boundary check over 22 E3-to-E4/W29 joins found no splice signature: maximum
boundary delta `852`, global adjacent-sample maximum `5306`, and zero
boundaries above the global p99.9 delta (`2441.282`). A final human W29
listening check remains required before release.

### Asynchronous codec

The async codec implementation was stabilized with a persistent CUDA stream,
explicit stream synchronization, and bounded producer shutdown. Sync and async
PCM were byte-identical with SHA-256
`ca608d3261b6466535f6f2ffed083c9e280b68196375c07f7a58dab9dea4d08e`.
Five fresh-worker soaks completed at `600.154-608.744 ms` first PCM with zero
starvation and no replay/shutdown assertion. It did not improve CMP latency, so
it remains diagnostic-only and is not enabled by the ultra profile.

### Registered-voice prefix KV reuse

The common registered-voice prefix is 86 positions, but isolated prefix
prefill is not numerically equivalent to the same prefix inside full prefill.
The corrected probe measured prefix hidden max delta `0.20703125` and prefix KV
max delta `0.765625` (not all-close). Even seeding the suffix with exact KV
copied from full prefill left a `0.09375` hidden delta and `0.25` final KV delta,
although logits were all-close and the first token matched.

A diagnostic reuse prototype reduced first PCM from `614.279` to `527.394 ms`
and prefill GPU time from `357.890` to `276.107 ms`, but failed the audio gate:
the control produced `7280 ms` and reuse `7200 ms` PCM, the first difference
appeared at `400 ms`, common-prefix SNR was `-2.365 dB`, and maximum sample
delta was `14966`. The production reuse path was removed. Only the parity
diagnostic remains.

## Decision

Promote W448/E3-to-E4/W29 as the opt-in ultra profile. Keep W768/E4/W33 as the
established low-latency profile and W2048/E8/W33 as the safe profile. Do not
enable async codec or voice-prefix KV reuse in production. Route or split text
before submission; never retry an already partially played capacity failure as
though no audio had been emitted.
