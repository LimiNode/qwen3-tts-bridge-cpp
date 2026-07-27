# RTX 4090 Faster-Qwen Profiling Commands

Run from:

```text
C:/_repoz/faster-qwen3-tts-v032-stack112-clean
```

2026-07-27 strict BF16 SDPA product opt-in:

```text
run from: C:\_repoz\qwen3-tts-bridge-cpp
bridge branch: development-flash-attn-experiment
faster-qwen3-tts branch: prefill-compile-exact-shape
faster-qwen3-tts product commit: 12527a7
model: models\Qwen3-TTS-12Hz-0.6B-CustomVoice
hardware: NVIDIA GeForce RTX 4090
python: .venv-packaging\Scripts\python.exe for worker benchmarks
diagnostic python: .venv-faster-qwen\Scripts\python.exe for direct gates
PYTHONPATH: worker\src;C:\_repoz\faster-qwen3-tts-v032-stack112-clean;external\python\Qwen3-TTS-streaming;tests\python
text: I am your robot, I am your worker.
language: English
speaker: ryan
seed: 4242
decode: --no-sample
```

2026-07-28 strict BF16 SDPA lifecycle hardening:

```text
run from: C:\_repoz\qwen3-tts-bridge-cpp
bridge branch: development-flash-attn-experiment
faster-qwen3-tts branch: prefill-compile-exact-shape
faster-qwen3-tts lifecycle commit: 95ea2ca
scope:
  - immutable loaded-model compat mode
  - atomic Talker module patching
  - bridge cross-field config validation
  - bridge loaded-model validation before ready
  - strict VoiceDesign temporarily blocked until real-model gate
```

Verification after lifecycle hardening:

```text
FasterQwen targeted:
  .venv-faster-qwen\Scripts\python.exe -m pytest tests\test_sampling.py tests\test_prefill_compat.py -q
  result: 50 passed, 1 warning

FasterQwen selected:
  .venv-faster-qwen\Scripts\python.exe -m pytest tests\test_ggml_backend.py tests\test_prefill_compat.py tests\test_sample_rate.py tests\test_sampling.py tests\test_voice_clone_prompt_api.py -q
  result: 107 passed, 1 warning

FasterQwen full:
  $env:PYTHONPATH='C:\_repoz\qwen3-tts-bridge-cpp\external\python\Qwen3-TTS-streaming'
  .venv-faster-qwen\Scripts\python.exe -m pytest -q
  result: 121 passed, 18 warnings, 287.12s

Bridge Python:
  scripts\check-python.ps1 -UseVenv -VenvPath .venv
  result: 158 tests OK, 2 skipped

Bridge C++:
  ctest --test-dir build\default --output-on-failure
  result: 9/9 passed
```

Real-model diagnostic-lazy smoke after lifecycle hardening:

```powershell
$env:PYTHONPATH='C:\_repoz\faster-qwen3-tts-v032-stack112-clean;C:\_repoz\qwen3-tts-bridge-cpp\external\python\Qwen3-TTS-streaming'
.\.venv-faster-qwen\Scripts\python.exe scripts\qwen_prefill_context_gate.py `
    --model models\Qwen3-TTS-12Hz-0.6B-CustomVoice `
    --device cuda `
    --dtype bfloat16 `
    --attn-implementation sdpa `
    --speaker ryan `
    --text "I am your robot, I am your worker." `
    --language English `
    --max-new-tokens 64 `
    --repeats 1 `
    --include-product-compat `
    --include-reduce-overhead `
    --compact-output `
    --output tmp\context-gate-product-lifecycle-smoke.json
```

Smoke result:

```text
raw_eager, strict_eager, strict_inductor_default, strict_reduce_overhead,
product_strict_inductor_default, product_strict_reduce_overhead:
  semantic_pass=true
  termination_equal=true
  same_codec=true
  same_frame_count=true
  prefill diff vs raw=0.0
```

Lifecycle patch SHA256:

```text
faster-qwen-strict-bf16-sdpa-lifecycle-patch/0001-feat-prefill-add-strict-bf16-sdpa-compat-mode.patch  7717E6DF57F032208F44529229187457B53A9CD871EE2BF8D8387CDC6B6E5D06
faster-qwen-strict-bf16-sdpa-lifecycle-patch/0002-fix-prefill-make-compat-mode-immutable.patch  90DA4DA036BA242A4B7DCCA6115B51BB08E88675638BD5675BC32C2C9C9A2556
faster-qwen-strict-bf16-sdpa-lifecycle-patch/faster-qwen-prefill-compile-through-95ea2ca.bundle  3FCED2B067672D497F07F23AC1B842B39132E3718206902AA6845D713AE9DA12
```

2026-07-28 strict BF16 SDPA prefill-only lifecycle correction:

```text
faster-qwen3-tts lifecycle commit: 9023eb8
scope:
  - pass prefill_compile_compat_mode into the returned FasterQwen3TTS wrapper
  - expose public prefill_compile_compat_metadata
  - validate strict target module counts at load without keeping forwards patched
  - apply strict forwards only inside compiled prefill calls
  - require warmup_synthesis_enabled=true for bridge strict product mode
  - validate bridge strict metadata before ready
```

Verification after prefill-only correction:

```text
FasterQwen targeted:
  .venv-faster-qwen\Scripts\python.exe -m pytest tests\test_prefill_compat.py tests\test_sampling.py -q
  result: 52 passed, 1 warning

FasterQwen selected:
  .venv-faster-qwen\Scripts\python.exe -m pytest tests\test_ggml_backend.py tests\test_prefill_compat.py tests\test_sample_rate.py tests\test_sampling.py tests\test_voice_clone_prompt_api.py -q
  result: 109 passed, 1 warning

FasterQwen full:
  $env:PYTHONPATH='C:\_repoz\qwen3-tts-bridge-cpp\external\python\Qwen3-TTS-streaming'
  .venv-faster-qwen\Scripts\python.exe -m pytest -q
  result: 123 passed, 18 warnings, 298.34s

Bridge Python:
  scripts\check-python.ps1 -UseVenv -VenvPath .venv
  result: 158 tests OK, 2 skipped

Bridge C++:
  ctest --test-dir build\default --output-on-failure
  result: 9/9 passed

Bridge targeted:
  $env:PYTHONPATH='worker/src;tests/python'
  .venv\Scripts\python.exe -m unittest tests.python.test_qwen_engine tests.python.test_qwen_model_loader tests.python.test_engine_factory
  result: 49 tests OK

py_compile:
  .venv\Scripts\python.exe -m py_compile scripts\qwen_prefill_compile_parity.py scripts\qwen_prefill_context_gate.py scripts\qwen_strict_worker_load_smoke.py
  result: passed
```

Real worker-load strict smoke through bridge QwenTtsEngine:

```powershell
$env:PYTHONPATH='C:\_repoz\qwen3-tts-bridge-cpp\worker\src;C:\_repoz\faster-qwen3-tts-v032-stack112-clean;C:\_repoz\qwen3-tts-bridge-cpp\external\python\Qwen3-TTS-streaming'
.\.venv-packaging\Scripts\python.exe scripts\qwen_strict_worker_load_smoke.py `
    --model models\Qwen3-TTS-12Hz-0.6B-CustomVoice `
    --device cuda `
    --dtype bfloat16 `
    --attn-implementation sdpa `
    --prefill-backend compile_reduce_overhead `
    --speaker ryan `
    --text "I am your robot, I am your worker." `
    --language English `
    --warmup-synthesis `
    --warmup-max-output-chunks 1 `
    --max-chunks 1 `
    --output tmp\strict-worker-load-smoke-packaging.json
```

Smoke result:

```text
metadata before ready/warmup:
  wrapper=declared=mode=strict_bf16_sdpa_v1
  applied=false
  patched_modules={}
  validated_modules={rmsnorm: 134, mlp: 33, attention: 33}
warmup: 1 bounded audio chunk
request: 1 PCM chunk, 29610 bytes
prefill_backend_used=compile_reduce_overhead
prefill_compile_fallback=false
chunk metrics report transient strict patch:
  prefill_compile_compat_applied=true
  patched_modules={rmsnorm: 134, mlp: 33, attention: 33}
```

Environment note:

```text
.venv-faster-qwen has torch 2.10.0+cu128 and no Triton package, so the same
worker-load smoke falls back to eager prefill there. The compile-path smoke
above intentionally uses .venv-packaging, which has torch 2.11.0+cu126 and
triton-windows 3.7.1.post27.
```

Semantic context gate after prefill-only correction:

```powershell
$env:PYTHONPATH='C:\_repoz\faster-qwen3-tts-v032-stack112-clean;C:\_repoz\qwen3-tts-bridge-cpp\external\python\Qwen3-TTS-streaming'
.\.venv-packaging\Scripts\python.exe scripts\qwen_prefill_context_gate.py `
    --model models\Qwen3-TTS-12Hz-0.6B-CustomVoice `
    --device cuda `
    --dtype bfloat16 `
    --attn-implementation sdpa `
    --speaker ryan `
    --text "I am your robot, I am your worker." `
    --language English `
    --max-new-tokens 64 `
    --repeats 1 `
    --include-product-compat `
    --include-reduce-overhead `
    --compact-output `
    --output tmp\context-gate-prefill-only-smoke.json
```

Semantic result:

```text
raw_eager, strict_eager, strict_inductor_default, strict_reduce_overhead,
product_strict_inductor_default, product_strict_reduce_overhead:
  semantic_pass=true
  termination_equal=true
  same_codec=true
  same_frame_count=true
  prefill diff vs raw=0.0
```

Prefill-only lifecycle patch SHA256:

```text
faster-qwen-strict-bf16-sdpa-lifecycle-patch/0003-fix-prefill-keep-strict-compat-prefill-only.patch  4138C702545AE8A84397AE7466F38262E4D17E96E1FE2A3B81CC47B0BBFFFAE8
faster-qwen-strict-bf16-sdpa-lifecycle-patch/faster-qwen-prefill-compile-through-9023eb8.bundle  6CD1E618B8F728420275973621A654F83559989B208A523B86F8C8ECB3E36FCB
```

Diagnostic semantic gates:

```powershell
.\.venv-faster-qwen\Scripts\python.exe scripts\qwen_prefill_context_gate.py `
    --model models\Qwen3-TTS-12Hz-0.6B-CustomVoice `
    --device cuda `
    --dtype bfloat16 `
    --attn-implementation sdpa `
    --speaker ryan `
    --text "I am your robot, I am your worker." `
    --language English `
    --max-new-tokens 64 `
    --repeats 3 `
    --include-reduce-overhead `
    --output docs\benchmark-artifacts\rtx4090-2026-07-22\context-gate-v2\bf16-sdpa-raw-strict-inductor-reduce-r3.json

.\.venv-faster-qwen\Scripts\python.exe scripts\qwen_prefill_context_gate.py `
    --model models\Qwen3-TTS-12Hz-0.6B-CustomVoice `
    --device cuda `
    --dtype bfloat16 `
    --attn-implementation sdpa `
    --speaker ryan `
    --text "I am your robot, I am your worker." `
    --language English `
    --max-new-tokens 256 `
    --repeats 3 `
    --include-reduce-overhead `
    --output docs\benchmark-artifacts\rtx4090-2026-07-22\context-gate-v2\bf16-sdpa-raw-strict-inductor-reduce-eos-r3.json

.\.venv-faster-qwen\Scripts\python.exe scripts\qwen_prefill_context_gate.py `
    --model models\Qwen3-TTS-12Hz-0.6B-CustomVoice `
    --device cuda `
    --dtype bfloat16 `
    --attn-implementation sdpa `
    --speaker ryan `
    --text "I am your robot, I am your worker." `
    --language English `
    --max-new-tokens 64 `
    --repeats 3 `
    --include-product-compat `
    --include-reduce-overhead `
    --output docs\benchmark-artifacts\rtx4090-2026-07-22\context-gate-v2\product-strict-bf16-sdpa-r3.json

.\.venv-faster-qwen\Scripts\python.exe scripts\qwen_prefill_context_gate.py `
    --model models\Qwen3-TTS-12Hz-0.6B-CustomVoice `
    --device cuda `
    --dtype bfloat16 `
    --attn-implementation sdpa `
    --speaker ryan `
    --text "I am your robot, I am your worker." `
    --language English `
    --max-new-tokens 256 `
    --repeats 3 `
    --include-product-compat `
    --include-reduce-overhead `
    --output docs\benchmark-artifacts\rtx4090-2026-07-22\context-gate-v2\product-strict-bf16-sdpa-eos-r3.json
```

Additional semantic matrix:

```text
context-gate-v2/semantic-russian-quote-bf16-sdpa-r3.json
  text: Я твой робот, я твой работник.
  language: Russian
  max_new_tokens: 128
  result: semantic_pass=true for all comparisons; termination_equal=true

context-gate-v2/semantic-english-instruction-short-bf16-sdpa-r3.json
  text: I am online.
  instruction: Speak calmly.
  language: English
  max_new_tokens: 128
  result: semantic_pass=true for all comparisons; termination_equal=true

context-gate-v2/matrix-customvoice-english-short-product-r3.json
  text: Hello.
  include_product_compat: true
  compact_output: true
  result: semantic_pass=true for product strict contexts; EOS termination

context-gate-v2/matrix-customvoice-english-long-product-r3.json
  text: This is a longer validation sentence for the strict compiled prefill path.
  include_product_compat: true
  compact_output: true
  result: semantic_pass=true for product strict contexts; max_new_tokens termination
```

Source-worker product A/B command template:

```powershell
$env:PYTHONPATH='C:\_repoz\qwen3-tts-bridge-cpp\worker\src;C:\_repoz\faster-qwen3-tts-v032-stack112-clean;C:\_repoz\qwen3-tts-bridge-cpp\external\python\Qwen3-TTS-streaming;C:\_repoz\qwen3-tts-bridge-cpp\tests\python'
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv-packaging\Scripts\python.exe -B tests\python\benchmark_packaged_worker_restart.py `
    .\.venv-packaging\Scripts\python.exe `
    --worker-prefix-arg=-B `
    --worker-prefix-arg=-P `
    --worker-prefix-arg=-s `
    --worker-prefix-arg=-m `
    --worker-prefix-arg=qwen_tts_bridge_worker `
    --engine qwen `
    --model-path models\Qwen3-TTS-12Hz-0.6B-CustomVoice `
    --runtime-backend faster `
    --device cuda `
    --dtype bfloat16 `
    --attn-implementation sdpa `
    --emit-every-frames 8 `
    --max-seq-len 2048 `
    --warmup-synthesis `
    --warmup-synthesis-passes 1 `
    --warmup-text "I am your robot, I am your worker." `
    --warmup-language English `
    --warmup-speaker ryan `
    --runs 5 `
    --requests-per-run 4 `
    --seed 4242 `
    --seed-mode fixed `
    --warmup-seed 4242 `
    --text "I am your robot, I am your worker." `
    --language English `
    --speaker ryan `
    --profile-prefill `
    --prefill-backend <eager|compile_inductor_default|compile_reduce_overhead> `
    --prefill-compile-compat-mode <none|strict_bf16_sdpa_v1> `
    --no-sample `
    --allow-unverified-faster-wheel `
    --partial-output docs\benchmark-artifacts\rtx4090-2026-07-22\product-compat-performance\<output>.json `
    --timeout-seconds 1200
```

Product A/B results:

```text
source-worker-eager-r5x4.json
  backend=eager, compat=none
  steady first audio median: 357.2 ms
  steady completed median: 1441.3 ms
  steady RTF median: 0.379
  steady prefill median: 136.2 ms

source-worker-product-strict-inductor-default-r5x4.json
  backend=compile_inductor_default, compat=strict_bf16_sdpa_v1
  steady first audio median: 322.4 ms
  steady completed median: 1363.5 ms
  steady RTF median: 0.358
  steady prefill median: 109.2 ms
  speedup vs eager: first audio 1.11x, completed 1.06x

source-worker-product-strict-reduce-r5x4.json
  backend=compile_reduce_overhead, compat=strict_bf16_sdpa_v1
  steady first audio median: 228.1 ms
  steady completed median: 1266.6 ms
  steady RTF median: 0.333
  steady prefill median: 11.3 ms
  speedup vs eager: first audio 1.56x, completed 1.14x
```

Verification:

```text
FasterQwen targeted: py_compile passed; pytest tests/test_sampling.py tests/test_prefill_compat.py -q -> 45 passed, 1 warning
FasterQwen selected non-e2e suite -> 102 passed, 1 warning
FasterQwen e2e parity with Qwen fork on PYTHONPATH -> 14 passed, 17 warnings
FasterQwen full suite with Qwen fork on PYTHONPATH -> 116 passed, 18 warnings
Bridge worker Python checks after integration -> scripts/check-python.ps1 -UseVenv -VenvPath .venv passed; 154 tests OK, 2 skipped
Bridge C++ ctest -> 9/9 passed
Bridge stdio stress -> ctest --test-dir build\default -R stdio_transport_test --output-on-failure --repeat until-fail:20 passed 20/20
```

Artifact SHA256:

```text
context-gate-v2/bf16-sdpa-raw-strict-inductor-reduce-eos-r3.json  7B87305214A88F3FDA9A0C3452B550E6A26B3DA3D4CB30F96D87C7B4EAAF8796
context-gate-v2/bf16-sdpa-raw-strict-inductor-reduce-r3.json  9B3ABE00BF3A71CDBD0A7B6705A9F0B05D36EA51DBFD8A8973FB414E12F61B52
context-gate-v2/matrix-customvoice-english-long-product-r3.json  55C7BECC7C237493D3C736B7E7CFCE148679E19AA6B16C5FDB93D4B7239A7A13
context-gate-v2/matrix-customvoice-english-short-product-r3.json  13B27B11F9AE2F65E9852E064CD07C58FD80B1FCA5611F3E20A81BCDE25E3B69
context-gate-v2/product-strict-bf16-sdpa-eos-r3.json  064B7753C3D69195F896F5FB8E9D2D76D60053D8FF81D790578FD0AE018A7E5C
context-gate-v2/product-strict-bf16-sdpa-r3.json  B243D3F7096F53986BAACDBE30B4934E95027F1FD7E9179D9F933C06C0CBBD27
context-gate-v2/semantic-english-instruction-short-bf16-sdpa-r3.json  7ABA9A03CB75FEF0A416A6FF9AC128EED4C08D161FC932AD3B787FB54747E259
context-gate-v2/semantic-russian-quote-bf16-sdpa-r3.json  16A12355C2E5272F34E0ACCD215235477A5A7005262293679BC0136B222EBBDC
product-compat-performance/source-worker-eager-r5x4.json  C0BE752370DED6F7C30D1E949FB265BD58BEC957DD0CA891380D228A204EE583
product-compat-performance/source-worker-product-strict-inductor-default-r5x4.json  0115D646DFA1F93F419371FDA585BA4ECFFDC0CF00B031ADC2C58139C109F53B
product-compat-performance/source-worker-product-strict-reduce-r5x4.json  633EAE622D6F5EBD74B39848CF6E083C5F54B4C9513E8C9AD3C8EF7395D5EEAF
product-compat-performance/summary.json  F30E2AE46C23F7C4F9880B84A786D8FB328FD0C251C9011239CE54456ADC2E6B
faster-qwen-strict-bf16-sdpa-product-patch/0001-feat-prefill-add-strict-bf16-sdpa-compat-mode.patch  C03956AC16C34D913588EE86E0300EFC51121282D0E5B7040F4E66E652CA5810
faster-qwen-strict-bf16-sdpa-product-patch/faster-qwen-prefill-compile-through-12527a7.bundle  09841C65217B2E2FE075234ACBF1CC2FB20F0C02EB6EED60111F1F1F9B46D2DE
```

