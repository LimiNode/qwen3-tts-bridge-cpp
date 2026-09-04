# CMP 50HX registered-voice prefix reuse probe

Date: 2026-09-03  
Profile: registered 1.7B Base voice `kraftwerk_robot_ru_bootstrap_fidelity`,
eager prefill, E8, W48 right-padded codec decode, reference-context bootstrap.

This probe hashes each position of `talker_input_embeds` in profile-only mode.
It does not reuse KV state and does not change inference.

## Result

Five different texts were sent through fresh workers with the same registered
voice profile. Every request produced `talker_prefill_length=237` and exactly
237 position hashes. The longest identical prefix across all five requests was
86 positions; position 86 was the first text-dependent position.

| Text shape | Text tokens | Prefill length | First PCM |
| --- | ---: | ---: | ---: |
| short Russian | 14 | 237 | 1022.0 ms |
| medium Russian | 26 | 237 | 1020.4 ms |
| long mixed/punctuated Russian | 55 | 237 | 1029.5 ms |
| mixed Russian/English | 25 | 237 | 1027.9 ms |
| punctuation-heavy Russian | 37 | 237 | 1029.7 ms |

The common prefix is therefore about 36% of the current talker prefill
sequence. This is large enough to justify a per-voice KV-cache prototype, but
embedding equality alone is not a correctness proof: suffix attention masks,
RoPE positions, cache layout, `past_hidden`, and generation state must all be
validated against a full eager prefill.

## Recommended next step

Implement a diagnostic-only split-forward check for one voice:

1. run the current full prefill and retain logits/hidden state/KV;
2. run positions `0:86` once, then positions `86:237` with the prefix
   `past_key_values`;
3. compare suffix hidden states, first codec logits, KV contents, and the full
   generated codec-token hash;
4. only after exact parity passes, measure whether retaining the first 86
   positions across requests reduces first PCM.

Do not expose the cache through the release configuration until the split path
passes natural EOS, cancellation/reset, PCM parity, and persistent-worker
reuse gates. The current production profile remains unchanged.

## Diagnostic implementation

The split-forward check is now available behind the environment variable
`QTB_FASTER_PREFIX_SPLIT_PROBE=1` (optional
`QTB_FASTER_PREFIX_SPLIT_PROBE_LENGTH`, default `86`). It runs after the normal
full prefill on a fresh dynamic cache, forwards the prefix and suffix through
`talker.model`, and compares suffix hidden states, codec logits, and every
available key/value tensor with the untouched full-prefill result. The split
result is never used for generation.

The first-chunk timing object reports whether the probe was attempted and
supported, its prefix length, max/mean hidden-state delta, max logits and KV
deltas, all-close flags, first-token argmax agreement, and any exception text.
Unsafe profiles (padding, sliding-window attention, unsupported cache layout)
are reported as skipped or failed rather than changing synthesis behavior.

This remains an experiment. A successful numerical probe is only a prerequisite
for a real cache-reuse prototype; generated codec-token hash, PCM, EOS,
cancellation/reset, and persistent-worker tests are still required before any
production enablement.

## CMP 50HX result (2026-09-03)

The probe was run against the sealed CUDA runtime (`torch 2.10.0+cu128`) with
the cached 1.7B Base model and the registered
`kraftwerk_robot_ru_bootstrap_fidelity` profile. The request used the accepted
E8/W48/reference-context configuration. The split path completed without
affecting synthesis, but it did not pass the cache-equivalence gate:

| Measurement | Result |
| --- | ---: |
| probe attempted / supported | yes / yes |
| prefix length | 86 / 237 positions |
| hidden max / mean absolute delta | 0.078125 / 0.003541 |
| codec-logit max absolute delta | 0.0625 |
| codec logits all-close (diagnostic tolerance) | yes |
| first-token argmax agreement | yes |
| KV max absolute delta | 0.640625 |
| KV tensors all-close | **no** |

The first PCM callback in this run was 9.64 s because graph capture was done in
the request; that number is not a steady-state latency measurement. The
important result is that matching input embeddings and even close suffix logits
do not imply reusable KV tensors. The current split implementation therefore
remains diagnostic-only and no per-voice KV reuse should be enabled.

Raw hash-bearing runs are under `tmp/` and are intentionally unversioned.

## Corrected isolation and reuse result (2026-09-04)

The initial split probe was extended to separate three effects: prefix-only
prefill versus the matching positions in full prefill, suffix execution using
the prefix-only KV, and suffix execution seeded with exact KV copied from full
prefill. This supersedes the earlier interpretation that the mismatch could be
explained only by attention-mask construction.

| Measurement | Result |
| --- | ---: |
| prefix hidden max absolute delta | 0.20703125 |
| prefix KV max absolute delta / all-close | 0.765625 / no |
| exact-KV-seeded suffix hidden max delta | 0.09375 |
| exact-KV-seeded suffix logits max delta / all-close | 0.0390625 / yes |
| exact-KV-seeded first token | match |
| exact-KV-seeded final KV max delta / all-close | 0.25 / no |

A temporary production-shaped reuse prototype showed that the opportunity is
large: first PCM improved from `614.279` to `527.394 ms`, while prefill GPU time
fell from `357.890` to `276.107 ms`. It nevertheless failed the required audio
parity gate. Control and reuse output lengths were respectively `7280` and
`7200 ms`; the first PCM difference appeared at `400 ms`, common-prefix SNR was
`-2.365 dB`, and maximum sample delta was `14966`.

The reuse path was therefore removed. The expanded diagnostic probe remains so
future kernel/runtime changes can retest the numerical boundary, but registered
voice prefix KV reuse is rejected for production in the current FP16 runtime.
