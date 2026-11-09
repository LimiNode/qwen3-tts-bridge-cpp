# CMP 50HX source upstream CustomVoice smoke — 187d450

> Historical diagnostic summary (August 2026). It records a bounded experiment and is not a current release gate. Raw machine artifacts are intentionally local-only and are not part of this curated documentation set.

Result: **PASS.** This is one diagnostic-only source-built upstream smoke, not an upstream-versus-FasterQwen performance comparison. No R4 package was built.

The source checkout was `187d450eb6a9c76e9334b3488468d7949fc34f9f` on `feature/docs-and-playback-cli`; its `external/python/Qwen3-TTS-streaming` gitlink was `6db590f3614a2243239f8047066d190ae9125852`. The client was source-built at `build/cmp50hx-diagnostic-mingw/qwen_tts_save_wav.exe`. Worker code was imported from `worker/src/qwen_tts_bridge_worker` and the source submodule. The physical R3 directory supplied only its read-only private Python/Torch dependencies.

Before and after the run, the R3 marker was present and both `package_tree_manifest.py verify` and `voice_assets_manifest.py verify` succeeded. The declared verified package digest remained `c2a5133e843d5660b2fd0ca3c2b633f54154195c6fc1c76e7d0994542211ecfc`; the manifest-document hashes were also identical before and after. No sealed R3 file was changed.

The request used the prior fixed medium CustomVoice manifest: `Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice` revision `85e237c12c027371202489a0ec509ded67b5e4b5`, speaker `ryan`, Russian, BF16, 24 kHz mono S16 PCM, and seed `20260806` fixed. Runtime was upstream with eager prefill and SDPA, `--no-compile` and `--no-cuda-graphs`; no schedule, frequency profile `8,8,12`, allowlist, canary, or `collect_generation_trace` option was enabled.

`CUDA_VISIBLE_DEVICES=GPU-40361931-6cb5-ac58-a059-5ba3e70986fb` constrained the worker to one visible device. Torch reported `cuda:0` as NVIDIA CMP 50HX (21,474,574,336 bytes, capability 7.5). Worker PID `31868` was repeatedly mapped by `nvidia-smi` to `GPU-40361931-6cb5-ac58-a059-5ba3e70986fb, NVIDIA CMP 50HX`; it was not mapped to the GTX 1060.

## Result

| Measure | Observed |
| --- | ---: |
| Client exit / terminal state | `0` / `completed` |
| Completion generation trace | received (`upstream_streaming_completion_v1`) |
| Termination | `eos`; `hit_eos=true` |
| Max limits | `hit_max_new_tokens=false`; `hit_max_seq_len=false` |
| PCM / codec | 25 chunks; 767,890 bytes; 200 codec frames |
| First PCM | 12,249.781 ms |
| Audio duration | 15,997.708 ms |
| Generation wall time | 182,804.029 ms |
| Standard RTF | 11.426889 |
| Inverse RTF | 0.087512885 |

All seven requested pass conditions are met. This passing smoke supports recommending an R4 package build from `187d450`, but this task did **not** build R4.

Raw client result, worker log, provenance, and machine-readable summary artifacts are retained locally and intentionally omitted from this curated documentation set.
