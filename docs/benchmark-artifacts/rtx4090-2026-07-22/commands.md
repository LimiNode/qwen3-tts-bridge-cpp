# RTX 4090 Faster-Qwen Profiling Commands

Run from:

```text
C:/_repoz/faster-qwen3-tts-v032-stack112-clean
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