2026-07-25/26 profile cleanup and diagnostic r100:

```text
faster-qwen3-tts cleanup commit: 71fa0fd
cleanup wheel SHA256: 0b3aa64a592daa4d573b500455c27d87df54cdfd41219217bf153ffb2c94d0dc
patch series: faster-qwen3-tts-telemetry-patch/0001-0005-prefill-profile-telemetry-cleanup-series.patch
patch series SHA256: 374937d27ba58762092a7978ff5c82b28871e24b38630b8d6aeb2afcd8a3b8cc
git bundle: faster-qwen3-tts-telemetry-patch/faster-qwen3-tts-afa6120-to-71fa0fd.bundle
git bundle SHA256: 85b5d68076b7bb330b9c98cbd6af708b75fdd6d1b7dc7c358e9dc6f88b2774e7
```

Reanalysis and Nsight summary artifacts:

```text
profile-overhead-control-v3-r50x4-randomized-runs/reanalysis-bootstrap.json
SHA256: 007c106670770b7e1d0f0faa01f9554787d6c1a101abfdf8cc89e89207c7805d

nsight-systems-v3/kern-exec-summary.json
SHA256: 90aabb22c25e1726ffae5ef7d3a3532be5744b17499469c8a6d5c7970825864c

profile-cleanup-bc-smoke-r10x4/B-profile-off-summary.json
SHA256: 8f379d04f1a0b85a6e489e4aced4a494f03cfdea65a5617ac296ef7d43858c87

profile-cleanup-bc-smoke-r10x4/C-profile-on-summary.json
SHA256: 45a18d1d171b316ae6f19c1b4b2108ee3e7317441cc18c9284de63b51ff4b6a9
```

Diagnostic r100:

```text
artifact: diagnostic-r100-profile-cleanup-v3/summary.json
SHA256: 3a1b9604f4f6792d2618ceb31326009c62791794e23ef10438d224b836d35a27
runs: 100 fresh workers
requests per run: 4
profile_prefill: true
profile_nvtx: false
GPU polling: disabled
expected faster wheel SHA256: 0b3aa64a592daa4d573b500455c27d87df54cdfd41219217bf153ffb2c94d0dc

profile_complete: 400/400
stream consistent: 400/400
positive paired deltas >20 ms: 12/100
talker-forward declassified positive outliers below 20 ms: 12/12
conditional outlier total delta p50/p95/max: 25.735 / 51.350 / 52.471 ms
conditional outlier talker-forward delta p50/p95/max: 20.671 / 40.001 / 43.705 ms
conditional outlier unexplained residual p50/p95/max: 7.053 / 13.370 / 15.502 ms
conditional talker attribution fraction min/p50/p95/max: 0.449 / 0.773 / 0.892 / 0.908
conditional attribution counts: >=50% 11/12, >=80% 5/12
per-real-steady positive unexplained residual p95: 8.625 ms
per-real-steady signed unexplained residual p95: 8.990 ms
reanalyzer artifact: diagnostic-r100-profile-cleanup-v3/analysis-cleanup.json
reanalyzer SHA256: 73a0921044d7c5211abb69de80585925cd287ba44cf54292ac3ccc12a52bb371
reanalyzer command:
  PYTHONPATH=tests/python;worker/src .venv-packaging/Scripts/python.exe tests/python/reanalyze_benchmark_report.py --input docs/benchmark-artifacts/rtx4090-2026-07-22/diagnostic-r100-profile-cleanup-v3/summary.json --output docs/benchmark-artifacts/rtx4090-2026-07-22/diagnostic-r100-profile-cleanup-v3/analysis-cleanup.json --threshold-ms 20.0
```

Production profile-off r30:

```text
artifact: production-r30-profile-off-cleanup-v3/summary.json
SHA256: 30db1a8ce55033ed337ec9569109d48c2f76d0de1fb616ffd979095e62b910df
runs: 30 fresh workers
requests per run: 4
profile_prefill: false
profile_nvtx: false
expected faster wheel SHA256: 0b3aa64a592daa4d573b500455c27d87df54cdfd41219217bf153ffb2c94d0dc
first TTFA median/p95: 375.377 ms / 417.717 ms
steady TTFA median/p95: 384.442 ms / 411.271 ms
paired delta median/p95: 2.335 ms / 18.668 ms
profile statuses: disabled 120/120
```

Exact-shape prefill compile prototype:

```text
faster-qwen3-tts branch: prefill-compile-exact-shape
faster-qwen3-tts compile prototype commit: f08260d
faster-qwen3-tts diagnostic commit: f3b979c
portable faster wheel SHA256: fd6f117280ea44702b15eb417262d5019f97d748ac767a437befeede23c0c4fe
clean diagnostic wheel SHA256: 4afd978d30b0d6d703aca38d0e59aa396492b99d4695a108938aa35b84425019
bridge worker flag: --prefill-backend eager|compile_backend_eager|compile_backend_aot_eager|compile_inductor_default|compile_default|compile_reduce_overhead
model: models/Qwen3-TTS-12Hz-0.6B-CustomVoice
speaker: ryan
text: I am your robot, I am your worker.
decode: greedy (--no-sample)
warmup: same synthesis text/language/speaker as measured request
runtime provenance: --allow-unverified-faster-wheel because portable install
  did not expose installed_archive_sha256; wheel hash and faster commit are
  recorded here instead.
```

R3 exploratory artifacts:

```text
prefill-compile-exact-shape-smoke-r3/eager-summary.json
SHA256: 0ffb8b857cc62ab96ea4802ccb4c80fb42447d9b403e9a9805724f87051ed97f
prefill-compile-exact-shape-smoke-r3/compile_default-summary.json
SHA256: f1da27ef07b8a53571cfe810f0998b6fba48fa085982db8b9548c6201174854d
prefill-compile-exact-shape-smoke-r3/compile_reduce_overhead-summary.json
SHA256: dac77665a761ffb20b00445d8432648b00e2b39ab7c12ad98fc32c61e0a96ddb
prefill-compile-exact-shape-samewarmup-r3/compile_default-summary.json
SHA256: f677776046c901386c817645329e0d085e51604fd2b1735c827fe6caeef46e3e
prefill-compile-exact-shape-samewarmup-r3/compile_reduce_overhead-summary.json
SHA256: 32f8dd0a8d04bd3f768eab348f63a8f2315703aad74d1d7ed6a953c283e9a7c9
```

R10 production-control artifacts:

```text
prefill-compile-exact-shape-r10/profile-on-eager-summary.json
SHA256: 2701bd990f325db8e845930c47f616bb0bcf94039e0fb9051626f56566a64164
prefill-compile-exact-shape-r10/profile-on-compile_reduce_overhead-summary.json
SHA256: 3da14b8d4d823d8ab547e3926e3156762ea8c077d7bac66543a9b8a6608ee294
prefill-compile-exact-shape-r10/profile-off-eager-summary.json
SHA256: 950e78f513689784f4f122dc9d5931fe1ff04045f9b0b525c77b48fd0fd07803
prefill-compile-exact-shape-r10/profile-off-compile_reduce_overhead-summary.json
SHA256: 0257014f9a8a8a89f26770fe2db13183f1d662255624d7b5b26e9258654812a3
prefill-compile-exact-shape-r10/prefill-parity-probe.json
SHA256: f6835b63eba4aaf12a257f8e0fea061fa28fe4473a088e6846d9ca3a765c7ad8

profile-off eager first TTFA median/p95: 391.653 ms / 413.613 ms
profile-off compile_reduce_overhead first TTFA median/p95: 274.279 ms / 294.758 ms
profile-off eager steady TTFA median/p95: 372.017 ms / 407.316 ms
profile-off compile_reduce_overhead steady TTFA median/p95: 233.914 ms / 244.649 ms
profile-on eager steady talker-forward median/p95: 128.720 ms / 173.398 ms
profile-on compile_reduce_overhead steady talker-forward median/p95: 3.308 ms / 4.240 ms
compile_reduce_overhead fallbacks: 0/40 profile-on, 0/40 profile-off
parity gate: failed; eager/eager repeat was exact, but compiled prefill differed
  from eager by logits_last_max_abs=0.2578125 and past_hidden_max_abs=0.546875.
semantic parity gate: failed; compiled greedy output is shorter.
  eager output: 232162 PCM bytes, 8 chunks, 4836.708 ms audio
  compile_reduce_overhead output: 175046 PCM bytes, 6 chunks, 3646.792 ms audio
  duration delta: -24.6%
  completion time and RTF are not apples-to-apples for eager vs compiled.
```

Compile prototype source artifacts:

```text
faster-qwen-prefill-compile-patch/0001-feat-prefill-add-exact-shape-compile-backend-switch.patch
SHA256: a486d09fdbc739157b5c05b5da56bed0fddc8185a30d7babd28273cf8e141e3c
faster-qwen-prefill-compile-patch/0002-test-prefill-add-diagnostic-compile-backends.patch
SHA256: be279eaebf202cdd1a342624e76575cddf73b41cb62f78e903ae79b3fd4a0de7
faster-qwen-prefill-compile-patch/faster-qwen3-tts-71fa0fd-to-f3b979c.bundle
SHA256: a85e8f371ccc649b3d2c2eab4b8b9522c1501c7cb0429a99c4e488666965f908
```

Compile parity ladder artifacts:

```text
script: scripts/qwen_prefill_compile_parity.py

prefill-compile-parity-ladder/bf16-ladder-r2.json
SHA256: a669c7c09384a4b6bc0909ca0177a277c97a289f156a9b95aef4213d59db1fd3
prefill-compile-parity-ladder/bf16-precision-control-prefill-r2.json
SHA256: 563e9892de3e6c4a111c3207b115631ddf02e5ad47cce705aecae920fbd06161
prefill-compile-parity-ladder/fp32-prefill-r2.json
SHA256: 0c14bbb52e28cf9d57eb89bbd97c7bff752eeff750b81cf4df6cfcc164bc35f6
prefill-compile-parity-ladder/bf16-generation-eos-r1.json
SHA256: 58d8ffe9cd6515b8c8b7f94c3c1c02fe234b2e57a429963fd15b9c5aacbbe313

BF16 ladder:
  compile_backend_eager logits_last_max_abs: 0.21875
  compile_backend_aot_eager logits_last_max_abs: 0.21875
  compile_inductor_default logits_last_max_abs: 0.2578125
  compile_reduce_overhead logits_last_max_abs: 0.2578125
  same-backend prefill repeat stability: 0.0 max abs for logits_last and past_hidden
  32-frame capped generation: all compiled backends changed codec hashes and
    diverged at frame 0 while frame count and audio samples stayed equal.

BF16 precision control:
  TF32 disabled and matmul precision highest did not restore parity.
  backend-eager/aot-eager logits_last_max_abs: 0.2509765625
  Inductor logits_last_max_abs: 0.25

FP32 control:
  TF32 disabled and matmul precision highest nearly restored prefill parity.
  compiled logits_last_max_abs: 1.9073486328125e-05

Full BF16 direct generation control:
  eager: 46 frames, 87765 samples, 3656.875 ms audio
  compile_reduce_overhead: 50 frames, 95445 samples, 3976.875 ms audio
  first codec divergence: frame 0, codebook 5
  direct harness duration direction differs from packaged r10, but both prove
    that compiled BF16 prefill changes the greedy codec/waveform trajectory.

Verification after adding the parity ladder:
  scripts/check-python.ps1 -UseVenv
    passed: Ruff, Pyright, 154 Python tests, 2 skipped
  ctest --test-dir build/default --output-on-failure
    first full run: stdio_transport_test timed out waiting for a frame
    isolated retry: stdio_transport_test passed
    second full run: 9/9 C++ tests passed

Clean portable worker rebuild after commit fbdfa2e:
  command:
    scripts/package-python-worker.ps1 -Clean -IncludeQwenFork `
      -QwenSourcePath external/python/Qwen3-TTS-streaming `
      -IncludeFasterQwen `
      -FasterQwenSourcePath C:/_repoz/faster-qwen3-tts-v032-stack112-clean `
      -UseVenv
  build-manifest.json SHA256:
    2c27bdc85ccc35dee3452e9823e966a25d340e23809eae4a8e644a1d91564c5e
  staged bridge worker wheel SHA256:
    f8a1c3e0a31d682d303c6342ae63ff01632f7911dab6d66c78816988b8274b35
  staged qwen fork wheel SHA256:
    d9d782739fa9574082a530ef710bd0eece976f6f64e61574a97d039189b63bd4
  staged faster-qwen wheel SHA256:
    f3048bd67b9027207aad27d4d4f5464e00e912f01cf87ec2390cb6290b861ac7
  clean sources in manifest:
    bridge worker git_commit fbdfa2e30a2b71f688cd3d75bd28c4397bc1c3ea
    Qwen fork git_commit 25cc5886a753035ac3ed9d4000440b2e842e5e56
    faster-qwen git_commit f3b979c818f21b31a09656fff09022120cc73951
  mock portable probe:
    scripts/test-portable-python-worker.ps1 -UseVenv `
      -WorkerCommand dist/QwenTTSBridge/worker-python/qwen_tts_worker.cmd `
      -TimeoutSeconds 30 -MockChunks 2
    passed
  real-model portable faster eager smoke:
    verify_packaged_worker.py dist/QwenTTSBridge/worker-python/qwen_tts_worker.cmd `
      --engine qwen --runtime-backend faster `
      --model-path models/Qwen3-TTS-12Hz-0.6B-CustomVoice `
      --device cuda --dtype bfloat16 --attn-implementation eager `
      --text "I am your robot, I am your worker." --language English `
      --speaker ryan --enable-streaming-optimizations --no-compile `
      --no-cuda-graphs --matmul-precision high --prefill-backend eager `
      --no-sample
    passed
  real-model portable diagnostic compile smoke:
    same command with --prefill-backend compile_backend_eager
    passed as a startup/protocol smoke only; semantic parity remains failed.
```

True-greedy predictor follow-up:

```text
problem confirmed:
  FasterQwen from_pretrained constructed PredictorGraph(do_sample=True).
  fast_generate_streaming(do_sample=False) only made talker codebook 0 greedy;
  residual predictor codebooks 1..15 still used PredictorGraph sampling.

faster-qwen3-tts fix commit: 0272258
commit message: fix(predictor): honor greedy mode for residual codebooks

source artifacts:
  faster-qwen-true-greedy-predictor-patch/0001-feat-prefill-add-exact-shape-compile-backend-switch.patch
  SHA256: 00b124e225e28d72e8efcf756143cdbf93bd780745bdcc612738c3031d098477
  faster-qwen-true-greedy-predictor-patch/0002-test-prefill-add-diagnostic-compile-backends.patch
  SHA256: 9195ebdb84b266c028cafd3c7fc725299d743cba2d3c502efb51530b5842e7a7
  faster-qwen-true-greedy-predictor-patch/0003-fix-predictor-honor-greedy-mode-for-residual-codeboo.patch
  SHA256: 5ab612173ea1de08970153522d7d74e4d73b6a89385185b18592dafe1602f549
  faster-qwen-true-greedy-predictor-patch/faster-qwen3-tts-71fa0fd-to-0272258.bundle
  SHA256: 27e84a8fd011d0ca985f6e286d54f645c3901c708b33cb11edb77d5ab9b430fe

bridge harness update:
  scripts/qwen_prefill_compile_parity.py now selects model._select_predictor_graph(False)
  when calling fast_generate_streaming directly.

available checks:
  .venv-packaging/Scripts/python.exe -m py_compile `
    scripts/qwen_prefill_compile_parity.py `
    scripts/qwen_prefill_module_parity.py `
    C:/_repoz/faster-qwen3-tts-v032-stack112-clean/faster_qwen3_tts/model.py `
    C:/_repoz/faster-qwen3-tts-v032-stack112-clean/tests/test_sampling.py
    passed
  inline selector/multinomial guard:
    passed
  pytest was not available in .venv-packaging or .venv-faster-qwen.
  scripts/check-python.ps1 -UseVenv
    passed: Ruff, Pyright, 154 Python tests, 2 skipped
  ctest --test-dir build/default --output-on-failure
    first full run: stdio_transport_test timed out waiting for a frame
    isolated retry: stdio_transport_test passed
    second full run: 9/9 C++ tests passed

true-greedy artifacts:
  true-greedy-predictor/eager-repeat-r3.json
  SHA256: 96d710ccd735ed83d7104ba27c05d5009a08ae4734b2a1965092232c6c08fd33
  result: raw eager x3 same_codec=true, same_frame_count=true, same_audio_samples=true

  true-greedy-predictor/bf16-ladder-r2.json
  SHA256: df6c6a166100a2ed92ce9fa0f9e512f3c2964f6942b3e99aef40e59c07853097
  result: BF16 compiled backends still fail true-greedy semantic parity.
    compile_backend_eager first divergence: frame 1, codebook 8
    compile_backend_aot_eager first divergence: frame 1, codebook 8
    compile_inductor_default first divergence: frame 0, codebook 15
    compile_reduce_overhead first divergence: frame 0, codebook 15

  true-greedy-predictor/bf16-precision-control-ladder-r2.json
  SHA256: b67078b01932d957786e44e6833c6ac76d14600cda6b2a7809dd9bc33479f9f0
  result: disabling TF32/reduced-precision reductions did not restore BF16 parity.

  true-greedy-predictor/fp32-ladder-r2.json
  SHA256: aa8bebcc1850161fed3d7d3ad1ed921aeea4c1c4ed45e5af404f9f37b7a2657b
  result: FP32 true-greedy semantic parity passed for compile_backend_eager,
    compile_backend_aot_eager, and compile_inductor_default.

hook localization artifacts:
  script: scripts/qwen_prefill_module_parity.py

  true-greedy-predictor/bf16-hook-smoke.json
  SHA256: dbadef94e1334b3df4311be0181c7c5af29e52f65bc13796cb575a7b22224c93

  true-greedy-predictor/bf16-layer0-hook-smoke.json
  SHA256: e3fc3dbf2bd269076ccd1a2b4e74c27099ef7d160cf3337ebd04d6098a135430
  first visible layer-0 difference:
    model.layers.0.self_attn.o_proj max_abs=0.00048828125
    rmse=3.2677187846275046e-05
  layer-0 output:
    model.layers.0 max_abs=0.03125

  true-greedy-predictor/fp32-layer0-hook-smoke.json
  SHA256: cfc729ca093277b237ad7de6692ade246f97696df3200be5a88db9bfbd6d38b2
  first visible layer-0 difference:
    model.layers.0.self_attn.o_proj max_abs=4.172325134277344e-07
    rmse=1.313299780036914e-08

compile-aware branch search:
  rg -n "is_compiling|torch\\.compiler|torch\\._dynamo|dynamo|compile" `
    C:/_repoz/faster-qwen3-tts-v032-stack112-clean/faster_qwen3_tts `
    external/python/Qwen3-TTS-streaming/qwen_tts
  result: no obvious is_compiling branch found in the FasterQwen/Qwen talker
    prefill path; hits were compile setup helpers and cudagraph markers.
