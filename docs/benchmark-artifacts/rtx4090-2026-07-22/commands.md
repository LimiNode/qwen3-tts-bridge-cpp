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
