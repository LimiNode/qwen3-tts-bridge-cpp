# CMP 50HX Base first-PCM research

Date: 2026-09-02  
Scope: registered 1.7B Base voice, persistent worker, E8 emission, W48
right-padded decoder with manual CUDA Graph, prebuffer 1, and reference-context
bootstrap.

This is a diagnostic study. It does not change the accepted release profile
(W48 remains the production baseline).

## Baseline decomposition

Three fresh-worker idle runs used different Russian text lengths (19, 24, and
47 tokenizer tokens). The measured `talker_prefill_length` stayed `237` in all
requests.

| Text tokens | First PCM | Talker/prefill GPU | AR decode | Codec residual | Starvation proxy |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 19 | 1018.3 ms | 344.0 ms / 353.7 ms | 509.6 ms | 150.6 ms | 0 |
| 24 | 1013.1 ms | 344.9 ms / 353.7 ms | 506.7 ms | 148.4 ms | 0 |
| 47 | 1034.4 ms | 349.6 ms / 359.0 ms | 517.8 ms | 152.8 ms | 0 |

The first PCM budget is therefore dominated by Base talker prefill (~354 ms),
autoregressive bootstrap (about 510 ms), and the first codec decode (~150 ms).
Tokenization and local input construction are only single-digit milliseconds.

## Compiled prefill experiment

`compile_reduce_overhead` was tested in a separate runtime cache. The existing
FP16 profile cannot use `strict_bf16_sdpa_v1` (the worker correctly rejects that
combination), so the comparison used the supported FP16 compile path.

The compiler spent approximately 148 seconds during warmup. The request then
hit the compiled callable cache, but the compiled prefill still took 404.9 ms
(talker forward 395.5 ms), versus 353–359 ms eager. First PCM was 1064.9 ms and
WaveOut started at 1131.0 ms. Audio completed with natural EOS and starvation
proxy 0, but this is a regression, not an optimization. Compiled prefill is
therefore not recommended for the current CMP FP16 profile.

## Right-padded decoder window experiment

The same fixed-seed request was captured with W48, W36, and W33. Generated codec
tokens were identical in all three runs (`64` frames, natural EOS, identical
codec-token SHA-256). All runs completed with starvation proxy 0.

| Window | First PCM | Codec residual | WaveOut | PCM comparison to W48 |
| ---: | ---: | ---: | ---: | --- |
| W48 | 1014.6 ms | 148.7 ms | 1080.3 ms | reference |
| W36 | 1013.1 ms | 145.7 ms | 1080.5 ms | SNR 52.9 dB, max delta 60 |
| W33 | 989.8 ms | 122.2 ms | 1056.4 ms | SNR 52.2 dB, max delta 86 |

W33 is the minimum causal shape for history 25 + E8. A three-attempt W33 soak
with another short request measured first PCM `988.0`, `988.7`, and `992.7 ms`,
with prefill `351.8–354.1 ms`, codec residual `121.1–123.0 ms`, and starvation
proxy `0` for every attempt. The W33 PCM is not byte-identical to W48, but the
codec-token stream and metadata are identical and the measured PCM difference
is small (about 52 dB SNR). Subjective listening and a longer mixed-text soak
are still required before making W33 an accepted release setting.

## Conclusions

1. The old fast-start problem is not caused by an unstable Base prompt shape;
   the registered profile consistently produces prefill length 237.
2. Compiling the current FP16 prefill does not help on CMP 50HX and adds a very
   large one-time warmup cost.
3. The only tested change that materially reduces first PCM is shrinking the
   right-padded codec window to W33 (about 25 ms in these runs), while retaining
   E8 cadence and starvation proxy 0.
4. Keep W48 as the release default until W33 passes audio review and a longer
   workload gate. If accepted, expose W33 as an explicit CMP low-latency
   profile, not as a silent global default.

Raw run directories and parity reports are under `tmp/` and intentionally are
not versioned.