```

Paired same-process Nsight captures:

```text
artifact directory: nsight-systems-paired-v3/
summary: nsight-systems-paired-v3/paired-summary.json
summary SHA256: 50f8a929276334636b6733d17851355bc1b5541bf81c8142ddd102c568a4ba50
capture range: qtb_profile_first_steady_pair
nested ranges: qtb_profile_first_user_prefill, qtb_profile_steady_prefill
trace count: 20
positive first-minus-steady prefill deltas >20 ms: 0/20
limitation: these paired Nsight captures did not directly catch a positive p95
tail process; use diagnostic r100 CUDA-event data for positive-tail attribution.
```

Using:

```text
C:/_repoz/qwen3-tts-bridge-cpp/.venv-faster-qwen/Scripts/python.exe
```

Commands:

```powershell
$repo = 'C:\_repoz\qwen3-tts-bridge-cpp'
$py = "$repo\.venv-faster-qwen\Scripts\python.exe"

& $py "$repo\scripts\faster-qwen-profile-next.py" `
    --runs 20 `
    --chunk-size 8 `
    --seed 4242 `
    --output "$repo\tmp\faster-profile-next-stack112-clean-torch210-cu128-seed4242-r20.json"

& $py "$repo\scripts\faster-qwen-profile-codec-split.py" `
    --runs 5 `
    --chunk-size 8 `
    --seed 4242 `
    --output "$repo\tmp\faster-codec-split-stack112-clean-torch210-cu128-seed4242-r5.json"

& $py "$repo\scripts\faster-qwen-profile-adaptive-chunks.py" `
    --runs 20 `
    --producer-chunk-size 4 `
    --first-output-steps 4 `
    --steady-output-steps 12 `
    --seed 4242 `
    --output "$repo\tmp\faster-adaptive-4to12-stack112-clean-torch210-cu128-seed4242-r20-fixed.json"
```

Unified schedule performance pass:

```powershell
$modes = @(
    @('fixed8', '8', '8'),
    @('fixed12', '12', '12'),
    @('4to12', '4', '4,12'),
    @('4to8to12', '4', '4,8,12')
)

foreach ($mode in $modes) {
    $name = $mode[0]
    $producer = $mode[1]
    $schedule = $mode[2]
    & $py "$repo\scripts\faster-qwen-profile-adaptive-chunks.py" `
        --runs 20 `
        --producer-chunk-size $producer `
        --output-schedule $schedule `
        --seed 4242 `
        --transport-reserve-ms 50 `
        --output "$repo\tmp\faster-schedule-$name-stack112-clean-torch210-cu128-seed4242-r20-v3.json"
}
```

Schedule correctness pass with codec hashing enabled outside the timed path:

```powershell
foreach ($mode in $modes) {
    $name = $mode[0]
    $producer = $mode[1]
    $schedule = $mode[2]
    & $py "$repo\scripts\faster-qwen-profile-adaptive-chunks.py" `
        --runs 5 `
        --producer-chunk-size $producer `
        --output-schedule $schedule `
        --seed 7777 `
        --transport-reserve-ms 50 `
        --hash-codecs `
        --output "$repo\tmp\faster-schedule-$name-stack112-clean-torch210-cu128-seed7777-r5-hash.json"
}
```

Worker engine CustomVoice smoke:

```powershell
$env:PYTHONPATH = "$repo\worker\src"

@'
import threading
from qwen_tts_bridge_worker.config import QwenEngineConfig
from qwen_tts_bridge_worker.engine.qwen_engine import QwenTtsEngine
from qwen_tts_bridge_worker.engine.types import SynthesisRequest

engine = QwenTtsEngine(QwenEngineConfig(
    model_path='models/Qwen3-TTS-12Hz-0.6B-CustomVoice',
    runtime_backend='faster',
    dtype='bfloat16',
    attn_implementation='eager',
    emit_every_frames=8,
    warmup_synthesis_enabled=True,
    warmup_text='Warmup.',
    warmup_language='English',
    warmup_speaker='ryan',
))
engine.load()
engine.warmup()
list(engine.synthesize_stream(
    SynthesisRequest(
        request_id=1,
        text='This is a faster backend bridge smoke test.',
        language='English',
        speaker='ryan',
    ),
    threading.Event(),
))
engine.close()
'@ | & $py -
```

Source worker IPC benchmark:

```powershell
$sourceWorker = "$repo\tmp\source_faster_worker.cmd"

@"
@echo off
setlocal
set "PYTHONPATH=$repo\worker\src"
set "PYTHONDONTWRITEBYTECODE=1"
"$repo\.venv-faster-qwen\Scripts\python.exe" -B -m qwen_tts_bridge_worker %*
"@ | Set-Content -Path $sourceWorker -Encoding ASCII

$env:PYTHONPATH = "$repo\worker\src"
& $py "$repo\tests\python\benchmark_packaged_worker.py" `
    $sourceWorker `
    --engine qwen `
    --model-path "$repo\models\Qwen3-TTS-12Hz-0.6B-CustomVoice" `
    --runtime-backend faster `
    --dtype bfloat16 `
    --attn-implementation eager `
    --emit-every-frames 8 `
    --warmup-synthesis `
    --warmup-language English `
    --warmup-speaker ryan `
    --requests 2 `
    --text "This is a faster backend worker IPC benchmark." `
    --language English `
    --speaker ryan `
    --timeout-seconds 1200
```

C++ source-worker smoke:

```powershell
build\default\qwen_tts_save_wav.exe `
    --worker tmp\source_faster_worker.cmd `
    --cwd $repo `
    --output tmp\cpp-faster-customvoice-smoke.wav `
    --text "This is a faster backend C plus plus bridge smoke test." `
    --language English `
    --speaker ryan `
    --startup-timeout-ms 1200000 `
    --request-timeout-ms 1200000 `
    --worker-arg qwen `
    --worker-arg --model-path `
    --worker-arg models\Qwen3-TTS-12Hz-0.6B-CustomVoice `
    --worker-arg --runtime-backend `
    --worker-arg faster `
    --worker-arg --dtype `
    --worker-arg bfloat16 `
    --worker-arg --attn-implementation `
    --worker-arg eager `
    --worker-arg --emit-every-frames `
    --worker-arg 8 `
    --worker-arg --warmup-synthesis `
    --worker-arg --warmup-language `
    --worker-arg English `
    --worker-arg --warmup-speaker `
    --worker-arg ryan
```

Latency ladder, direct engine:

```powershell
$env:PYTHONPATH = "$repo\worker\src"
$env:PYTHONDONTWRITEBYTECODE = "1"
& $py -B scripts\qwen-engine-latency-benchmark.py `
    --model-path models\Qwen3-TTS-12Hz-0.6B-CustomVoice `
    --runtime-backend faster `
    --device cuda `
    --dtype auto `
    --emit-every-frames 8 `
    --max-seq-len 2048 `
    --warmups 5 `
    --requests 30 `
    --text "This is a faster backend latency benchmark." `
    --language English `
    --speaker ryan `
    --output docs\benchmark-artifacts\rtx4090-2026-07-22\latency-ladder-direct-engine-faster-customvoice-chunk8-r30.json
```

Latency ladder, direct engine v2 with local/inverse RTF:

```powershell
$env:PYTHONPATH = "$repo\worker\src"
$env:PYTHONDONTWRITEBYTECODE = "1"
& $py -B scripts\qwen-engine-latency-benchmark.py `
    --model-path models\Qwen3-TTS-12Hz-0.6B-CustomVoice `
    --runtime-backend faster `
    --device cuda `
    --dtype auto `
    --emit-every-frames 8 `
    --max-seq-len 2048 `
    --warmups 5 `
    --requests 30 `
    --text "This is a faster backend latency benchmark." `
    --language English `
    --speaker ryan `
    --output docs\benchmark-artifacts\rtx4090-2026-07-22\latency-ladder-direct-engine-faster-customvoice-chunk8-r30-v2.json
```

Latency ladder, source worker IPC:

```powershell
$env:PYTHONPATH = "$repo\worker\src"
$env:PYTHONDONTWRITEBYTECODE = "1"
& $py -B tests\python\benchmark_packaged_worker.py `
    tmp\source_faster_worker.cmd `
    --engine qwen `
    --model-path models\Qwen3-TTS-12Hz-0.6B-CustomVoice `
    --runtime-backend faster `
    --device cuda `
    --dtype auto `
    --emit-every-frames 8 `
    --max-seq-len 2048 `
    --warmups 5 `
    --requests 30 `
    --text "This is a faster backend latency benchmark." `
    --language English `
    --speaker ryan `
    --timeout-seconds 900 `
    > docs\benchmark-artifacts\rtx4090-2026-07-22\latency-ladder-source-worker-ipc-faster-customvoice-chunk8-r30.json
```

Latency ladder, source worker IPC with block stdout reader:

```powershell
$env:PYTHONPATH = "$repo\worker\src"
$env:PYTHONDONTWRITEBYTECODE = "1"
$out = & $py -B tests\python\benchmark_packaged_worker.py `
    tmp\source_faster_worker.cmd `
    --engine qwen `
    --model-path models\Qwen3-TTS-12Hz-0.6B-CustomVoice `
    --runtime-backend faster `
    --device cuda `
    --dtype auto `
    --emit-every-frames 8 `
    --max-seq-len 2048 `
    --warmups 5 `
    --requests 30 `
    --text "This is a faster backend latency benchmark." `
    --language English `
    --speaker ryan `
    --timeout-seconds 900
[IO.File]::WriteAllText(
    "docs\benchmark-artifacts\rtx4090-2026-07-22\latency-ladder-source-worker-ipc-faster-customvoice-chunk8-r30-block-reader.json",
    ($out -join "`n"),
    [System.Text.UTF8Encoding]::new($false)
)
```

Restart-based first-user-after-ready benchmark:

```powershell
$env:PYTHONPATH = "$repo\worker\src"
$env:PYTHONDONTWRITEBYTECODE = "1"
$out = & $py -B tests\python\benchmark_packaged_worker_restart.py `
    $py `
    --worker-prefix-arg=-B `
    --worker-prefix-arg=-P `
    --worker-prefix-arg=-s `
    --worker-prefix-arg=-m `
    --worker-prefix-arg=qwen_tts_bridge_worker `
    --engine qwen `
    --model-path models\Qwen3-TTS-12Hz-0.6B-CustomVoice `
    --runtime-backend faster `
    --device cuda `
    --dtype auto `
    --emit-every-frames 8 `
    --max-seq-len 2048 `
    --warmup-synthesis `
    --warmup-synthesis-passes 2 `
    --warmup-text "This is a faster backend latency benchmark." `
    --warmup-language English `
    --warmup-speaker ryan `
    --runs 20 `
    --text "This is a faster backend latency benchmark." `
    --language English `
    --speaker ryan `
    --timeout-seconds 1200
[IO.File]::WriteAllText(
    "docs\benchmark-artifacts\rtx4090-2026-07-22\restart-first-user-source-worker-faster-customvoice-chunk8-r20.json",
    ($out -join "`n"),
    [System.Text.UTF8Encoding]::new($false)
)
```

Source-vs-portable parity benchmark shape:

```powershell
$common = @(
    "--engine", "qwen",
    "--model-path", "models\Qwen3-TTS-12Hz-0.6B-CustomVoice",
    "--runtime-backend", "faster",
    "--device", "cuda",
    "--dtype", "auto",
    "--emit-every-frames", "8",
    "--max-seq-len", "2048",
    "--warmup-synthesis",
    "--warmup-synthesis-passes", "2",
    "--warmup-text", "This is a faster backend latency benchmark.",
    "--warmup-language", "English",
    "--warmup-speaker", "ryan",
    "--warmups", "5",
    "--requests", "30",
    "--text", "This is a faster backend latency benchmark.",
    "--language", "English",
    "--speaker", "ryan",
    "--timeout-seconds", "1200"
)

$sourceOut = & $py -B tests\python\benchmark_packaged_worker.py `
    $py `
    --worker-prefix-arg=-B `
    --worker-prefix-arg=-P `
    --worker-prefix-arg=-s `
    --worker-prefix-arg=-m `
    --worker-prefix-arg=qwen_tts_bridge_worker `
    @common

$portableOut = & $py -B tests\python\benchmark_packaged_worker.py `
    dist\QwenTTSBridge\worker-python\qwen_tts_worker.cmd `
    @common

[IO.File]::WriteAllText(
    "docs\benchmark-artifacts\rtx4090-2026-07-22\parity-source-worker-faster-customvoice-chunk8-r30.json",
    ($sourceOut -join "`n"),
    [System.Text.UTF8Encoding]::new($false)
)
[IO.File]::WriteAllText(
    "docs\benchmark-artifacts\rtx4090-2026-07-22\parity-portable-worker-faster-customvoice-chunk8-r30.json",
    ($portableOut -join "`n"),
    [System.Text.UTF8Encoding]::new($false)
)
```

Latency ladder, C++ callback boundary:

```powershell
build\default\qwen_tts_latency_benchmark.exe `
    --worker tmp\source_faster_worker.cmd `
    --worker-arg qwen `
    --worker-arg --model-path `
    --worker-arg models\Qwen3-TTS-12Hz-0.6B-CustomVoice `
    --worker-arg --runtime-backend `
    --worker-arg faster `
    --worker-arg --device `
    --worker-arg cuda `
    --worker-arg --dtype `
    --worker-arg auto `
    --worker-arg --emit-every-frames `
    --worker-arg 8 `
    --worker-arg --max-seq-len `
    --worker-arg 2048 `
    --startup-timeout-ms 1200000 `
    --request-timeout-ms 900000 `
    --warmups 5 `
    --requests 30 `
    --text "This is a faster backend latency benchmark." `
    --language English `
    --speaker ryan `
    > docs\benchmark-artifacts\rtx4090-2026-07-22\latency-ladder-cpp-callback-faster-customvoice-chunk8-r30.json
```

Latency ladder, C++ callback with paired worker telemetry:

```powershell
build\default\qwen_tts_latency_benchmark.exe `
    --worker tmp\source_faster_worker.cmd `
    --worker-arg qwen `
    --worker-arg --model-path `
    --worker-arg models\Qwen3-TTS-12Hz-0.6B-CustomVoice `
    --worker-arg --runtime-backend `
    --worker-arg faster `
    --worker-arg --device `
    --worker-arg cuda `
    --worker-arg --dtype `
    --worker-arg auto `
    --worker-arg --emit-every-frames `
    --worker-arg 8 `
    --worker-arg --max-seq-len `
    --worker-arg 2048 `
    --startup-timeout-ms 1200000 `
    --request-timeout-ms 900000 `
    --warmups 5 `
    --requests 30 `
    --text "This is a faster backend latency benchmark." `
    --language English `
    --speaker ryan `
    > docs\benchmark-artifacts\rtx4090-2026-07-22\latency-ladder-cpp-callback-faster-customvoice-chunk8-r30-paired.json `
    2> docs\benchmark-artifacts\rtx4090-2026-07-22\latency-ladder-cpp-callback-faster-customvoice-chunk8-r30-paired.stderr.txt
```

Ready warmup C++ smoke:

```powershell
build\default\qwen_tts_latency_benchmark.exe `
    --worker tmp\source_faster_worker.cmd `
    --worker-arg qwen `
    --worker-arg --model-path `
    --worker-arg models\Qwen3-TTS-12Hz-0.6B-CustomVoice `
    --worker-arg --runtime-backend `
    --worker-arg faster `
    --worker-arg --device `
    --worker-arg cuda `
    --worker-arg --dtype `
    --worker-arg auto `
    --worker-arg --emit-every-frames `
    --worker-arg 8 `
    --worker-arg --max-seq-len `
    --worker-arg 2048 `
    --worker-arg --warmup-synthesis `
    --worker-arg --warmup-language `
    --worker-arg English `
    --worker-arg --warmup-speaker `
    --worker-arg ryan `
    --startup-timeout-ms 1200000 `
    --request-timeout-ms 900000 `
    --warmups 0 `
    --requests 5 `
    --text "This is a faster backend latency benchmark." `
    --language English `
    --speaker ryan `
    > docs\benchmark-artifacts\rtx4090-2026-07-22\cpp-faster-customvoice-ready-warmup-callback-r5.json `
    2> docs\benchmark-artifacts\rtx4090-2026-07-22\cpp-faster-customvoice-ready-warmup-callback-r5.stderr.txt
```

Latency ladder timestamp smoke:

```powershell
build\default\qwen_tts_latency_benchmark.exe `
    --worker tmp\source_faster_worker.cmd `
    --worker-arg qwen `
    --worker-arg --model-path `
    --worker-arg models\Qwen3-TTS-12Hz-0.6B-CustomVoice `
    --worker-arg --runtime-backend `
    --worker-arg faster `
    --worker-arg --device `
    --worker-arg cuda `
    --worker-arg --dtype `
    --worker-arg auto `
    --worker-arg --emit-every-frames `
    --worker-arg 8 `
    --worker-arg --max-seq-len `
    --worker-arg 2048 `
    --startup-timeout-ms 1200000 `
    --request-timeout-ms 900000 `
    --warmups 1 `
    --requests 2 `
    --text "This is a faster backend latency benchmark." `
    --language English `
    --speaker ryan `
    > docs\benchmark-artifacts\rtx4090-2026-07-22\latency-ladder-cpp-callback-timestamps-smoke-faster-customvoice-chunk8-r2.json `
    2> docs\benchmark-artifacts\rtx4090-2026-07-22\latency-ladder-cpp-callback-timestamps-smoke-faster-customvoice-chunk8-r2.stderr.txt
```

Portable worker faster packaging dry run:

```powershell
.\scripts\package-python-worker.ps1 `
    -UseVenv `
    -DryRun `
    -IncludeQwenFork `
    -IncludeFasterQwen `
    -FasterQwenSourcePath C:\_repoz\faster-qwen3-tts-v032-stack112-clean
```

Portable worker faster packaging real build:

```powershell
.\scripts\package-python-worker.ps1 `
    -UseVenv `
    -Clean `
    -IncludeQwenFork `
    -IncludeFasterQwen `
    -FasterQwenSourcePath C:\_repoz\faster-qwen3-tts-v032-stack112-clean

.\scripts\test-portable-python-worker.ps1 -UseVenv

dist\QwenTTSBridge\worker-python\python\python.exe `
    -P -s -c "import faster_qwen3_tts, qwen_tts, torch; print(faster_qwen3_tts.__version__); print(torch.__version__, torch.version.cuda)"
```

Portable worker real CustomVoice benchmark:

