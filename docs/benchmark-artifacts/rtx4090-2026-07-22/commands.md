# RTX 4090 Faster-Qwen Profiling Commands

Run from:

```text
C:/_repoz/faster-qwen3-tts-v032-stack112-clean
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
