# Qwen GPU Validation Checklist

This checklist is for a Windows machine with a real NVIDIA GPU and local Qwen
model files. It validates the bridge beyond the no-GPU import probes by loading
the model, producing PCM, and optionally writing a WAV file through the C++
client example.

The checklist intentionally uses the portable Python worker baseline. Nuitka
CustomVoice packaging remains a separate optimization track.

## Start Here On A New Machine

The repository state before this checklist:

- the portable Python worker baseline is merged into `main`;
- `Portable Qwen Import Probe` has passed on GitHub Actions run `28705920145`;
- no-GPU validation already proves that the vendored Qwen package can be staged
  and imported from the portable runtime;
- the remaining unknown is real GPU execution: model load, first PCM, WAV
  output, and audible quality.

On the GPU machine, begin with a fresh checkout of `main`, then follow the
steps below in order. Do not restart the Nuitka slimming track unless the
portable Python worker path fails for a reason that also affects real usage.

Record these details for the next review pass:

- exact model path and model family;
- speaker or VoiceDesign instruction;
- GPU model, driver, PyTorch version, and CUDA version;
- whether `ready`, `started`, first `AUDIO_PCM`, and `completed` were observed;
- stderr/metrics from the worker;
- generated WAV path and whether the audio content sounds correct.

## Machine Setup

- Windows x64.
- Python 3.11 available through `py -3.11` or an explicit `python.exe`.
- A CUDA-capable PyTorch environment that matches the installed NVIDIA driver.
- The vendored Qwen submodule checked out:

```powershell
git submodule update --init --recursive
```

- A local model directory under `models/`, for example:

```text
models/Qwen3-TTS-12Hz-0.6B-CustomVoice
```

For the 0.6B CustomVoice smoke candidate, use a known preset speaker such as
`ryan` or `serena` if the model advertises it.

## 1. Prepare Packaging Environment

```powershell
.\scripts\setup-python-packaging.ps1 -UseVenv -InstallQwenFork
```

This installs the packaging tools, the worker package, and the vendored
`qwen_tts` fork into `.venv-packaging`.

## 2. Build Portable Worker With Qwen

```powershell
.\scripts\package-python-worker.ps1 `
    -UseVenv `
    -Clean `
    -IncludeQwenFork
```

The packaging script must finish the staged import probe:

```text
qwen_tts.inference.qwen3_tts_model
```

This step does not load model weights and does not require a GPU.

## 3. Run Real Qwen Protocol Smoke

```powershell
.\scripts\test-packaged-qwen-worker.ps1 `
    -UseVenv `
    -WorkerExe dist\QwenTTSBridge\worker-python\qwen_tts_worker.cmd `
    -ModelPath models\Qwen3-TTS-12Hz-0.6B-CustomVoice `
    -Speaker ryan `
    -Text "GPU validation smoke test." `
    -TimeoutSeconds 900
```

Expected result:

- worker sends `ready`;
- request reaches `queued` and `started`;
- at least one non-empty `AUDIO_PCM` frame is received;
- request reaches `completed`;
- shutdown completes with exit code 0.

If startup fails before `ready`, keep stderr from the script output. Typical
failures are missing CUDA/PyTorch DLLs, missing model files, unsupported
speaker names, or model-specific Transformers import assumptions.

## 4. Write A WAV Through The C++ Example

Build the C++ example first, for example:

```powershell
cmake --build build\default --config Release --target qwen_tts_save_wav
```

Then launch the portable worker directly through its staged `python.exe`:

```powershell
$WorkerRoot = (Resolve-Path "dist\QwenTTSBridge\worker-python").Path
$env:PYTHONHOME = Join-Path $WorkerRoot "python"
$env:PYTHONPATH = Join-Path $WorkerRoot "python\Lib\site-packages"
$env:PYTHONNOUSERSITE = "1"
$env:PYTHONDONTWRITEBYTECODE = "1"

.\build\default\Release\qwen_tts_save_wav.exe `
    --worker (Join-Path $WorkerRoot "python\python.exe") `
    --worker-arg -B `
    --worker-arg -P `
    --worker-arg -s `
    --worker-arg -m `
    --worker-arg qwen_tts_bridge_worker `
    --worker-arg qwen `
    --worker-arg --model-path `
    --worker-arg (Resolve-Path "models\Qwen3-TTS-12Hz-0.6B-CustomVoice").Path `
    --worker-arg --device `
    --worker-arg cuda `
    --worker-arg --dtype `
    --worker-arg auto `
    --output tmp\qwen-gpu-smoke.wav `
    --text "This is a GPU validation WAV." `
    --speaker ryan `
    --request-timeout-ms 900000
```

After the command succeeds, listen to:

```text
tmp/qwen-gpu-smoke.wav
```

The WAV proves the C++ public API, stdio transport, worker protocol, Qwen
engine, and PCM writer all work together. It does not prove final voice quality.

## 5. Benchmark Persistent Worker Latency

Run at least one baseline benchmark and one optimized benchmark. These keep the
worker alive across requests and report per-request JSON metrics:

```powershell
.\scripts\benchmark-packaged-qwen-worker.ps1 `
    -UseVenv `
    -WorkerExe dist\QwenTTSBridge\worker-python\qwen_tts_worker.cmd `
    -ModelPath models\Qwen3-TTS-12Hz-0.6B-CustomVoice `
    -Speaker ryan `
    -Text "This is a GPU validation WAV." `
    -Requests 2 `
    -TimeoutSeconds 1200
```

Then run the optimized path:

```powershell
.\scripts\benchmark-packaged-qwen-worker.ps1 `
    -UseVenv `
    -WorkerExe dist\QwenTTSBridge\worker-python\qwen_tts_worker.cmd `
    -ModelPath models\Qwen3-TTS-12Hz-0.6B-CustomVoice `
    -Speaker ryan `
    -Text "This is a GPU validation WAV." `
    -Requests 2 `
    -TimeoutSeconds 1200 `
    -EnableStreamingOptimizations
```

Finally run the user-facing warmup mode. This intentionally moves compile and
first-synthesis cost before `ready`, so the first request after `ready` should
be much faster:

```powershell
.\scripts\benchmark-packaged-qwen-worker.ps1 `
    -UseVenv `
    -WorkerExe dist\QwenTTSBridge\worker-python\qwen_tts_worker.cmd `
    -ModelPath models\Qwen3-TTS-12Hz-0.6B-CustomVoice `
    -Speaker ryan `
    -Text "This is a GPU validation WAV." `
    -Requests 1 `
    -TimeoutSeconds 1200 `
    -EnableStreamingOptimizations `
    -WarmupSynthesis `
    -WarmupSpeaker ryan `
    -WarmupText "Warmup."
```

Record `first_audio_ms`, `completed_ms`, `audio_duration_ms`, and
`real_time_factor` for every request.

## 6. Record Diagnostics

For every GPU validation run, record:

- GPU model and VRAM.
- NVIDIA driver version.
- Python version.
- PyTorch and CUDA versions:

```powershell
.\.venv-packaging\Scripts\python.exe -c "import torch; print(torch.__version__); print(torch.version.cuda); print(torch.cuda.get_device_name(0))"
```

- model path and model family.
- speaker name or VoiceDesign instruction.
- whether first audio arrived before timeout.
- generated WAV path, if any.

Keep generated WAV files and model weights out of git.