```powershell
$oldPyPath = $env:PYTHONPATH
$oldPyHome = $env:PYTHONHOME
try {
    $env:PYTHONPATH = $null
    $env:PYTHONHOME = $null
    $out = .\.venv\Scripts\python.exe -B tests\python\benchmark_packaged_worker.py `
        dist\QwenTTSBridge\worker-python\qwen_tts_worker.cmd `
        --engine qwen `
        --model-path models\Qwen3-TTS-12Hz-0.6B-CustomVoice `
        --runtime-backend faster `
        --device cuda `
        --dtype auto `
        --emit-every-frames 8 `
        --max-seq-len 2048 `
        --warmup-synthesis `
        --warmup-language English `
        --warmup-speaker ryan `
        --warmups 0 `
        --requests 5 `
        --text "This is a faster backend latency benchmark." `
        --language English `
        --speaker ryan `
        --timeout-seconds 1200
    [IO.File]::WriteAllText(
        "docs\benchmark-artifacts\rtx4090-2026-07-22\latency-ladder-portable-worker-faster-customvoice-chunk8-r5.json",
        ($out -join "`n"),
        [System.Text.UTF8Encoding]::new($false)
    )
}
finally {
    $env:PYTHONPATH = $oldPyPath
    $env:PYTHONHOME = $oldPyHome
}
```

Portable C++ real CustomVoice benchmark:

```powershell
build\default\qwen_tts_latency_benchmark.exe `
    --worker dist\QwenTTSBridge\worker-python\qwen_tts_worker.cmd `
    --worker-arg qwen `
    --worker-arg --model-path `
    --worker-arg models\Qwen3-TTS-12Hz-0.6B-CustomVoice `
    --worker-arg --runtime-backend `
    --worker-arg faster `
    --worker-arg --device `
    --worker-arg cuda `
    --worker-arg --dtype `
    --worker-arg auto `
    --worker-arg --emit-every-frames `
    --worker-arg 8 `
    --worker-arg --max-seq-len `
    --worker-arg 2048 `
    --worker-arg --warmup-synthesis `
    --worker-arg --warmup-language `
    --worker-arg English `
    --worker-arg --warmup-speaker `
    --worker-arg ryan `
    --startup-timeout-ms 1200000 `
    --request-timeout-ms 900000 `
    --warmups 0 `
    --requests 5 `
    --text "This is a faster backend latency benchmark." `
    --language English `
    --speaker ryan `
    > docs\benchmark-artifacts\rtx4090-2026-07-22\latency-ladder-portable-cpp-faster-customvoice-chunk8-r5.json `
    2> docs\benchmark-artifacts\rtx4090-2026-07-22\latency-ladder-portable-cpp-faster-customvoice-chunk8-r5.stderr.txt
```

Paired restart source-worker benchmark with runtime fingerprint:

Source-worker faster backend runs require the local faster source on
`PYTHONPATH` unless it has been installed into the selected environment:

```powershell
$env:PYTHONPATH = "worker/src;tests/python;external/python/Qwen3-TTS-streaming;C:\_repoz\faster-qwen3-tts-v032-stack112-clean"
```

```powershell
$out = .\.venv-packaging\Scripts\python.exe -B tests\python\benchmark_packaged_worker_restart.py `
    .\.venv-packaging\Scripts\python.exe `
    --worker-prefix-arg=-B `
    --worker-prefix-arg=-P `
    --worker-prefix-arg=-s `
    --worker-prefix-arg=-m `
    --worker-prefix-arg=qwen_tts_bridge_worker `
    --engine qwen `
    --model-path models\Qwen3-TTS-12Hz-0.6B-CustomVoice `
    --runtime-backend faster `
    --device cuda `
    --dtype auto `
    --emit-every-frames 8 `
    --max-seq-len 2048 `
    --warmup-synthesis `
    --warmup-synthesis-passes 2 `
    --warmup-text "This is a faster backend latency benchmark." `
    --warmup-language English `
    --warmup-speaker ryan `
    --runs 50 `
    --requests-per-run 4 `
    --seed 4242 `
    --text "This is a faster backend latency benchmark." `
    --language English `
    --speaker ryan `
    --timeout-seconds 1200
[IO.File]::WriteAllText(
    "docs\benchmark-artifacts\rtx4090-2026-07-22\paired-restart-source-worker-faster-customvoice-chunk8-r50x4-seed4242.json",
    ($out -join "`n"),
    [System.Text.UTF8Encoding]::new($false)
)
```

Bounded second warmup pass probe:

```powershell
$out = .\.venv-packaging\Scripts\python.exe -B tests\python\benchmark_packaged_worker_restart.py `
    .\.venv-packaging\Scripts\python.exe `
    --worker-prefix-arg=-B `
    --worker-prefix-arg=-P `
    --worker-prefix-arg=-s `
    --worker-prefix-arg=-m `
    --worker-prefix-arg=qwen_tts_bridge_worker `
    --engine qwen `
    --model-path models\Qwen3-TTS-12Hz-0.6B-CustomVoice `
    --runtime-backend faster `
    --device cuda `
    --dtype auto `
    --emit-every-frames 8 `
    --max-seq-len 2048 `
    --warmup-synthesis `
    --warmup-synthesis-passes 2 `
    --warmup-unbounded-passes 1 `
    --warmup-max-output-chunks 2 `
    --warmup-text "This is a faster backend latency benchmark." `
    --warmup-language English `
    --warmup-speaker ryan `
    --runs 20 `
    --requests-per-run 4 `
    --seed 4242 `
    --text "This is a faster backend latency benchmark." `
    --language English `
    --speaker ryan `
    --timeout-seconds 1200
[IO.File]::WriteAllText(
    "docs\benchmark-artifacts\rtx4090-2026-07-22\paired-restart-source-worker-faster-customvoice-chunk8-r20x4-seed4242-capture-full-bounded2.json",
    ($out -join "`n"),
    [System.Text.UTF8Encoding]::new($false)
)
```

CPU-affinity paired restart probes:

```powershell
foreach ($entry in @(
    @{ Affinity = "0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21"; Suffix = "affinity-0-21" },
    @{ Affinity = "22,23,24,25,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,41,42,43"; Suffix = "affinity-22-43" }
)) {
    $out = .\.venv-packaging\Scripts\python.exe -B tests\python\benchmark_packaged_worker_restart.py `
        .\.venv-packaging\Scripts\python.exe `
        --worker-prefix-arg=-B `
        --worker-prefix-arg=-P `
        --worker-prefix-arg=-s `
        --worker-prefix-arg=-m `
        --worker-prefix-arg=qwen_tts_bridge_worker `
        --engine qwen `
        --model-path models\Qwen3-TTS-12Hz-0.6B-CustomVoice `
        --runtime-backend faster `
        --device cuda `
        --dtype auto `
        --emit-every-frames 8 `
        --max-seq-len 2048 `
        --warmup-synthesis `
        --warmup-synthesis-passes 2 `
        --warmup-text "This is a faster backend latency benchmark." `
        --warmup-language English `
        --warmup-speaker ryan `
        --runs 20 `
        --requests-per-run 4 `
        --seed 4242 `
        --cpu-affinity $entry.Affinity `
        --text "This is a faster backend latency benchmark." `
        --language English `
        --speaker ryan `
        --timeout-seconds 1200
    [IO.File]::WriteAllText(
        "docs\benchmark-artifacts\rtx4090-2026-07-22\paired-restart-source-worker-faster-customvoice-chunk8-r20x4-seed4242-$($entry.Suffix).json",
        ($out -join "`n"),
        [System.Text.UTF8Encoding]::new($false)
    )
}
```

First-frame pipeline probe:

```powershell
$oldPyPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = "worker/src;tests/python;external/python/Qwen3-TTS-streaming;C:\_repoz\faster-qwen3-tts-v032-stack112-clean"
    $out = .\.venv-packaging\Scripts\python.exe -B tests\python\benchmark_packaged_worker_restart.py `
        .\.venv-packaging\Scripts\python.exe `
        --worker-prefix-arg=-B `
        --worker-prefix-arg=-P `
        --worker-prefix-arg=-s `
        --worker-prefix-arg=-m `
        --worker-prefix-arg=qwen_tts_bridge_worker `
        --engine qwen `
        --model-path models\Qwen3-TTS-12Hz-0.6B-CustomVoice `
        --runtime-backend faster `
        --device cuda `
        --dtype auto `
        --emit-every-frames 8 `
        --max-seq-len 2048 `
        --warmup-synthesis `
        --warmup-synthesis-passes 2 `
        --warmup-text "This is a faster backend latency benchmark." `
        --warmup-language English `
        --warmup-speaker ryan `
        --runs 5 `
        --requests-per-run 4 `
        --seed 4242 `
        --text "This is a faster backend latency benchmark." `
        --language English `
        --speaker ryan `
        --timeout-seconds 1200
    [IO.File]::WriteAllText(
        "docs\benchmark-artifacts\rtx4090-2026-07-22\paired-restart-source-worker-faster-customvoice-chunk8-r5x4-seed4242-pipeline.json",
        ($out -join "`n"),
        [System.Text.UTF8Encoding]::new($false)
    )
}
finally {
    $env:PYTHONPATH = $oldPyPath
}
```

## 2026-07-27 Raw-vs-Strict Context Gate Correction

The first context gate showed that the diagnostic strict SDPA island was not a
valid raw eager reference: it missed production SDPA `is_causal` and GQA
dispatch behavior. The strict SDPA custom op was updated to match the
Transformers wrapper path for the all-valid prefill case.

```powershell
$env:PYTHONPATH = "C:\_repoz\faster-qwen3-tts-v032-stack112-clean;C:\_repoz\qwen3-tts-bridge-cpp\external\python\Qwen3-TTS-streaming"
$env:PYTHONDONTWRITEBYTECODE = "1"

.\.venv-packaging\Scripts\python.exe scripts\qwen_prefill_context_gate.py `
  --model models\Qwen3-TTS-12Hz-0.6B-CustomVoice `
  --text "I am your robot, I am your worker." `
  --language English `
  --speaker ryan `
  --dtype bfloat16 `
  --attn-implementation sdpa `
  --force-talker-attn-implementation sdpa `
  --trace-attention-calls `
  --prefill-mask-mode auto `
  --include-component-ablation `
  --skip-generation `
  --repeats 1 `
  --max-new-tokens 64 `
  --chunk-size 8 `
  --device-profile rtx4090 `
  --output docs\benchmark-artifacts\rtx4090-2026-07-22\context-gate\bf16-sdpa-strict-component-ablation-prefill-after-causal-gqa-r1.json

.\.venv-packaging\Scripts\python.exe scripts\qwen_prefill_context_gate.py `
  --model models\Qwen3-TTS-12Hz-0.6B-CustomVoice `
  --text "I am your robot, I am your worker." `
  --language English `
  --speaker ryan `
  --dtype bfloat16 `
  --attn-implementation sdpa `
  --force-talker-attn-implementation sdpa `
  --trace-attention-calls `
  --prefill-mask-mode auto `
  --include-reduce-overhead `
  --repeats 1 `
  --max-new-tokens 64 `
  --chunk-size 8 `
  --device-profile rtx4090 `
  --output docs\benchmark-artifacts\rtx4090-2026-07-22\context-gate\bf16-sdpa-raw-strict-inductor-reduce-after-causal-gqa-r1.json

.\.venv-packaging\Scripts\python.exe scripts\qwen_prefill_context_gate.py `
  --model models\Qwen3-TTS-12Hz-0.6B-CustomVoice `
  --text "I am your robot, I am your worker." `
  --language English `
  --speaker ryan `
  --dtype bfloat16 `
  --attn-implementation sdpa `
  --force-talker-attn-implementation sdpa `
  --trace-attention-calls `
  --prefill-mask-mode auto `
  --include-reduce-overhead `
  --repeats 1 `
  --max-new-tokens 256 `
  --chunk-size 8 `
  --device-profile rtx4090 `
  --output docs\benchmark-artifacts\rtx4090-2026-07-22\context-gate\bf16-sdpa-raw-strict-inductor-reduce-eos-after-causal-gqa-r1.json

.\.venv-packaging\Scripts\python.exe scripts\qwen_prefill_context_gate.py `
  --model models\Qwen3-TTS-12Hz-0.6B-CustomVoice `
  --text "Я твой робот, я твой работник." `
  --language Russian `
  --speaker ryan `
  --dtype bfloat16 `
  --attn-implementation sdpa `
  --force-talker-attn-implementation sdpa `
  --trace-attention-calls `
  --prefill-mask-mode auto `
  --include-reduce-overhead `
  --repeats 1 `
  --max-new-tokens 128 `
  --chunk-size 8 `
  --device-profile rtx4090 `
  --output docs\benchmark-artifacts\rtx4090-2026-07-22\context-gate\semantic-russian-quote-bf16-sdpa-after-causal-gqa-r1.json

.\.venv-packaging\Scripts\python.exe scripts\qwen_prefill_context_gate.py `
  --model models\Qwen3-TTS-12Hz-0.6B-CustomVoice `
  --text "The machine speaks softly and keeps perfect time." `
  --language English `
  --speaker ryan `
  --instruction "Speak softly and steadily." `
  --dtype bfloat16 `
  --attn-implementation sdpa `
  --force-talker-attn-implementation sdpa `
  --trace-attention-calls `
  --prefill-mask-mode auto `
  --include-reduce-overhead `
  --repeats 1 `
  --max-new-tokens 128 `
  --chunk-size 8 `
  --device-profile rtx4090 `
  --output docs\benchmark-artifacts\rtx4090-2026-07-22\context-gate\semantic-english-instruction-bf16-sdpa-after-causal-gqa-r1.json
```

Results:

```text
bf16-sdpa-strict-component-ablation-prefill-r1.json
  before causal/GQA fix: strict_sdpa_eager logits_last max_abs 19.828125
bf16-sdpa-strict-component-ablation-prefill-after-causal-r1.json
  after causal fix only: strict_sdpa_eager logits_last max_abs 0.21875
bf16-sdpa-strict-component-ablation-prefill-after-causal-gqa-r1.json
  after causal+GQA fix: all component ablations logits_last max_abs 0.0
bf16-sdpa-raw-strict-inductor-reduce-after-causal-gqa-r1.json
  raw eager, strict eager, strict Inductor default, and strict reduce-overhead all match; stop_reason=max_new_tokens
bf16-sdpa-raw-strict-inductor-reduce-eos-after-causal-gqa-r1.json
  same A/B/C/D gate passes with true EOS termination
semantic-russian-quote-bf16-sdpa-after-causal-gqa-r1.json
  Russian/Unicode prompt passes; stop_reason=max_new_tokens
semantic-english-instruction-bf16-sdpa-after-causal-gqa-r1.json
  instruction prompt passes; both paths stop short_without_eos
```

Artifact hashes:

```text
context-gate/bf16-sdpa-raw-strict-inductor-reduce-r1.json SHA256: 09dca329e1407c868953aa2d7a7194888a45e969da7ab7f1e253e8c6b17b12f9
context-gate/bf16-sdpa-strict-component-ablation-prefill-r1.json SHA256: fdcf936cdee03b57b616e0f79dd96b5fcb7cc6c5028ee1fd6adb8bce69c4f71f
context-gate/bf16-sdpa-strict-component-ablation-prefill-after-causal-r1.json SHA256: 8e4a23b05a73e4d798ea8f1c14c8d59f8c6b9ee10e76b6948adf337634de69bf
context-gate/bf16-sdpa-strict-component-ablation-prefill-after-causal-gqa-r1.json SHA256: b7b04d542c9f2f0f61b7d469fc4cb7f97ac01127691e2e19598a56fc1c0c68cb
context-gate/bf16-sdpa-raw-strict-inductor-reduce-after-causal-gqa-r1.json SHA256: 0b58349c173a6857bb82cd29e57c06e0858491ca7d972bd34050363456c26462
context-gate/bf16-sdpa-raw-strict-inductor-reduce-eos-after-causal-gqa-r1.json SHA256: 74800d82e5eccdfefe9989f36926ee2f80bd42f5a13c9cfc07d08a3a483937fe
context-gate/semantic-russian-quote-bf16-sdpa-after-causal-gqa-r1.json SHA256: 47a863111ad7ba6762511c7a950e500601321a9505b08fd5f39601a67c68d380
context-gate/semantic-english-instruction-bf16-sdpa-after-causal-gqa-r1.json SHA256: 60c0d80c57cfca3f24b28444d4efd812b7aae347ecd3e44162d98a5cfe1392f0
```

Verification:

```text
.venv-faster-qwen/Scripts/python.exe -m py_compile scripts/qwen_prefill_compile_parity.py scripts/qwen_prefill_context_gate.py
scripts/check-python.ps1 -UseVenv -VenvPath .venv
  passed: 154 tests, 2 skipped
ctest --test-dir build/default --output-on-failure
  first run: stdio_transport_test transient ready wait failure
ctest --test-dir build/default -R stdio_transport_test --output-on-failure -V
  passed
ctest --test-dir build/default --output-on-failure
  passed: 9/9 tests
ctest --test-dir build/default -R stdio_transport_test --output-on-failure --repeat until-fail:20
  passed: 20/20 repetitions
git diff --check
  passed; only CRLF conversion warnings for touched text files
```

## Mask Contract Hardening And Inductor RMS/RoPE Diagnostics

Safe production gate after replacing bare `all_valid=true` with mask
provenance and adding Qwen fail-closed skip guards:

```powershell
$env:PYTHONPATH = "C:\_repoz\faster-qwen3-tts-v032-stack112-clean;C:\_repoz\qwen3-tts-bridge-cpp\external\python\Qwen3-TTS-streaming"
$env:PYTHONDONTWRITEBYTECODE = "1"

.\.venv-packaging\Scripts\python.exe scripts\qwen_prefill_compile_parity.py `
    --model models\Qwen3-TTS-12Hz-0.6B-CustomVoice `
    --text "I am your robot, I am your worker." `
    --language English `
    --speaker ryan `
    --dtype bfloat16 `
    --attn-implementation eager `
    --backend eager `
    --backend compile_backend_eager `
    --backend compile_backend_aot_eager `
    --repeats 2 `
    --max-new-tokens 64 `
    --chunk-size 8 `
    --device-profile rtx4090 `
    --output docs\benchmark-artifacts\rtx4090-2026-07-22\production-mask-contract-hardening\bf16-safe-compile-ladder-r2.json
```

Inductor remains blocked under the same hardened mask contract:

```powershell
.\.venv-packaging\Scripts\python.exe scripts\qwen_prefill_compile_parity.py `
    --model models\Qwen3-TTS-12Hz-0.6B-CustomVoice `
    --text "I am your robot, I am your worker." `
    --language English `
    --speaker ryan `
    --dtype bfloat16 `
    --attn-implementation eager `
    --backend eager `
    --backend compile_inductor_default `
    --repeats 1 `
    --max-new-tokens 64 `
    --chunk-size 8 `
    --device-profile rtx4090 `
    --output docs\benchmark-artifacts\rtx4090-2026-07-22\production-mask-contract-hardening\bf16-inductor-default-r1.json
```

Layer-0 Inductor diagnostics used:

```powershell
.\.venv-packaging\Scripts\python.exe scripts\qwen_prefill_attention_micro_parity.py `
    --model models\Qwen3-TTS-12Hz-0.6B-CustomVoice `
    --text "I am your robot, I am your worker." `
    --language English `
    --speaker ryan `
    --dtype bfloat16 `
    --attn-implementation eager `
    --right-backend compile_inductor_default `
    --force-mask-skip-during-compile `
    --layer-norm-variant f_rms_norm `
    --qk-norm-variant f_rms_norm `
    --rope-variant fp32 `
    --device-profile rtx4090 `
    --output docs\benchmark-artifacts\rtx4090-2026-07-22\inductor-rope-variants\bf16-layer0-all-f_rms_norm-rope-fp32.json
```

The `--qk-norm-variant` sweep covered `current`, `input_contiguous`,
`output_contiguous`, `manual_fp32`, `f_rms_norm`, and `aten_rms_norm`. The
`--layer-norm-variant` all-RMS sweep covered `f_rms_norm` and `aten_rms_norm`.
The RoPE sweep covered `input_contiguous`, `output_contiguous`, and `fp32`.

