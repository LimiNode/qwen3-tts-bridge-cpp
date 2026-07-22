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
