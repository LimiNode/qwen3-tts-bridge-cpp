# Seeded early-EOS reproduction on CMP 50HX, 2026-11-20

Status: **reproducible failure; R1 remains NO-GO**. This follow-up replaces the
earlier lack of a reproducible seed, not the historical WAV or its unknown
seed. No production algorithm, default, model, binary or package was changed.

Source: `aa2770ec8aeb45d59f42c96c3a1f4f2dc52390d8`; qwentts
`130cb99af9ae12d554962fd0920e08fb4268af01`, ABI6. Hardware:
CMP50HX, UUID `GPU-40361931-6cb5-ac58-a059-5ba3e70986fb`, driver 581.94.
Exact models/runtime/voice/input and artifact hashes are in the
[canonical diagnostic receipt](native-r1-seeded-early-eos-cmp50hx-20261120.json).

## Reproduction

The input remains the complete 126-byte UTF-8 utterance, 22 BPE body tokens:

> МГУ находится в Москве. Инженер проверил USB-порт, GPS и новый процессор.

A prespecified seed 0..127 search in 32-row batches stopped after the first
batch found five short-EOS candidates. Discovery used max 256 tokens, no
warmup, the existing nonshipping benchmark and exact packaged worker/runtime.

| Seed | Codec frames | Audio duration |
| --- | ---: | ---: |
| 2 | 3 | 0.24 s |
| 4 | 5 | 0.40 s |
| 14 | 3 | 0.24 s |
| 21 | 10 | 0.80 s |
| 31 | 4 | 0.32 s |

These selected diagnostic seeds are not an estimate of production failure rate.
Seeds 2 and 14 were then repeated twice with the original max 2048 tokens.
All four results remained 3 frames. A separate fresh worker with guard ON
also produced 3 frames for each seed. The seed 2 Talker, uniforms and all
three 16-codebook predictor frames match across discovery, repeated default
replay, fresh full-dump replay and guard-on replay.

## The existing EOS guard is not causing this failure

The historical package route does not enable `--eos-guard`; the worker default
is OFF and the historical log has no guard-enabled banner. This guard limits
overlong generation; it does not impose a minimum meaningful utterance.
For this 22-token clone prompt, enabled guard logs:

```text
expected=132 soft=79 max=158 force=198 boost=25.00
```

Before step 79 it contributes no EOS bias. Guard OFF/ON both produce the same
early seed 2 trajectory. Separate initial-EOS suppression masks only steps 0/1;
from step 2 EOS is intentionally eligible. No guard threshold was changed.

## Why the sampled seed matters

Seed 2 produces Talker codes `[462,462,619,2150]`; 2150 is EOS.
At step 3, before sampler policy, EOS is already the highest model logit:
15.804861 versus 13.470518 for the runner-up. Among codec-permitted tokens at
temperature 1 its probability is 82.4654%; after the existing
repetition/temperature/top-k chain it is 90.5919%.

The actual uniform is 0.3281003833. EOS occupies the normalized CDF interval
[0.0940813422,1], so this is not a boundary rounding accident or an implausible
categorical selection. Raw logits are finite; weights are finite/nonnegative;
the saved F32 sum 1.1038519144, target 0.3621742427 and every CDF entry replay
exactly to the selected EOS. No NaN/fallback/accumulator fault was observed.

In contrast, normal seed 1 follows `[1225,1707,1191,320,...]`. Its step 3 EOS
raw rank is 126, permitted-vocab temperature 1 probability 0.00009310585; top-k
excludes EOS. Prompt IDs, input embedding, trailing hidden, speaker embedding,
reference codes, prefill final hidden and prefill logits are byte-identical
between the two seeds. The initial RNG choice, not text or reference loss,
starts their divergence.

Two controlled three-frame substitutions test the causal link:

| Diagnostic intervention | Step 3 raw logits | Result |
| --- | --- | --- |
| Seed 0 given seed 2's first 3 complete audio-code frames | Byte-identical to bad seed 2 | EOS at 3, 90.5919% |
| Seed 2 given normal seed 1's first 3 complete audio-code frames | Byte-identical to normal seed 1 | EOS excluded by top-k; continuation |

These use the engine's existing forced-frame diagnostic hook, not normal
generation or a fix. Both controls cap generation at 6 frames; the continuing
control intentionally reports max_tokens and is not a natural-EOS or quality
PASS. Full dumps can alter graph retention, so transparency was checked
against the matching trace-only seed 2 trajectory rather than assumed.

Thus a seed-dependent early audio history steers this native model forward
into an EOS-dominant state. The sampler faithfully follows it; the existing
upper-tail guard is unrelated and does not protect against this failure.
This establishes the autoregressive failure mechanism. It does not yet
separate model/conditioning calibration from native-forward numerical parity:
no upstream same-history comparison was run. The old random seed is still
unknown, so seed 2 is a reproduced class of failure, not an identification of
that historical seed.

## Evidence and scope

Payload directory:
`.tmp/base-acceptance/native-r1-aa2770ec-20261120/diagnosis/short-eos-seed-sweep-001/`.

`plan.json`, per-run UTF-8 request manifests/invocations/results, complete
stderr traces, full short-run tensor/sampler dumps and `analysis.json` remain
local. The hashed `artifact-manifest.json` lists 1071 files; all sizes and
SHA-256s were independently verified. The local final driver includes the
optional prefix-intervention support added after discovery; invocation files
record which controls actually ran.

The model-free analysis independently checks tensor identities, finite values,
F32 selection replay and the controlled-prefix raw logits. There is no
human-listening/ASR verdict or full-speech success claim. The six-frame controls
and mechanically successful early natural EOS must not be promoted into
release acceptance. Originals and historical reports are preserved.

The next corrective decision is about preventing or rejecting premature
content termination, with scoped quality/continuation tests, or investigating
same-history upstream/native forward parity. This diagnosis does not silently
extend EOS masking, force a duration, enable retries or change sampling defaults.