Artifact hashes:

```text
production-mask-contract-hardening/bf16-compile-backend-eager-r1.json SHA256: 3504bad9a71824320f409f1a3ab085316c0c6a0369b810edfee5a56f04b5e579
production-mask-contract-hardening/bf16-inductor-default-r1.json SHA256: 4059d46074ebf7c73ae2b110b2e64d9847730fc639fdc9e42334819d41c3499c
production-mask-contract-hardening/bf16-safe-compile-ladder-r2.json SHA256: 539bdb22335dd64787e423e8b36e0d71599ee5ff500e470ec9e62a9ea58faf29
inductor-qk-norm-variants/bf16-layer0-aten_rms_norm.json SHA256: 1190532b9d55f17dd2ce0ad74d54cc2c3e5989144403024259e9b1a2c374f51a
inductor-qk-norm-variants/bf16-layer0-current.json SHA256: 464d4c7775701dd5c485dbefa95f3933f175350fa2164fcdd78180baac64eeb7
inductor-qk-norm-variants/bf16-layer0-f_rms_norm.json SHA256: 9367ff4a4117cb31da8153a9af3082bbb37485f8d23b7a977ca5b22a0902c5b8
inductor-qk-norm-variants/bf16-layer0-input_contiguous.json SHA256: f9a686721c57960f62d4bb2ffc5d5f2c9608da2b25eb0c23e9a9eeb2435f9b38
inductor-qk-norm-variants/bf16-layer0-manual_fp32.json SHA256: 4985d5afa5fc6b25a7ee7e6be2709ebfe7ced2534e37d7e0c97fcc6c20fec8da
inductor-qk-norm-variants/bf16-layer0-output_contiguous.json SHA256: 0c1075d29e86de9633304881804ee24082278d82ea0a3434bb7230d2b8d29322
inductor-rms-norm-variants/bf16-layer0-all-aten_rms_norm.json SHA256: 62523578fe5d97f961cb17f0e56ced41324047ffc8652389c0497cc22edf0022
inductor-rms-norm-variants/bf16-layer0-all-f_rms_norm.json SHA256: 94a4468c407ec0f8876733c46c26e246bee5944c6197caf218602b1559c17714
inductor-rope-variants/bf16-layer0-all-f_rms_norm-rope-fp32.json SHA256: d328f0431ab266701bbfb5593feafed8640b01b92a23cb73d97f96b65a4e2f23
inductor-rope-variants/bf16-layer0-all-f_rms_norm-rope-input_contiguous.json SHA256: e63fe44a8cc97b28e01979cb9f570127c37cc6a4508e2a7dff291b8fb05d573c
inductor-rope-variants/bf16-layer0-all-f_rms_norm-rope-output_contiguous.json SHA256: 8ac4df7fa6dd08509ec02ee7352ac2783893e889eb955561d653b4546966c166
faster-qwen-mask-contract-hardening-patch/0001-fix-prefill-harden-mask-skip-selection.patch SHA256: ef2d77bb01af3481bf1604c82464f894fe268d5263e8036cd7c5648b7b77bd67
faster-qwen-mask-contract-hardening-patch/faster-qwen-prefill-compile-through-70bfea4.bundle SHA256: ea07e795fb92f45f2a66f4643863db2e601757158b090706f5adb3fe0140bfd2
qwen-mask-contract-hardening-patch/0001-fix-talker-reject-unsafe-prefill-mask-skips.patch SHA256: 3c144938e710cca661df5cc9b6c427026d3847b6ec2c6407e2ea090ea91b7e96
```

## Verified Mask Contract, SDPA Gate, And RoPE Repro

The final mask-contract gate used explicit and verified-skip runs:

```powershell
$env:PYTHONPATH = "C:\_repoz\faster-qwen3-tts-v032-stack112-clean;C:\_repoz\qwen3-tts-bridge-cpp\external\python\Qwen3-TTS-streaming"
$env:PYTHONDONTWRITEBYTECODE = "1"

.\.venv-packaging\Scripts\python.exe scripts\qwen_prefill_compile_parity.py `
    --model models\Qwen3-TTS-12Hz-0.6B-CustomVoice `
    --text "I am your robot, I am your worker." `
    --language English `
    --speaker ryan `
    --dtype bfloat16 `
    --attn-implementation sdpa `
    --prefill-mask-mode skip `
    --backend eager `
    --backend compile_backend_eager `
    --repeats 1 `
    --max-new-tokens 64 `
    --chunk-size 8 `
    --device-profile rtx4090 `
    --output docs\benchmark-artifacts\rtx4090-2026-07-22\mask-contract-sdpa-gate\bf16-sdpa-skip-compile-backend-eager-r1.json
```

Standalone RoPE repro:

```powershell
.\.venv-packaging\Scripts\python.exe scripts\qwen_rope_inductor_repro.py `
    --model models\Qwen3-TTS-12Hz-0.6B-CustomVoice `
    --text "I am your robot, I am your worker." `
    --language English `
    --speaker ryan `
    --dtype bfloat16 `
    --attn-implementation sdpa `
    --compute-dtype input `
    --device-profile rtx4090 `
    --output docs\benchmark-artifacts\rtx4090-2026-07-22\rope-inductor-repro\bf16-rope-repro-input.json
```

Compatibility graph-break matrix:

```powershell
.\.venv-packaging\Scripts\python.exe scripts\qwen_prefill_compile_parity.py `
    --model models\Qwen3-TTS-12Hz-0.6B-CustomVoice `
    --text "I am your robot, I am your worker." `
    --language English `
    --speaker ryan `
    --dtype bfloat16 `
    --attn-implementation sdpa `
    --prefill-mask-mode skip `
    --backend eager `
    --backend compile_inductor_graphbreak `
    --disable-compile-rmsnorm `
    --disable-compile-rope `
    --repeats 1 `
    --skip-generation `
    --device-profile rtx4090 `
    --output docs\benchmark-artifacts\rtx4090-2026-07-22\inductor-eager-islands\bf16-prefill-rms-rope-r1.json
```

Automatic accuracy minifier attempt:

```powershell
$env:TORCHDYNAMO_REPRO_AFTER = "dynamo"
$env:TORCHDYNAMO_REPRO_LEVEL = "4"
.\.venv-packaging\Scripts\python.exe scripts\qwen_rope_inductor_repro.py `
    --model models\Qwen3-TTS-12Hz-0.6B-CustomVoice `
    --text "I am your robot, I am your worker." `
    --language English `
    --speaker ryan `
    --dtype bfloat16 `
    --attn-implementation sdpa `
    --compute-dtype input `
    --backend compile_inductor_default `
    --device-profile rtx4090 `
    --output docs\benchmark-artifacts\rtx4090-2026-07-22\rope-inductor-repro\bf16-rope-repro-minifier-attempt.json
```

This minifier attempt did not produce a usable launcher; PyTorch failed inside
the minifier path with an internal tensor/list input assertion and shape-guard
error.

Artifact hashes:

```text
mask-contract-sdpa-gate/bf16-sdpa-explicit-compile-backend-eager-r1.json SHA256: ecbcc7f1295b980f7fad7f2ac128edaf180cda1f2ec6c9ad41fa2fec0b2ff1d8
mask-contract-sdpa-gate/bf16-sdpa-skip-compile-backend-eager-r1.json SHA256: 821463c100f2888ab9b5ae6828bf0aa1e30d20219bdb1e832216033a1c52fe58
rope-inductor-repro/bf16-rope-repro-input.json SHA256: d2ee6b009d4d524a1c8644960f94f4105fba87d55edeb3b6811e7437bfa772f6
rope-inductor-repro/fp32-rope-repro.json SHA256: 21a47f6646f87854ba48f070f4bc37c1e2930aab79020f8df37600e805160726
inductor-eager-islands/bf16-prefill-baseline-r1.json SHA256: bffafb470f77b9f208c4760bb8958ca499431804a88715cd09565f18e8263aaa
inductor-eager-islands/bf16-prefill-rms-r1.json SHA256: c0aa13aabc966977937e26a31eafa4a8174d2b87770f5e1e4db6b593b5ffcba9
inductor-eager-islands/bf16-prefill-rms-rope-islands-smoke.json SHA256: b44f6ec7eb842773990a4c77a9a4131dd70112e50166e634d206a97b00126576
inductor-eager-islands/bf16-prefill-rms-rope-r1.json SHA256: b44f6ec7eb842773990a4c77a9a4131dd70112e50166e634d206a97b00126576
faster-qwen-verified-mask-and-graphbreak-patch/0001-fix-prefill-require-verified-mask-skip-inputs.patch SHA256: 994223679175f2962e3c4b534e9dfb5ca7bf938520b737c64dca5a2032ea0116
faster-qwen-verified-mask-and-graphbreak-patch/0002-test-prefill-add-graphbreak-compile-backend.patch SHA256: 298a1cd7913a193f36ecda1995df6725ca0d728b3eb9d338c456973c57bcdfe7
faster-qwen-verified-mask-and-graphbreak-patch/faster-qwen-prefill-compile-through-8791fcd.bundle SHA256: 82fd2ac837e6cbee0715731d8bcb71a2397a6c3c7d855990e34cfb6cc84de714
qwen-verified-mask-patch/0001-fix-talker-require-absent-mask-for-verified-skips.patch SHA256: 01569aeff9d69c085335a741df77b99169f55ec987be285926a5499fe5f4497d
```

Fail-closed greedy predictor patch artifacts:

```powershell
$dir = "docs\benchmark-artifacts\rtx4090-2026-07-22\faster-qwen-fail-closed-greedy-predictor-patch"
New-Item -ItemType Directory -Force -Path $dir | Out-Null
git -C C:\_repoz\faster-qwen3-tts-v032-stack112-clean format-patch `
    -o (Resolve-Path $dir) 71fa0fd..9f1c801
git -C C:\_repoz\faster-qwen3-tts-v032-stack112-clean bundle create `
    (Join-Path (Resolve-Path $dir) "faster-qwen-prefill-compile-exact-shape-through-9f1c801.bundle") `
    prefill-compile-exact-shape ^71fa0fd
```

Frame-accounting parity controls:

```powershell
$env:PYTHONPATH = "C:\_repoz\faster-qwen3-tts-v032-stack112-clean;external/python/Qwen3-TTS-streaming"

.\.venv-packaging\Scripts\python.exe scripts\qwen_prefill_compile_parity.py `
    --model models\Qwen3-TTS-12Hz-0.6B-CustomVoice `
    --text "I am your robot, I am your worker." `
    --language English `
    --speaker ryan `
    --dtype bfloat16 `
    --attn-implementation eager `
    --backend eager `
    --backend compile_backend_eager `
    --backend compile_inductor_default `
    --repeats 1 `
    --max-new-tokens 64 `
    --chunk-size 8 `
    --output docs\benchmark-artifacts\rtx4090-2026-07-22\frame-accounting\bf16-ladder-r1.json

.\.venv-packaging\Scripts\python.exe scripts\qwen_prefill_compile_parity.py `
    --model models\Qwen3-TTS-12Hz-0.6B-CustomVoice `
    --text "I am your robot, I am your worker." `
    --language English `
    --speaker ryan `
    --dtype float32 `
    --attn-implementation eager `
    --backend eager `
    --backend compile_backend_eager `
    --backend compile_inductor_default `
    --repeats 1 `
    --max-new-tokens 64 `
    --chunk-size 8 `
    --disable-tf32 `
    --matmul-precision highest `
    --output docs\benchmark-artifacts\rtx4090-2026-07-22\frame-accounting\fp32-ladder-r1.json
```

Layer-0 attention micro-bisect and FP32-island controls:

```powershell
$env:PYTHONPATH = "C:\_repoz\faster-qwen3-tts-v032-stack112-clean;external/python/Qwen3-TTS-streaming"

.\.venv-packaging\Scripts\python.exe scripts\qwen_prefill_attention_micro_parity.py `
    --model models\Qwen3-TTS-12Hz-0.6B-CustomVoice `
    --text "I am your robot, I am your worker." `
    --language English `
    --speaker ryan `
    --dtype bfloat16 `
    --attn-implementation eager `
    --right-backend compile_backend_eager `
    --checkpoint scores `
    --output docs\benchmark-artifacts\rtx4090-2026-07-22\attention-micro-bisect\bf16-layer0-attention-scores-only-compile-backend-eager.json

.\.venv-packaging\Scripts\python.exe scripts\qwen_prefill_attention_micro_parity.py `
    --model models\Qwen3-TTS-12Hz-0.6B-CustomVoice `
    --text "I am your robot, I am your worker." `
    --language English `
    --speaker ryan `
    --dtype bfloat16 `
    --attn-implementation eager `
    --right-backend compile_backend_eager `
    --checkpoint softmax_probs `
    --output docs\benchmark-artifacts\rtx4090-2026-07-22\attention-micro-bisect\bf16-layer0-attention-softmax-only-compile-backend-eager.json

.\.venv-packaging\Scripts\python.exe scripts\qwen_prefill_attention_micro_parity.py `
    --model models\Qwen3-TTS-12Hz-0.6B-CustomVoice `
    --text "I am your robot, I am your worker." `
    --language English `
    --speaker ryan `
    --dtype bfloat16 `
    --attn-implementation eager `
    --right-backend compile_backend_eager `
    --checkpoint scores `
    --checkpoint softmax_probs `
    --checkpoint attention_context `
    --checkpoint o_proj_input `
    --checkpoint o_proj_output `
    --attention-core-fp32 `
    --output docs\benchmark-artifacts\rtx4090-2026-07-22\attention-micro-bisect\bf16-attention-core-fp32-selected-compile-backend-eager.json
```

Transport stress:

```powershell
ctest --test-dir build\default -R stdio_transport_test --repeat until-fail:100 --output-on-failure
```

Result: `100/100` iterations passed in `449.94 s`.

New artifact hashes:

```text
frame-accounting/bf16-ladder-r1.json SHA256: 074c6b4c8950cb9d8943c6662486f6e838544a69b1c06633ec0e65471ab95ed1
frame-accounting/fp32-ladder-r1.json SHA256: 26a7026dded548be7ae06875dcfa6b99942f0d8364ec457f4710235e5f934364
attention-micro-bisect/bf16-attention-core-fp32-selected-compile-backend-eager.json SHA256: 3e798ae67f0804adc3186f1675f1e5427fe65c28f90ce03554e8c90e0ee7ea69
attention-micro-bisect/bf16-layer0-attention-scores-only-compile-backend-eager.json SHA256: cc658fe50ced6959c97a2abf9951ff3dae158ac36a65abf315758a7bbfa7efda
attention-micro-bisect/bf16-layer0-attention-selected-compile-backend-eager.json SHA256: 8a04cab465eb6d5808982efdec623bbb061952df9e696f1d797dfe44db04a750
attention-micro-bisect/bf16-layer0-attention-softmax-only-compile-backend-eager.json SHA256: 34aba3c672ae2a6b55bc614111b8ef11feb32c63ab5b974112d9f166f435fc71
attention-micro-bisect/fp32-layer0-attention-selected-compile-backend-eager.json SHA256: e3160b83064d3e340060c25400d1ec2d6396c80189bbf110a9bb22c4ef84e532
attention-micro-bisect/fp32-layer0-attention-softmax-only-compile-backend-eager.json SHA256: 581fd1d5f557519ad9a2b9d8ff3cd6bb9fc4b5bfa86bb545aad1f014df8f4058
attention-micro-bisect/materialized-scores-softmax-control.json SHA256: 65537f107d65885ee2f006f1d6c09f3207e173aa92acac02da64ede4768cc406
faster-qwen-fail-closed-greedy-predictor-patch/0001-feat-prefill-add-exact-shape-compile-backend-switch.patch SHA256: e49d105869d39c0aa95996878a4d797229e4473d064663b825cdcce11a24c2b5
faster-qwen-fail-closed-greedy-predictor-patch/0002-test-prefill-add-diagnostic-compile-backends.patch SHA256: 4bbd1df46fa823748886b34b46b776ee15319bfa1efd4a19412bb04d4ba37762
faster-qwen-fail-closed-greedy-predictor-patch/0003-fix-predictor-honor-greedy-mode-for-residual-codeboo.patch SHA256: 0523270f8158dd5d4b6e5e96f22fffe2e9486bff41fa3546c25e1efa1cfe2087
faster-qwen-fail-closed-greedy-predictor-patch/0004-fix-predictor-fail-closed-without-greedy-graph.patch SHA256: ece402e6a01f079de8248de62adf6d01ed95006eab23783b7f58086b9f22ddb2
faster-qwen-fail-closed-greedy-predictor-patch/faster-qwen-prefill-compile-exact-shape-through-9f1c801.bundle SHA256: 3294b4a1d438bed688df15223968249ca58e8ef996eecdd3de11ef425e28163f
```

Single-pass bisection and mask-skip compile fix:

```powershell
$env:PYTHONPATH = "C:\_repoz\faster-qwen3-tts-v032-stack112-clean;external/python/Qwen3-TTS-streaming"

.\.venv-packaging\Scripts\python.exe scripts\qwen_prefill_attention_micro_parity.py `
    --model models\Qwen3-TTS-12Hz-0.6B-CustomVoice `
    --text "I am your robot, I am your worker." `
    --language English `
    --speaker ryan `
    --dtype bfloat16 `
    --attn-implementation eager `
    --right-backend compile_backend_eager `
    --checkpoint scores `
    --checkpoint causal_mask `
    --checkpoint scores_masked `
    --checkpoint softmax_probs `
    --checkpoint o_proj_output `
    --output docs\benchmark-artifacts\rtx4090-2026-07-22\attention-single-pass-bisect\bf16-layer0-mask-focus-v2-compile-backend-eager.json

.\.venv-packaging\Scripts\python.exe scripts\qwen_prefill_attention_micro_parity.py `
    --model models\Qwen3-TTS-12Hz-0.6B-CustomVoice `
    --text "I am your robot, I am your worker." `
    --language English `
    --speaker ryan `
    --dtype bfloat16 `
    --attn-implementation eager `
    --right-backend compile_inductor_default `
    --checkpoint scores `
    --checkpoint causal_mask `
    --checkpoint scores_masked `
    --checkpoint softmax_probs `
    --checkpoint attention_context `
    --checkpoint o_proj_output `
    --checkpoint layer_output `
    --force-mask-skip-during-compile `
    --output docs\benchmark-artifacts\rtx4090-2026-07-22\attention-single-pass-bisect\bf16-layer0-inductor-force-mask-skip.json

.\.venv-packaging\Scripts\python.exe scripts\qwen_prefill_compile_parity.py `
    --model models\Qwen3-TTS-12Hz-0.6B-CustomVoice `
    --text "I am your robot, I am your worker." `
    --language English `
    --speaker ryan `
    --dtype bfloat16 `
    --attn-implementation eager `
    --backend eager `
    --backend compile_backend_eager `
    --backend compile_backend_aot_eager `
    --backend compile_inductor_default `
    --backend compile_reduce_overhead `
    --repeats 2 `
    --max-new-tokens 64 `
    --chunk-size 8 `
    --output docs\benchmark-artifacts\rtx4090-2026-07-22\mask-skip-compile-fix\bf16-compiled-ladder-r2-v2.json
