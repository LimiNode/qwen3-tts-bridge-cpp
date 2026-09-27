# CMP 50HX CUDA-graphs paired probe (2026-09-27)

This is a bounded A/B experiment. The only runtime variable is
`GGML_CUDA_GRAPHS`; the Bridge worker, qwentts source, GGML source, CUDA
toolchain, Q8 models, registered voice, text, seed, warmup policy, and stream
chunk size are shared.

## Provenance

- Bridge: `202e64c82725198a36a165aac0772109d458ca7c`
- qwentts.cpp: `130cb99af9ae12d554962fd0920e08fb4268af01`
- GGML submodule: `c044c6f0` (recorded by the qwentts checkout)
- CUDA: 13.3.73; MSVC: 14.44.35207
- GPU: NVIDIA CMP 50HX, driver 581.94, 20480 MiB (`sm_75` build)
- Models: Q8 talker and Q8 tokenizer; SHA-256 values are in the companion JSON
- Voice: registered `kraftwerk_robot_ru_bootstrap_fidelity`
- Text: `Сегодня хороший день, и мы начинаем проверку голоса.`
- Language: `russian`; seed: `1002`; `--stream-max-chunk-frames 1`
- EOS guard: disabled
- Both workers report `ready.warmed_up=true`.

The ON runtime emitted `ggml_backend_cuda_graph_compute: CUDA graph warmup
complete`. The OFF runtime emitted no CUDA-graph warmup marker. CMake caches
record `GGML_CUDA_GRAPHS=ON` and `OFF`, respectively, with
`GGML_CUDA=ON`, `QWEN_SHARED=ON`, and `CMAKE_CUDA_ARCHITECTURES=75-real`.

## Normal synthesis

| metric | graphs OFF | graphs ON |
| --- | ---: | ---: |
| first PCM | 228.468 ms | 189.629 ms |
| qwen total | 1677.04 ms | 616.391 ms |
| qwen prefill | 153.133 ms | 161.934 ms |
| qwen TTFA | 212.946 ms | 180.769 ms |
| talker | 270.170 ms | 103.678 ms |
| code predictor | 973.750 ms | 195.260 ms |
| codec | 272.543 ms | 147.045 ms |
| audio | 18 frames / 1.44 s | 18 frames / 1.44 s |
| median inter-chunk gap | 83.924 ms | 24.744 ms |
| max inter-chunk gap | 90.551 ms | 25.654 ms |
| starvation detected | yes | no |
| terminal outcome | `natural_eos` | `natural_eos` |

The captured WAV is byte-identical in both modes:

`5F83E313183B6C92BA42913FD02F3DC7F6974F0C78C31EBB882778BE5842A2E3`

This establishes the result only for this request. It does not yet establish
long-run latency percentiles or general semantic equivalence.

## Persistent cancellation/recovery

Each mode used one persistent worker: warmup, a long request cancelled after
the first PCM chunk, then a second request without restarting the worker.

| metric | graphs OFF | graphs ON |
| --- | ---: | ---: |
| `ready.warmed_up` | true | true |
| cancel first PCM | 234.433 ms | 184.457 ms |
| chunks before cancel | 1 | 1 |
| recovery | `natural_eos` | `natural_eos` |
| recovery time | 1967.530 ms | 1302.173 ms |
| recovery chunks | 10 | 10 |
| recovery PCM | 38400 bytes | 38400 bytes |
| worker exit | 0 | 0 |

Both modes therefore preserve cancellation and subsequent request handling in
this smoke. The result supports enabling CUDA graphs for the next canary, but
the next gate remains a 30-request warmed series followed by a 100-request
baseline, with longer RU/EN texts and VRAM/RTF capture.