```

FasterQwen patch artifacts through `2d04337`:

```powershell
$dir = "docs\benchmark-artifacts\rtx4090-2026-07-22\faster-qwen-mask-skip-compile-fix-patch"
New-Item -ItemType Directory -Force -Path $dir | Out-Null
git -C C:\_repoz\faster-qwen3-tts-v032-stack112-clean format-patch `
    -o (Resolve-Path $dir) 71fa0fd..2d04337
git -C C:\_repoz\faster-qwen3-tts-v032-stack112-clean bundle create `
    (Join-Path (Resolve-Path $dir) "faster-qwen-prefill-compile-through-2d04337.bundle") `
    prefill-compile-exact-shape ^71fa0fd
```

Additional artifact hashes:

```text
attention-single-pass-bisect/bf16-layer0-inductor-force-mask-skip.json SHA256: f12e00b0be17afee87b6f12f61a1704b288991f140c1128214de8f136ac46fab
attention-single-pass-bisect/bf16-layer0-mask-focus-v2-compile-backend-eager.json SHA256: 97f9dae768b0725d85a7b1df7e8f6840f1ca617b5549b0d07fbe949a25fc61f8
attention-single-pass-bisect/fp32-layer0-inductor-force-mask-skip.json SHA256: a54686e9f23af53f0966080371004b38d13ec9d8e26f8bd15815720c55ef4ee4
mask-skip-compile-fix/bf16-compile-backend-eager-r1-v2.json SHA256: 0d597fcebe3030da32378934c50cf6a8a7a9c7cc9672d285ff384ac78dbcdfa3
mask-skip-compile-fix/bf16-compiled-ladder-r2-v2.json SHA256: b8b98eb7f6da41bb5e254159e2c5671e58c4aa6e4c6b73e4a9330925ac7ccef3
faster-qwen-mask-skip-compile-fix-patch/0005-fix-prefill-preserve-mask-skip-under-compile.patch SHA256: bad0d99c716060dd5174263bf554e07789c5938ad51eefc0a6c4d45557051e2a
faster-qwen-mask-skip-compile-fix-patch/faster-qwen-prefill-compile-through-2d04337.bundle SHA256: 72cbcee9fe125013f4ab0fa333005d2cf1b725591aeed9bc1a092d64b0b1053d
```

Production explicit mask mode controls:

```powershell
$env:PYTHONPATH = "C:\_repoz\faster-qwen3-tts-v032-stack112-clean;external/python/Qwen3-TTS-streaming"

.\.venv-packaging\Scripts\python.exe scripts\qwen_prefill_compile_parity.py `
    --model models\Qwen3-TTS-12Hz-0.6B-CustomVoice `
    --text "I am your robot, I am your worker." `
    --language English `
    --speaker ryan `
    --dtype bfloat16 `
    --attn-implementation eager `
    --backend eager `
    --backend compile_backend_eager `
    --repeats 1 `
    --max-new-tokens 64 `
    --chunk-size 8 `
    --device-profile rtx4090 `
    --output docs\benchmark-artifacts\rtx4090-2026-07-22\production-mask-mode\bf16-compile-backend-eager-r1.json

.\.venv-packaging\Scripts\python.exe scripts\qwen_prefill_compile_parity.py `
    --model models\Qwen3-TTS-12Hz-0.6B-CustomVoice `
    --text "I am your robot, I am your worker." `
    --language English `
    --speaker ryan `
    --dtype bfloat16 `
    --attn-implementation eager `
    --backend eager `
    --backend compile_backend_eager `
    --backend compile_backend_aot_eager `
    --repeats 2 `
    --max-new-tokens 64 `
    --chunk-size 8 `
    --device-profile rtx4090 `
    --output docs\benchmark-artifacts\rtx4090-2026-07-22\production-mask-mode\bf16-safe-compile-ladder-r2.json
```

Patch artifacts through Qwen `f75125e` and FasterQwen `d515c2d`:

```powershell
$fasterDir = "docs\benchmark-artifacts\rtx4090-2026-07-22\faster-qwen-explicit-mask-mode-patch"
New-Item -ItemType Directory -Force -Path $fasterDir | Out-Null
git -C C:\_repoz\faster-qwen3-tts-v032-stack112-clean format-patch `
    -o (Resolve-Path $fasterDir) 71fa0fd..d515c2d
git -C C:\_repoz\faster-qwen3-tts-v032-stack112-clean bundle create `
    (Join-Path (Resolve-Path $fasterDir) "faster-qwen-prefill-compile-through-d515c2d.bundle") `
    prefill-compile-exact-shape ^71fa0fd

$qwenDir = "docs\benchmark-artifacts\rtx4090-2026-07-22\qwen-explicit-mask-skip-patch"
New-Item -ItemType Directory -Force -Path $qwenDir | Out-Null
git -C external\python\Qwen3-TTS-streaming format-patch `
    -o (Resolve-Path $qwenDir) 25cc588..f75125e
```

Production mask mode artifact hashes:

```text
production-mask-mode/bf16-compile-backend-eager-r1.json SHA256: 957e897815b50f37ebe84d169dea0338061b71716d8b6ba8f723000f90ff7b60
production-mask-mode/bf16-safe-compile-ladder-r2.json SHA256: 6cf3843c92ea2c482180810c5d22b258385a044ebdbe3676b6ef142d43b5dc38
faster-qwen-explicit-mask-mode-patch/0006-fix-prefill-use-explicit-mask-skip-mode.patch SHA256: 57337df4196f95363969258cf93ba50d82090178433549ac0e790cc40b2197e2
faster-qwen-explicit-mask-mode-patch/faster-qwen-prefill-compile-through-d515c2d.bundle SHA256: d7111fc05f5037b43c378f4c1fd7f57f7f6dd6b45702e6d2f97d657c3e3078fd
qwen-explicit-mask-skip-patch/0001-fix-talker-allow-explicit-prefill-mask-skip.patch SHA256: d970b2b23e33506e06e6363f7c529bee22b623b3757605fbe48b623d8f17343b
```

2026-07-24 profile-on/off overhead control:

```powershell
$oldPyPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = "worker/src;tests/python"
    foreach ($profile in @($false, $true)) {
        $name = if ($profile) { "on" } else { "off" }
        $args = @(
            "-B", "tests\python\benchmark_packaged_worker_restart.py",
            ".\.venv-packaging\Scripts\python.exe",
            "--worker-prefix-arg=-B",
            "--worker-prefix-arg=-P",
            "--worker-prefix-arg=-s",
            "--worker-prefix-arg=-m",
            "--worker-prefix-arg=qwen_tts_bridge_worker",
            "--engine", "qwen",
            "--model-path", "models\Qwen3-TTS-12Hz-0.6B-CustomVoice",
            "--runtime-backend", "faster",
            "--device", "cuda",
            "--dtype", "auto",
            "--emit-every-frames", "8",
            "--max-seq-len", "2048",
            "--warmup-synthesis",
            "--warmup-synthesis-passes", "1",
            "--warmup-text", "I am your robot. I am your worker.",
            "--warmup-language", "English",
            "--warmup-speaker", "ryan",
            "--runs", "5",
            "--requests-per-run", "4",
            "--seed", "4242",
            "--seed-mode", "fixed",
            "--warmup-seed", "4242",
            "--text", "I am your robot. I am your worker.",
            "--language", "English",
            "--speaker", "ryan",
            "--partial-output",
            "docs\benchmark-artifacts\rtx4090-2026-07-22\profile-overhead-$name-source-worker-faster-customvoice-chunk8-r5x4.json",
            "--progress-every-runs", "1",
            "--progress-output", "tmp\profile-overhead-$name-progress.txt",
            "--timeout-seconds", "1200"
        )
        if ($profile) {
            $args += "--profile-prefill"
        }
        .\.venv-packaging\Scripts\python.exe @args > "tmp\profile-overhead-$name-stdout.json"
    }
}
finally {
    $env:PYTHONPATH = $oldPyPath
}
```

2026-07-24 small shape matrix, fixed medium warmup vs per-shape warmup:

```powershell
$oldPyPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = "worker/src;tests/python"
    .\.venv-packaging\Scripts\python.exe -B tests\python\benchmark_packaged_worker_restart.py `
        .\.venv-packaging\Scripts\python.exe `
        --worker-prefix-arg=-B `
        --worker-prefix-arg=-P `
        --worker-prefix-arg=-s `
        --worker-prefix-arg=-m `
        --worker-prefix-arg=qwen_tts_bridge_worker `
        --engine qwen `
        --model-path models\Qwen3-TTS-12Hz-0.6B-CustomVoice `
        --runtime-backend faster `
        --device cuda `
        --dtype auto `
        --emit-every-frames 8 `
        --max-seq-len 2048 `
        --warmup-synthesis `
        --warmup-synthesis-passes 1 `
        --warmup-text "I am your robot. I am your worker." `
        --warmup-language English `
        --warmup-speaker ryan `
        --runs 8 `
        --requests-per-run 2 `
        --run-shapes-jsonl docs\benchmark-artifacts\rtx4090-2026-07-22\input-shape-prefill-profile-r2-each-seed20260724.jsonl `
        --seed 4242 `
        --seed-mode fixed `
        --warmup-seed 4242 `
        --profile-prefill `
        --partial-output docs\benchmark-artifacts\rtx4090-2026-07-22\shape-prefill-profile-source-worker-faster-customvoice-chunk8-r8x2-sampling-mediumwarmup.json `
        --progress-every-runs 1 `
        --progress-output tmp\shape-prefill-profile-mediumwarmup-progress.txt `
        --timeout-seconds 1200

    .\.venv-packaging\Scripts\python.exe -B tests\python\benchmark_packaged_worker_restart.py `
        .\.venv-packaging\Scripts\python.exe `
        --worker-prefix-arg=-B `
        --worker-prefix-arg=-P `
        --worker-prefix-arg=-s `
        --worker-prefix-arg=-m `
        --worker-prefix-arg=qwen_tts_bridge_worker `
        --engine qwen `
        --model-path models\Qwen3-TTS-12Hz-0.6B-CustomVoice `
        --runtime-backend faster `
        --device cuda `
        --dtype auto `
        --emit-every-frames 8 `
        --max-seq-len 2048 `
        --warmup-synthesis `
        --warmup-synthesis-passes 1 `
        --warmup-text "I am your robot. I am your worker." `
        --warmup-language English `
        --warmup-speaker ryan `
        --warmup-from-run-shape `
        --runs 8 `
        --requests-per-run 2 `
        --run-shapes-jsonl docs\benchmark-artifacts\rtx4090-2026-07-22\input-shape-prefill-profile-r2-each-seed20260724.jsonl `
        --seed 4242 `
        --seed-mode fixed `
        --warmup-seed 4242 `
        --profile-prefill `
        --partial-output docs\benchmark-artifacts\rtx4090-2026-07-22\shape-prefill-profile-source-worker-faster-customvoice-chunk8-r8x2-sampling-shapewarmup.json `
        --progress-every-runs 1 `
        --progress-output tmp\shape-prefill-profile-shapewarmup-progress.txt `
        --timeout-seconds 1200
}
finally {
    $env:PYTHONPATH = $oldPyPath
}
```

Startup-thread warmup A/B/C:

```powershell
.\.venv-packaging\Scripts\python.exe -m pip install --force-reinstall --no-deps `
    dist\QwenTTSBridge\worker-python\wheels\faster_qwen3_tts-0.3.2-py3-none-any.whl

$oldPyPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = "worker/src;tests/python"
    foreach ($entry in @(
        @{ Mode = "main"; Suffix = "main-startup" },
        @{ Mode = "engine_warmup"; Suffix = "engine-warmup" },
        @{ Mode = "engine_load_warmup"; Suffix = "engine-load-warmup" }
    )) {
        $out = .\.venv-packaging\Scripts\python.exe -B tests\python\benchmark_packaged_worker_restart.py `
            .\.venv-packaging\Scripts\python.exe `
            --worker-prefix-arg=-B `
            --worker-prefix-arg=-P `
            --worker-prefix-arg=-s `
            --worker-prefix-arg=-m `
            --worker-prefix-arg=qwen_tts_bridge_worker `
            --engine qwen `
            --model-path models\Qwen3-TTS-12Hz-0.6B-CustomVoice `
            --runtime-backend faster `
            --device cuda `
            --dtype auto `
            --emit-every-frames 8 `
            --max-seq-len 2048 `
            --warmup-synthesis `
            --warmup-synthesis-passes 2 `
            --warmup-text "This is a faster backend latency benchmark." `
            --warmup-language English `
            --warmup-speaker ryan `
            --engine-startup-mode $entry.Mode `
            --runs 30 `
            --requests-per-run 4 `
            --partial-output "tmp\paired-restart-$($entry.Suffix)-partial.json" `
            --progress-every-runs 1 `
            --progress-output "tmp\paired-restart-$($entry.Suffix)-progress.txt" `
            --seed 4242 `
            --seed-mode fixed `
            --warmup-seed 4242 `
            --text "This is a faster backend latency benchmark." `
            --language English `
            --speaker ryan `
            --timeout-seconds 1200
        [IO.File]::WriteAllText(
            "docs\benchmark-artifacts\rtx4090-2026-07-22\paired-restart-source-worker-faster-customvoice-chunk8-r30x4-seed4242-fixed-$($entry.Suffix).json",
            ($out -join "`n"),
            [System.Text.UTF8Encoding]::new($false)
        )
    }
}
finally {
    $env:PYTHONPATH = $oldPyPath
}
```

Warmup-depth matrix, Qwen `auto -> engine_warmup`:

```powershell
.\.venv-packaging\Scripts\python.exe -m pip install --force-reinstall --no-deps `
    dist\QwenTTSBridge\worker-python\wheels\faster_qwen3_tts-0.3.2-py3-none-any.whl

$oldPyPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = "worker/src;tests/python"
    foreach ($entry in @(
        @{ Suffix = "warmup1full"; Passes = 1; Unbounded = $null; MaxChunks = $null },
        @{ Suffix = "warmup1full-plus1chunk"; Passes = 2; Unbounded = 1; MaxChunks = 1 },
        @{ Suffix = "warmup1full-plus2chunks"; Passes = 2; Unbounded = 1; MaxChunks = 2 },
        @{ Suffix = "warmup2full"; Passes = 2; Unbounded = $null; MaxChunks = $null }
    )) {
        $warmupArgs = @(
            "--warmup-synthesis",
            "--warmup-synthesis-passes", [string]$entry.Passes
        )
        if ($null -ne $entry.Unbounded) {
            $warmupArgs += @("--warmup-unbounded-passes", [string]$entry.Unbounded)
        }
        if ($null -ne $entry.MaxChunks) {
            $warmupArgs += @("--warmup-max-output-chunks", [string]$entry.MaxChunks)
        }

        $out = .\.venv-packaging\Scripts\python.exe -B tests\python\benchmark_packaged_worker_restart.py `
            .\.venv-packaging\Scripts\python.exe `
            --worker-prefix-arg=-B `
            --worker-prefix-arg=-P `
            --worker-prefix-arg=-s `
            --worker-prefix-arg=-m `
            --worker-prefix-arg=qwen_tts_bridge_worker `
            --engine qwen `
            --model-path models\Qwen3-TTS-12Hz-0.6B-CustomVoice `
            --runtime-backend faster `
            --device cuda `
            --dtype auto `
            --emit-every-frames 8 `
            --max-seq-len 2048 `
            @warmupArgs `
            --warmup-text "This is a faster backend latency benchmark." `
            --warmup-language English `
            --warmup-speaker ryan `
            --runs 30 `
            --requests-per-run 4 `
            --partial-output "tmp\paired-restart-auto-$($entry.Suffix)-partial.json" `
            --progress-every-runs 1 `
            --progress-output "tmp\paired-restart-auto-$($entry.Suffix)-progress.txt" `
            --seed 4242 `
            --seed-mode fixed `
            --warmup-seed 4242 `
            --text "This is a faster backend latency benchmark." `
            --language English `
            --speaker ryan `
            --timeout-seconds 1200
        [IO.File]::WriteAllText(
            "docs\benchmark-artifacts\rtx4090-2026-07-22\paired-restart-source-worker-faster-customvoice-chunk8-r30x4-seed4242-auto-$($entry.Suffix).json",
            ($out -join "`n"),
            [System.Text.UTF8Encoding]::new($false)
        )
    }
}
finally {
    $env:PYTHONPATH = $oldPyPath
}
```

Warmup-depth r100 confirmation, Qwen `auto -> engine_warmup`, one full
synthesis warmup:

```powershell
.\.venv-packaging\Scripts\python.exe -m pip install --force-reinstall --no-deps `
    dist\QwenTTSBridge\worker-python\wheels\faster_qwen3_tts-0.3.2-py3-none-any.whl

$oldPyPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = "worker/src;tests/python"
    $out = .\.venv-packaging\Scripts\python.exe -B tests\python\benchmark_packaged_worker_restart.py `
        .\.venv-packaging\Scripts\python.exe `
        --worker-prefix-arg=-B `
        --worker-prefix-arg=-P `
        --worker-prefix-arg=-s `
        --worker-prefix-arg=-m `
        --worker-prefix-arg=qwen_tts_bridge_worker `
        --engine qwen `
        --model-path models\Qwen3-TTS-12Hz-0.6B-CustomVoice `
        --runtime-backend faster `
        --device cuda `
        --dtype auto `
        --emit-every-frames 8 `
        --max-seq-len 2048 `
        --warmup-synthesis `
        --warmup-synthesis-passes 1 `
        --warmup-text "This is a faster backend latency benchmark." `
        --warmup-language English `
        --warmup-speaker ryan `
        --runs 100 `
        --requests-per-run 4 `
        --partial-output tmp\warmup1full-r100-partial.json `
        --progress-every-runs 1 `
        --progress-output tmp\warmup1full-r100-progress.txt `
        --seed 4242 `
        --seed-mode fixed `
        --warmup-seed 4242 `
        --text "This is a faster backend latency benchmark." `
        --language English `
        --speaker ryan `
        --timeout-seconds 1200
    [IO.File]::WriteAllText(
        "docs\benchmark-artifacts\rtx4090-2026-07-22\paired-restart-source-worker-faster-customvoice-chunk8-r100x4-seed4242-auto-warmup1full.json",
        ($out -join "`n"),
        [System.Text.UTF8Encoding]::new($false)
    )
}
finally {
    $env:PYTHONPATH = $oldPyPath
}
```

Warmup-depth varied-seed control, Qwen `auto -> engine_warmup`, one full
synthesis warmup:

```powershell
.\.venv-packaging\Scripts\python.exe -m pip install --force-reinstall --no-deps `
    dist\QwenTTSBridge\worker-python\wheels\faster_qwen3_tts-0.3.2-py3-none-any.whl

$oldPyPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = "worker/src;tests/python"
    $out = .\.venv-packaging\Scripts\python.exe -B tests\python\benchmark_packaged_worker_restart.py `
        .\.venv-packaging\Scripts\python.exe `
        --worker-prefix-arg=-B `
        --worker-prefix-arg=-P `
        --worker-prefix-arg=-s `
        --worker-prefix-arg=-m `
        --worker-prefix-arg=qwen_tts_bridge_worker `
        --engine qwen `
        --model-path models\Qwen3-TTS-12Hz-0.6B-CustomVoice `
        --runtime-backend faster `
        --device cuda `
        --dtype auto `
        --emit-every-frames 8 `
        --max-seq-len 2048 `
        --warmup-synthesis `
        --warmup-synthesis-passes 1 `
        --warmup-text "This is a faster backend latency benchmark." `
        --warmup-language English `
        --warmup-speaker ryan `
        --runs 30 `
        --requests-per-run 4 `
        --partial-output tmp\warmup1full-varseed-r30-partial.json `
        --progress-every-runs 1 `
        --progress-output tmp\warmup1full-varseed-r30-progress.txt `
        --seed 4242 `
        --seed-mode request_id `
        --run-seed-step 1009 `
        --warmup-seed 4242 `
        --run-warmup-seed-step 1009 `
        --text "This is a faster backend latency benchmark." `
        --language English `
        --speaker ryan `
        --timeout-seconds 1200
    [IO.File]::WriteAllText(
        "docs\benchmark-artifacts\rtx4090-2026-07-22\paired-restart-source-worker-faster-customvoice-chunk8-r30x4-varseed4242-step1009-auto-warmup1full.json",
        ($out -join "`n"),
        [System.Text.UTF8Encoding]::new($false)
    )
}
finally {
    $env:PYTHONPATH = $oldPyPath
}
```

Clean varied-seed controls, Qwen `auto -> engine_warmup`, one full synthesis
warmup, fixed seed within each process:

```powershell
$oldPyPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = "worker/src;tests/python"
    foreach ($entry in @(
        @{
            Suffix = "seed4242-step1009-fixed-auto-warmup1full"
            Partial = "tmp\seedA-r100-partial.json"
            Progress = "tmp\seedA-r100-progress.txt"
            RunWarmupSeedStep = 1009
        },
        @{
            Suffix = "seed4242-step1009-warmupseed4242-fixed-auto-warmup1full"
            Partial = "tmp\seedB-r100-partial.json"
            Progress = "tmp\seedB-r100-progress.txt"
            RunWarmupSeedStep = 0
        }
    )) {
        $out = .\.venv-packaging\Scripts\python.exe -B tests\python\benchmark_packaged_worker_restart.py `
            .\.venv-packaging\Scripts\python.exe `
            --worker-prefix-arg=-B `
            --worker-prefix-arg=-P `
            --worker-prefix-arg=-s `
            --worker-prefix-arg=-m `
            --worker-prefix-arg=qwen_tts_bridge_worker `
            --engine qwen `
            --model-path models\Qwen3-TTS-12Hz-0.6B-CustomVoice `
            --runtime-backend faster `
            --device cuda `
            --dtype auto `
            --emit-every-frames 8 `
            --max-seq-len 2048 `
            --warmup-synthesis `
            --warmup-synthesis-passes 1 `
            --warmup-text "This is a faster backend latency benchmark." `
            --warmup-language English `
            --warmup-speaker ryan `
            --runs 100 `
            --requests-per-run 4 `
            --partial-output $entry.Partial `
            --progress-every-runs 1 `
            --progress-output $entry.Progress `
            --seed 4242 `
            --seed-mode fixed `
            --run-seed-step 1009 `
            --warmup-seed 4242 `
            --run-warmup-seed-step $entry.RunWarmupSeedStep `
            --text "This is a faster backend latency benchmark." `
            --language English `
            --speaker ryan `
            --timeout-seconds 1200
        [IO.File]::WriteAllText(
            "docs\benchmark-artifacts\rtx4090-2026-07-22\paired-restart-source-worker-faster-customvoice-chunk8-r100x4-$($entry.Suffix).json",
            ($out -join "`n"),
            [System.Text.UTF8Encoding]::new($false)
        )
    }
}
finally {
    $env:PYTHONPATH = $oldPyPath
}
```

Strict RMSNorm/RoPE Inductor compatibility pass:

```text
faster-qwen3-tts branch: prefill-compile-exact-shape
faster-qwen3-tts safety commit: 9ba25c7
bridge script: scripts/qwen_prefill_compile_parity.py
bridge repros:
  scripts/qwen_rope_inductor_repro.py
  scripts/qwen_rmsnorm_inductor_repro.py
model: models/Qwen3-TTS-12Hz-0.6B-CustomVoice
speaker: ryan
text: I am your robot, I am your worker.
dtype: bfloat16
attn_implementation: sdpa
device_profile: rtx4090
```

Source artifacts:

```text
faster-qwen-compiled-explicit-safety-patch/0001-fix-prefill-reject-compiled-explicit-masks.patch
SHA256: 6f6b207802a14dbf6828d6ffca36d8dc04d27098c022152a1111b2a93f9d301f

faster-qwen-compiled-explicit-safety-patch/faster-qwen-prefill-compile-through-9ba25c7.bundle
SHA256: 436f994a2af207d475a65b8f8076597eb3dd7d1840d7376f628ccce09b43fbfd
```

Updated safety-test source artifacts:

```text
faster-qwen3-tts safety-test commit: 2fd44e0
commit message: test(prefill): cover compiled mask safety matrix

faster-qwen-mask-safety-matrix-patch/0001-fix-prefill-reject-compiled-explicit-masks.patch
SHA256: 854aaea8004bca80ef4c0e5339d1e88b08d2eaf01dcf4bb8a7a91b5538cd2430

faster-qwen-mask-safety-matrix-patch/0002-test-prefill-cover-compiled-mask-safety-matrix.patch
SHA256: 88e54b3a93490d2176d32fc6910c3cdf61e5bc4966ceeb64cc2d72fd7c57c761

faster-qwen-mask-safety-matrix-patch/faster-qwen-prefill-compile-through-2fd44e0.bundle
SHA256: 814e7ad3caf5f3dcbececba8982ed60a1360e3c611bd1e74e1d2efda3e0e525a
```

Safety smoke, expected to fail before model execution:

```powershell
$env:PYTHONPATH='C:\_repoz\faster-qwen3-tts-v032-stack112-clean;C:\_repoz\qwen3-tts-bridge-cpp\external\python\Qwen3-TTS-streaming'
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv-packaging\Scripts\python.exe scripts\qwen_prefill_compile_parity.py `
    --model models\Qwen3-TTS-12Hz-0.6B-CustomVoice `
    --text "I am your robot, I am your worker." `
    --language English `
    --speaker ryan `
    --dtype bfloat16 `
    --attn-implementation sdpa `
    --prefill-mask-mode explicit `
    --backend eager `
    --backend compile_backend_eager `
    --repeats 1 `
    --skip-generation `
    --device-profile rtx4090 `
    --output docs\benchmark-artifacts\rtx4090-2026-07-22\compiled-explicit-safety\should-not-exist.json
```

Expected result:

```text
faster_qwen3_tts.streaming.UnsupportedPrefillConfiguration:
  Compiled prefill requires verified mask skip; use eager for explicit masks.
```

Standalone strict RoPE artifacts:

```text
strict-rope-repro/bf16-rope-current.json
SHA256: 5f0223a7c00c44b46ffe24dd4f3b3c8410ac7bd81c7752f054271edecc035533
result: compile_inductor_default first_diff q_rope, max_abs 0.03125

strict-rope-repro/bf16-rope-strict_add.json
SHA256: f62ac6d728b44d94c04ac907e70d4c0e8be86d479da76b589df56805605ae5f3
result: compile_inductor_default exact

strict-rope-repro/bf16-rope-strict_rope.json
SHA256: 0d7cbddbf369b0db732fc838a9e748141c84cc1c4103b295e1c49ad087e47b9a
result: compile_inductor_default exact
```

Standalone strict RMSNorm artifacts:

```text
strict-rmsnorm-repro/bf16-qnorm-current.json
SHA256: 50b0d76061a3252e4b430b4f235ad28da7b75b7c55d89d035e72f96012fdfba2
result: compile_inductor_default max_abs 0.03125

strict-rmsnorm-repro/bf16-qnorm-aten_rms_norm.json
SHA256: be622911494ee1c6487d828c9b5f54a7a0b86ba197a87ac13e4688219224b2fd
result: compile_inductor_default exact

strict-rmsnorm-repro/bf16-qnorm-strict_custom.json
SHA256: ddb40cb583a89a1980d3ac60cbfd32eab06460b7455b1fd3f17a9ad36c61dda1
result: compile_inductor_default exact
```

Full true-greedy strict compatibility gates:

```text
strict-compat-full-gate/bf16-inductor-aten-rms-strict-rope-r1.json
SHA256: 7cbc4d63381a7812fd69b1e4029b010b0d60614eebc4c028602926980db8b930
result: failed; logits_last max_abs 0.3125, past_hidden max_abs 0.3125,
  codec differs at frame 5 codebook 1, same frame count and EOS status.

strict-compat-full-gate/bf16-inductor-strict-rms-strict-rope-r1.json
SHA256: 52f9e4d60a1f6dcc42e946d9e545a54fac23c41e749eccf623778744ba953286
result: failed; logits_last max_abs 0.25, past_hidden max_abs 0.5,
  codec differs at frame 7 codebook 1, same frame count and EOS status.
```

Attention A/B and layer-prefix bisection follow-up:

```text
bridge scripts:
  scripts/qwen_prefill_compile_parity.py
  scripts/qwen_prefill_layer_prefix_parity.py
new diagnostic switch:
  --force-talker-attn-implementation eager|sdpa
compat modes:
  --rmsnorm-compat-mode strict_custom
  --rope-compat-mode strict_add
  --mlp-compat-mode strict_mul
```

Requested eager attention did not load actual eager attention:

```text
attention-ab-strict-full-gate/bf16-inductor-eager-attn-strict-rms-strict-rope-r1.json
SHA256: 9da5f22568930b835fd6176dbbb61e200f3caa35c9e7c489977555e42614a6fe
actual_talker_attn_implementation: sdpa
result: failed; logits_last max_abs 0.25
```

Forced attention A/B:

```text
attention-ab-strict-full-gate/bf16-inductor-forced-sdpa-attn-strict-rms-strict-rope-r1.json
SHA256: 06edaf5e6ea6f03a5a2e57fe2559d48c210666281c2c9b5b6ef7f4486eea1430
result: failed; logits_last max_abs 0.25, past_hidden max_abs 0.5,
  codec differs at frame 7 codebook 1, same frame count and EOS status.

attention-ab-strict-full-gate/bf16-inductor-forced-eager-attn-strict-rms-strict-rope-r1.json
SHA256: 5a9dbe400f51a7fdb439169a6d56a45611f0684830d685732fb1032157dafba5
result: failed; logits_last max_abs 1.4375, past_hidden max_abs 1.8125,
  codec differs at frame 0 codebook 2, same frame count and EOS status.
```

Layer-prefix bisection, strict RMSNorm/RoPE only:

```text
layer-prefix-bisect/bf16-sdpa-strict-prefix-0.json
SHA256: 24c9d4406ba1b16113346bf450647abd16f64e8f9f1b25c1352955ef2df5fd36
result: exact

layer-prefix-bisect/bf16-sdpa-strict-prefix-1.json
SHA256: 4e3131a378b39fcfb2b535c6c1e4e3bc2ff50086e9b7a49a8f337c97cb79472c
result: layer output max_abs 0.125

layer-prefix-bisect/bf16-sdpa-strict-layer0-mlp_mul.json
SHA256: 928bf71796c16ff0e720720838c3b0fd46f5c1bbc3a52631f42878e14c559c50
result: first materialized MLP diff, max_abs 0.015625

layer-prefix-bisect/bf16-sdpa-strict-layer0-mlp_output.json
SHA256: 4c71df70dae5fc4b35db55fabf9e1903ce09b2f4bd77c4ec7e76f4cb136051a8
result: MLP output max_abs 0.125
```

Layer-prefix bisection, strict RMSNorm/RoPE/MLP multiply:

```text
layer-prefix-bisect/bf16-sdpa-strict-rms-rope-mlp-prefix-1.json
SHA256: 8765e991efce517b5a14118e0dd98d42b38c155017ca5b788312947ded379d3b
result: exact

layer-prefix-bisect/bf16-sdpa-strict-rms-rope-mlp-prefix-8.json
SHA256: 401316a7d27a55cb341b32f91f58482065fade91604a26f8e60c703fb6cd0d29
result: exact

layer-prefix-bisect/bf16-sdpa-strict-rms-rope-mlp-prefix-9.json
SHA256: 0e6cd6f480d65cdd356e313e8a3b97b27c0f242124fd62b771d847456d552c2e
result: exact

layer-prefix-bisect/bf16-sdpa-strict-rms-rope-mlp-prefix-10.json
SHA256: 7586333ef0d421d3debc6bcb7008c90e6b37f8d26be88fa08ef5c97e39e93302
result: first new prefix diff, max_abs 0.00390625

layer-prefix-bisect/bf16-sdpa-strict-rms-rope-mlp-layer9-attention_output.json
SHA256: 1b1b16ca3656856177bc9780e14b7a2334ba66287ae4b3cdc4c0b6a9abf94671
result: first layer-9 stage diff, max_abs 0.0009765625

layer-prefix-bisect/bf16-sdpa-strict-rms-rope-mlp-layer9-layer_output.json
SHA256: a0365a74c81f2719166366ec3ab938d371118cd04cf8da480f41a8f0c332c302
result: layer-9 output max_abs 0.0625
```

Full strict RMSNorm/RoPE/MLP gate:

```text
strict-compat-full-gate/bf16-inductor-strict-rms-rope-mlp-r1.json
SHA256: 984a508e5f7888f2056de678544d81617d33bad17a9c3ab74542551fc24e7e25
result: failed; logits_last max_abs 0.21875, past_hidden max_abs 1.0,
  codec differs at frame 4 codebook 7, frame count differs.
```

FasterQwen pytest verification after installing pytest into `.venv-faster-qwen`:

```text
command:
  .venv-faster-qwen/Scripts/python.exe -m pip install pytest
result:
  installed pytest 9.1.1, pluggy 1.6.0, iniconfig 2.3.0

command:
  .venv-faster-qwen/Scripts/python.exe -m pytest
    C:/_repoz/faster-qwen3-tts-v032-stack112-clean/tests/test_sampling.py -q
result:
  25 passed, 1 Dynamo warning, 21.40 s

command:
  .venv-faster-qwen/Scripts/python.exe -m pytest
    C:/_repoz/faster-qwen3-tts-v032-stack112-clean/tests/test_ggml_backend.py
    C:/_repoz/faster-qwen3-tts-v032-stack112-clean/tests/test_sample_rate.py
    C:/_repoz/faster-qwen3-tts-v032-stack112-clean/tests/test_voice_clone_prompt_api.py -q
result:
  57 passed, 5.56 s

full suite:
  .venv-faster-qwen/Scripts/python.exe -m pytest
    C:/_repoz/faster-qwen3-tts-v032-stack112-clean/tests -vv
result:
  timed out after 15 minutes before completing.

collect-only:
  96 tests collected in 10.00 s.
```

Attention sentinel and production-signature layer-9 repro:

```text
new scripts/features:
  scripts/qwen_prefill_compile_parity.py --trace-attention-calls
  scripts/qwen_prefill_layer9_attention_parity.py

attention-sentinel/bf16-sdpa-trace-strict-rms-rope-mlp-prefill-r1.json
SHA256: 97e673d28ebe44bca36541628c39aa143f8bee79b83dfc7c38527d94c4e271c8
result: attention_call_probe eager=0, sdpa=28; prefill diff remains 0.21875
  without strict SDPA.
```

Production-signature layer-9 ladder, strict RMSNorm/RoPE/MLP multiply:

```text
layer9-production-signature/bf16-sdpa-strict-rms-rope-mlp-layer9-layer_input.json
SHA256: 08fdc7b8e8236140d2fc41360c82707c2a0c20c3198e9c49f10aa3c4d9dd6854
result: exact

layer9-production-signature/bf16-sdpa-strict-rms-rope-mlp-layer9-q_proj.json
SHA256: 719ecb4e66a9419f8c8e8573260e2fe9a95afcaf86ace243b21c8275f8f867aa
result: exact

layer9-production-signature/bf16-sdpa-strict-rms-rope-mlp-layer9-k_proj.json
SHA256: 9a50844e82eea11b77e36d20e1328c6827b3b1a23852d37357ca793a83ec9b13
result: exact

layer9-production-signature/bf16-sdpa-strict-rms-rope-mlp-layer9-v_proj.json
SHA256: 194a093b3d46cc7ce44b86293d5f80a0eb1dff50cf28ab036cc55d24d1c8d377
result: exact

layer9-production-signature/bf16-sdpa-strict-rms-rope-mlp-layer9-q_norm.json
SHA256: f9c044f1858c2a894f4b4d31bee72c5feb3a08132fdc6166350833c17a7af181
result: exact

layer9-production-signature/bf16-sdpa-strict-rms-rope-mlp-layer9-k_norm.json
SHA256: c1fe7b4ed09cf01bc8c766a6374fbb9de14339069bca81f6ce1950d0c177ae51
result: exact

layer9-production-signature/bf16-sdpa-strict-rms-rope-mlp-layer9-q_rope.json
SHA256: e627b4b9d949bf28cdb5e7ff885ee47f813b2e2e99a6a11ab19adbabd80cbbe0
result: exact

layer9-production-signature/bf16-sdpa-strict-rms-rope-mlp-layer9-k_rope.json
SHA256: c770eae843f733b256a8ca48268acf06aa4e64e68ee262871a39c687d910ff2d
result: exact

layer9-production-signature/bf16-sdpa-strict-rms-rope-mlp-layer9-attention_context-default.json
SHA256: 98c36f15be651005cf00ec094a7a1e64a1d375e7d7c49851a9d9679fb805de7f
result: default SDPA max_abs 0.0009765625

layer9-production-signature/bf16-sdpa-strict-rms-rope-mlp-layer9-attention_context-math_sdpa.json
SHA256: 9dd270dc1db73272f11af091257987779eeb97a49ef239c68d503fa23a57d051
result: forced math SDPA max_abs 0.0009765625

layer9-production-signature/bf16-sdpa-strict-rms-rope-mlp-layer9-attention_context-eager_formula.json
SHA256: ec4c88450fbf1ebf4a48a8da8d7a34083e9d9875ed1ec47d131f513efc631914
result: explicit eager formula max_abs 0.017578125

layer9-production-signature/bf16-sdpa-strict-rms-rope-mlp-layer9-attention_context-strict_sdpa.json
SHA256: 57d5e0bb274e41dfd2005df027ce0d8ec5f69e707402f0380b6d94ebc270a48e
result: opaque strict SDPA custom op exact

layer9-production-signature/bf16-sdpa-strict-rms-rope-mlp-layer9-o_proj.json
SHA256: c06bb8dbb7d010de34dbee4357d740225146adb6d367e04faf677a79522594c8
result: default SDPA path max_abs 0.0009765625

layer9-production-signature/bf16-sdpa-strict-rms-rope-mlp-layer9-attention_output.json
SHA256: cced91dfb3372d56368d819683ee6475bdc592ed5f72228773dfe8e196e4a344
result: default SDPA path max_abs 0.0009765625
```

Full strict RMSNorm/RoPE/MLP/SDPA true-greedy gate:

```text
strict-compat-full-gate/bf16-inductor-strict-rms-rope-mlp-sdpa-r1.json
SHA256: ec7c72ecfec83244a82a51d1ab22e253ccf9a129b9866a16553cbc435aa86b5a
result: passed; attention probe eager=0, sdpa=28; prefill diff 0.0;
  codec/frame/EOS/waveform/audio samples match eager.

strict-compat-full-gate/bf16-inductor-strict-rms-rope-mlp-sdpa-r2.json
SHA256: 4390e94cf17250ca22b7552bb23ebb850b8651506e288ac0b2f41931b7d122f6
result: passed over 2 repeats; attention probe eager=0, sdpa=28; prefill diff
  0.0; codec/frame/EOS/waveform/audio samples match eager.
```

Verification after strict compatibility pass:

```text
py_compile:
  .venv-faster-qwen/Scripts/python.exe -m py_compile scripts/qwen_prefill_compile_parity.py
  scripts/qwen_rope_inductor_repro.py scripts/qwen_rmsnorm_inductor_repro.py
  C:/_repoz/faster-qwen3-tts-v032-stack112-clean/faster_qwen3_tts/streaming.py
  C:/_repoz/faster-qwen3-tts-v032-stack112-clean/tests/test_sampling.py
  passed

scripts/check-python.ps1 -UseVenv -VenvPath .venv
  passed: Ruff, Pyright, 154 Python tests, 2 skipped

ctest --test-dir build/default --output-on-failure
  passed: 9/9 C++ tests
```

Input-shape matrix, Qwen `auto -> engine_warmup`, one full synthesis warmup:

```powershell
$oldPyPath = $env:PYTHONPATH
$shapes = @(
    @{ Name = "short"; Text = "Short latency probe." },
    @{ Name = "medium"; Text = "This is a faster backend latency benchmark." },
    @{
        Name = "long"
        Text = "This is a faster backend latency benchmark. The bridge keeps the worker process warm between requests. We are measuring first audio latency after startup warmup."
    }
)
try {
    $env:PYTHONPATH = "worker/src;tests/python"
    foreach ($shape in $shapes) {
        $out = .\.venv-packaging\Scripts\python.exe -B tests\python\benchmark_packaged_worker_restart.py `
            .\.venv-packaging\Scripts\python.exe `
            --worker-prefix-arg=-B `
            --worker-prefix-arg=-P `
            --worker-prefix-arg=-s `
            --worker-prefix-arg=-m `
            --worker-prefix-arg=qwen_tts_bridge_worker `
            --engine qwen `
            --model-path models\Qwen3-TTS-12Hz-0.6B-CustomVoice `
            --runtime-backend faster `
            --device cuda `
            --dtype auto `
            --emit-every-frames 8 `
            --max-seq-len 2048 `
            --warmup-synthesis `
            --warmup-synthesis-passes 1 `
            --warmup-text $shape.Text `
            --warmup-language English `
            --warmup-speaker ryan `
            --runs 10 `
            --requests-per-run 4 `
            --partial-output "tmp\shape-$($shape.Name)-r10-partial.json" `
            --progress-every-runs 1 `
            --progress-output "tmp\shape-$($shape.Name)-r10-progress.txt" `
            --seed 4242 `
            --seed-mode fixed `
            --warmup-seed 4242 `
            --text $shape.Text `
            --language English `
            --speaker ryan `
            --timeout-seconds 1200
        [IO.File]::WriteAllText(
            "docs\benchmark-artifacts\rtx4090-2026-07-22\paired-restart-source-worker-faster-customvoice-chunk8-r10x4-shape-$($shape.Name)-seed4242-auto-warmup1full.json",
            ($out -join "`n"),
            [System.Text.UTF8Encoding]::new($false)
        )
    }
}
finally {
    $env:PYTHONPATH = $oldPyPath
}
```

Shuffled input-shape matrix, 50 fresh worker processes per shape, one fixed
medium synthesis warmup:

```powershell
@'
import json, random
from pathlib import Path

out = Path(
    "docs/benchmark-artifacts/rtx4090-2026-07-22/"
    "input-shape-r50-each-seed20260723.jsonl"
)
shapes = {
    "short": "Short latency probe.",
    "medium": "This is a faster backend latency benchmark.",
    "long": (
        "This is a faster backend latency benchmark. The bridge keeps the worker "
        "process warm between requests. We are measuring first audio latency "
        "after startup warmup."
    ),
    "very_long": (
        "This is a faster backend latency benchmark. The bridge keeps the worker "
        "process warm between requests. We are measuring first audio latency "
        "after startup warmup. This longer prompt adds enough text to stress "
        "prefill behavior while keeping the spoken content practical for repeated "
        "local validation on the RTX 4090. The output should remain plain English "
        "and use the same Ryan speaker preset."
    ),
}
rows = []
for label, text in shapes.items():
    for index in range(50):
        rows.append({
            "label": label,
            "text": text,
            "language": "English",
            "speaker": "ryan",
            "instruction": "",
            "replicate": index + 1,
        })
random.Random(20260723).shuffle(rows)
out.write_text(
    "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows)
    + "\n",
    encoding="utf-8",
)
'@ | .\.venv\Scripts\python.exe -

$oldPyPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = "worker/src;tests/python"
    $out = .\.venv-packaging\Scripts\python.exe -B tests\python\benchmark_packaged_worker_restart.py `
        .\.venv-packaging\Scripts\python.exe `
        --worker-prefix-arg=-B `
        --worker-prefix-arg=-P `
        --worker-prefix-arg=-s `
        --worker-prefix-arg=-m `
        --worker-prefix-arg=qwen_tts_bridge_worker `
        --engine qwen `
        --model-path models\Qwen3-TTS-12Hz-0.6B-CustomVoice `
        --runtime-backend faster `
        --device cuda `
        --dtype auto `
        --emit-every-frames 8 `
        --max-seq-len 2048 `
        --warmup-synthesis `
        --warmup-synthesis-passes 1 `
        --warmup-text "This is a faster backend latency benchmark." `
        --warmup-language English `
        --warmup-speaker ryan `
        --runs 200 `
        --requests-per-run 4 `
        --run-shapes-jsonl docs\benchmark-artifacts\rtx4090-2026-07-22\input-shape-r50-each-seed20260723.jsonl `
        --partial-output tmp\shape-r50x4-clean-partial.json `
        --progress-every-runs 1 `
        --progress-output tmp\shape-r50x4-clean-progress.txt `
        --seed 4242 `
        --seed-mode fixed `
        --run-seed-step 1009 `
        --warmup-seed 4242 `
        --run-warmup-seed-step 0 `
        --timeout-seconds 1200
    [IO.File]::WriteAllText(
        "docs\benchmark-artifacts\rtx4090-2026-07-22\paired-restart-source-worker-faster-customvoice-chunk8-r50each-shuffled-shapes-seed20260723-fixed-auto-warmup1medium.json",
        ($out -join "`n"),
        [System.Text.UTF8Encoding]::new($false)
    )
}
finally {
    $env:PYTHONPATH = $oldPyPath
}
```

Torch `2.10.0+cu128` source-worker paired restart control:

```powershell
$oldPyPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = "worker/src;tests/python;external/python/Qwen3-TTS-streaming;C:\_repoz\faster-qwen3-tts-v032-stack112-clean"
    $out = .\.venv-faster-qwen\Scripts\python.exe -B tests\python\benchmark_packaged_worker_restart.py `
        .\.venv-faster-qwen\Scripts\python.exe `
        --worker-prefix-arg=-B `
        --worker-prefix-arg=-P `
        --worker-prefix-arg=-s `
        --worker-prefix-arg=-m `
        --worker-prefix-arg=qwen_tts_bridge_worker `
        --engine qwen `
        --model-path models\Qwen3-TTS-12Hz-0.6B-CustomVoice `
        --runtime-backend faster `
        --device cuda `
        --dtype auto `
        --emit-every-frames 8 `
        --max-seq-len 2048 `
        --warmup-synthesis `
        --warmup-synthesis-passes 2 `
        --warmup-text "This is a faster backend latency benchmark." `
        --warmup-language English `
        --warmup-speaker ryan `
        --runs 20 `
        --requests-per-run 4 `
        --seed 4242 `
        --text "This is a faster backend latency benchmark." `
        --language English `
        --speaker ryan `
        --timeout-seconds 1200
    [IO.File]::WriteAllText(
        "docs\benchmark-artifacts\rtx4090-2026-07-22\paired-restart-source-worker-faster-customvoice-chunk8-r20x4-seed4242-torch210-cu128.json",
        ($out -join "`n"),
        [System.Text.UTF8Encoding]::new($false)
    )
}
finally {
    $env:PYTHONPATH = $oldPyPath
}
```

2026-07-24 faster prefill profiling smoke:

Add `--request-gpu-poll-interval-ms 25` to collect per-request `nvidia-smi`
snapshots in `request.gpu_poll`; this is intended for outlier reruns because
polling itself adds a little measurement noise.

Add `--warmup-from-run-shape` when comparing bucket-specific prefill behavior.
It keeps the same fresh-worker structure, but passes each JSONL row's
text/language/speaker/instruction into that worker's synthesis warmup.

Current faster telemetry provenance:

```text
faster-qwen3-tts v2 smoke commit: 8152612
retained v2 wheel SHA256: 3f81c8cd1eca91d203913d6befb4ee11d2aa8e38e8c593206bedc8df8db63b03
faster-qwen3-tts current local telemetry commit: f98242e
retained v3 wheel SHA256: b45c21193cad723456fdcb12d8cdad7afb3eeec0bf04c124e5406f6183d43696
upstream prerequisite/base commit: afa6120
v3 patch series: faster-qwen3-tts-telemetry-patch/0001-0004-prefill-profile-telemetry-series.patch
v3 patch series SHA256: 14e40c8fdb6fd0d46c5a3b2becb85d9abd4af3d1e76bda53d4b9a8e5dbc17d49
v3 git bundle: faster-qwen3-tts-telemetry-patch/faster-qwen3-tts-afa6120-to-f98242e.bundle
v3 git bundle SHA256: 2f95f76c382db9fe4addee55551fc9e414832fb63d1ea54f27e001c2b47eb3f6
source archive policy: no repeated full source ZIPs after the one-off v2 snapshot
Nsight status: nsys/ncu not found in PATH during the v2 pass
```

Randomized three-way overhead control:

```text
artifact directory: profile-overhead-control-v3-r50x4-randomized-runs/
summary artifact: profile-overhead-control-v3-r50x4-randomized-runs/summary.json
summary SHA256: 022141b5782dfaec742a2518fceb5f392fe81d178399475a7cff8cfe5205b547
schedule SHA256: 9b066f8bdb0b89762683037756f68ac55db76ed5c2f3f1cd7d81558e32ff43c8
raw run JSON archive: profile-overhead-control-v3-r50x4-randomized-runs/raw-run-json.zip
raw run JSON archive SHA256: c5e716ce54897eaff14134f4b77043eb501c8f22ebdfff1f9a3abdd7cdf4f3e0
schedule seeds: 20260724 for first 30/condition, 20260725 for extension to 50/condition
runs per condition: 50
requests per run: 4
A_pristine wheel SHA256: 91e5b434a4caee3153ebd2a7e3637fa6a940e716de7af6c7f4791c3ad84422ff
B/C telemetry wheel SHA256: b45c21193cad723456fdcb12d8cdad7afb3eeec0bf04c124e5406f6183d43696
benchmark flag: --allow-unverified-faster-wheel
reason for flag: A and B/C intentionally install different local wheels with the same distribution version
```

Directional first TTFA overhead checks from `summary.json`:

```text
B - A median: -2.952 ms
B - A p95: +5.295 ms
C - B median: +4.974 ms
C - B p95: -7.606 ms
```

Nsight Systems install attempt:

```text
official page checked: https://developer.nvidia.com/nsight-systems/get-started
official download data endpoint: https://developer.nvidia.com/tools-downloads.json
version found: 2026.4.1
Windows MSI URL: https://developer.nvidia.com/downloads/assets/tools/secure/nsight-systems/2026_4/NsightSystems-2026.4.1.174-3856861.msi
server Content-Length: 560553984 bytes
download path: tmp/NsightSystems-2026.4.1.174-3856861.msi
install log: tmp/nsight-systems-install.log
extract log: tmp/nsight-systems-extract.log
install result: msiexec /i failed with 1603 because Administrator privileges are required
administrative extract result: msiexec /a also failed with 1603
7-Zip extraction: succeeded into tmp/nsight-systems-cabs, but flattened nsys.exe scratch copy was not runnable
trace status: blocked until Nsight Systems is installed by an administrator or a valid portable CLI layout is supplied
```

Nsight Systems trace capture after manual installation:

```text
nsys path: C:/Program Files/NVIDIA Corporation/Nsight Systems 2026.4.1/target-windows-x64/nsys.exe
nsys version: 2026.4.1.174-264138568610v0
requested trace flags: --trace=cuda,nvtx,wddm --sample=none
capture range mode: --capture-range=nvtx
capture range end: --capture-range-end=stop-shutdown
environment: NSYS_NVTX_PROFILER_REGISTER_ONLY=0
limitation: WDDM trace disabled by Nsight because Administrator or Performance Log Users privileges are required
limitation: CPU context switch trace disabled by Nsight because Administrator privileges are required
```

First-user capture:

```powershell
$env:NSYS_NVTX_PROFILER_REGISTER_ONLY = "0"

& "C:\Program Files\NVIDIA Corporation\Nsight Systems 2026.4.1\target-windows-x64\nsys.exe" profile `
    --trace=cuda,nvtx,wddm `
    --sample=none `
    --capture-range=nvtx `
    --nvtx-capture=qtb_profile_first_user_request `
    --capture-range-end=stop-shutdown `
    --force-overwrite=true `
    -o docs\benchmark-artifacts\rtx4090-2026-07-22\nsight-systems-v3\first-user-prefill `
    .\.venv-packaging\Scripts\python.exe -B tests\python\benchmark_packaged_worker_restart.py `
    .\.venv-packaging\Scripts\python.exe `
    --worker-prefix-arg=-B `
    --worker-prefix-arg=-P `
    --worker-prefix-arg=-s `
    --worker-prefix-arg=-m `
    --worker-prefix-arg=qwen_tts_bridge_worker `
    --engine qwen `
    --model-path models\Qwen3-TTS-12Hz-0.6B-CustomVoice `
    --runtime-backend faster `
    --device cuda `
    --dtype auto `
    --emit-every-frames 8 `
    --max-seq-len 2048 `
    --warmup-synthesis `
    --warmup-synthesis-passes 1 `
    --warmup-text "I am your robot. I am your worker." `
    --warmup-language English `
    --warmup-speaker ryan `
    --runs 1 `
    --requests-per-run 2 `
    --seed 4242 `
    --seed-mode fixed `
    --warmup-seed 4242 `
    --text "I am your robot. I am your worker." `
    --language English `
    --speaker ryan `
    --profile-prefill `
    --timeout-seconds 1200
```

Steady capture uses the same command with:

```text
--nvtx-capture=qtb_profile_steady_request
-o docs\benchmark-artifacts\rtx4090-2026-07-22\nsight-systems-v3\steady-prefill
```

Nsight artifact hashes:

```text
first-user-prefill.nsys-rep SHA256: ba355b53659b454da68f9187049cb9fbad16684acee6cb5203bfa1f1ff3760b5
first-user-prefill.sqlite SHA256: 536e28e3c02c02e6ac5b279b7b03f053a4b3ea6c734c5336f639ec45715a3452
first-user-stats.txt SHA256: 04097ad16f2b3be9bb7a758ce8819c1d3306a0e1c4b34e7ffe69b5090f70f506
first-user-nsys-stdout.txt SHA256: 8b7c80f0d0b504601c423e5e8f43255352f979ae020790133b2861a3aad63d2b
steady-prefill.nsys-rep SHA256: 871d33105735a665a7f213354d9c6f0736515cdc42bd590b5de588ca723d8c51
steady-prefill.sqlite SHA256: c6f165c802f1c76b731529d52dc7980eccc7515072e87e68768bd053424860ac
steady-stats.txt SHA256: 0e10935a448ebbd799f77b985548ea7b6abafd4865b4e9d3c6a60f31c18ba1db
steady-nsys-stdout.txt SHA256: 5838aec7e1ff796b3c231babb40d8669eb5aa9f8a61f6d55ddb956c300610643
summary.json SHA256: 63edcc786aef75b9277ed67a3bed6701dbf2f70fdbfce98358253d3348a1dbd3
```

Nsight summary:

```text
first-user outer range: 183.198 ms
steady outer range: 172.315 ms
first-steady outer delta: +10.884 ms
first-user talker-forward range: 173.882 ms
steady talker-forward range: 163.435 ms
first-steady talker-forward delta: +10.448 ms
first-user CUDA runtime API: 85.069 ms across 2982 calls
steady CUDA runtime API: 81.048 ms across 2982 calls
first-user CUDA GPU kernels+mem: 5.966 ms
steady CUDA GPU kernels+mem: 6.014 ms
```

```powershell
$oldPyPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = "worker/src;tests/python"
    .\.venv-packaging\Scripts\python.exe -B tests\python\benchmark_packaged_worker_restart.py `
        .\.venv-packaging\Scripts\python.exe `
        --worker-prefix-arg=-B `
        --worker-prefix-arg=-P `
        --worker-prefix-arg=-s `
        --worker-prefix-arg=-m `
        --worker-prefix-arg=qwen_tts_bridge_worker `
        --engine qwen `
        --model-path models\Qwen3-TTS-12Hz-0.6B-CustomVoice `
        --runtime-backend faster `
        --device cuda `
        --dtype auto `
        --emit-every-frames 8 `
        --max-seq-len 2048 `
        --warmup-synthesis `
        --warmup-synthesis-passes 1 `
        --warmup-text "I am your robot. I am your worker." `
        --warmup-language English `
        --warmup-speaker ryan `
        --runs 1 `
        --requests-per-run 2 `
        --seed 4242 `
        --seed-mode fixed `
        --warmup-seed 4242 `
        --text "I am your robot. I am your worker." `
        --language English `
        --speaker ryan `
        --profile-prefill `
        --partial-output docs\benchmark-artifacts\rtx4090-2026-07-22\prefill-profile-source-worker-faster-customvoice-chunk8-sampling-r1x2.json `
        --timeout-seconds 1200

    .\.venv-packaging\Scripts\python.exe -B tests\python\benchmark_packaged_worker_restart.py `
        .\.venv-packaging\Scripts\python.exe `
        --worker-prefix-arg=-B `
        --worker-prefix-arg=-P `
        --worker-prefix-arg=-s `
        --worker-prefix-arg=-m `
        --worker-prefix-arg=qwen_tts_bridge_worker `
        --engine qwen `
        --model-path models\Qwen3-TTS-12Hz-0.6B-CustomVoice `
        --runtime-backend faster `
        --device cuda `
        --dtype auto `
        --emit-every-frames 8 `
        --max-seq-len 2048 `
        --warmup-synthesis `
        --warmup-synthesis-passes 1 `
        --warmup-text "I am your robot. I am your worker." `
        --warmup-language English `
        --warmup-speaker ryan `
        --runs 1 `
        --requests-per-run 2 `
        --seed 4242 `
        --seed-mode fixed `
        --warmup-seed 4242 `
        --text "I am your robot. I am your worker." `
        --language English `
        --speaker ryan `
        --profile-prefill `
        --no-sample `
        --partial-output docs\benchmark-artifacts\rtx4090-2026-07-22\prefill-profile-source-worker-faster-customvoice-chunk8-greedy-r1x2.json `
        --timeout-seconds 1200
}
finally {
    $env:PYTHONPATH = $oldPyPath
}
```
