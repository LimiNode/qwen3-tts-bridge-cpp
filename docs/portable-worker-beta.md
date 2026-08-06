# Portable Worker Beta

This document describes the current Windows x64 portable-worker beta boundary.
It is a packaging path for the persistent Python worker, not a release claim
for every Qwen model or every CUDA machine.

## What Is Packaged

`scripts/package-python-worker.ps1` stages a private Python 3.11 runtime,
the worker wheel, its local wheel artifact, and a build manifest under
`dist/QwenTTSBridge/worker-python`. The generated
`qwen_tts_worker.cmd` sets `PYTHONHOME`, `PYTHONPATH`, and disables user-site
imports, so the launched worker does not need a user-installed Python.
The package also includes `qwen_tts_doctor.cmd`, an explicit integrity check;
it is not run for every synthesis request.

After the staged isolation probe and a final bytecode cleanup, packaging writes
and immediately verifies
`portable-python-tree-manifest.json`. It hashes the actual contents of the
complete staged `worker-python/python` tree, including the interpreter, DLLs,
standard library, and `site-packages`. `build-manifest.json` records its
SHA-256. The manifest excludes only transient `__pycache__`, `.pyc`, and `.pyo`
files.

Model weights are deliberately external. Copy a compatible model directory
next to the distribution or provide its absolute path at launch; do not put
model weights in Git or in the worker package.

## Packaged Playback

A complete technical-beta package contains `start-qwen-tts.ps1`, the
canonical human-facing launcher for `bin\qwen_tts_play.exe`. It starts the
worker through the package's private `python.exe`; do not pass
`worker\qwen_tts_worker.cmd` to `--worker`, because Windows command scripts
are not a native executable worker boundary.

Create an external user config once. It intentionally lives under
`%LOCALAPPDATA%`, outside the sealed package tree:

```powershell
.\start-qwen-tts.ps1 -InitializeConfig
notepad $env:LOCALAPPDATA\QwenTTSBridge\runtime.local.json
```

Set the two external model paths in that file. Subsequent CustomVoice playback
needs no worker arguments:

```powershell
.\start-qwen-tts.ps1
.\start-qwen-tts.ps1 -Text "Hello from the packaged worker."
```

Base playback selects a registered package voice profile separately:

```powershell
.\start-qwen-tts.ps1 -ModelKind Base `
  -VoiceId kraftwerk_robot_ru_bootstrap_fidelity
```

`-ModelPath`, `-Speaker`, `-Language`, `-Instruction`, and `-VoiceId` are
one-run overrides. `-DryRun` prints the fully resolved command without loading
the model. The launcher uses eager prefill and does not select an internal
GPU-specific compile profile.

## Build And Verify

Packaging must be built with Python 3.11. The package scripts use this version
by default and reject a different interpreter.

```powershell
scripts\setup-python-packaging.ps1 -UseVenv
scripts\package-python-worker.ps1 -UseVenv
scripts\test-portable-python-worker.ps1 -UseVenv
```

The last command starts the staged worker with the mock backend. It verifies
that the private runtime can import the staged worker without leaking the
source tree into `sys.path`.

Before the first real-model start, after unpacking an update, or when diagnosing
a machine, run the packaged doctor:

```powershell
.\dist\QwenTTSBridge\worker-python\qwen_tts_doctor.cmd `
  --model-path C:\models\Qwen3-TTS-12Hz-1.7B-Base `
  --model-manifest C:\models\Qwen3-TTS-12Hz-1.7B-Base.manifest.json `
  --voice-registry .\config\voice-profiles.local.json `
  --require-cuda `
  --minimum-compute-capability 8.0
```

The doctor rehashes the staged Python runtime, checks that its tree manifest is
the one named by `build-manifest.json`, verifies an optional model content
manifest, preflights every selected voice WAV/profile, and reports CUDA, GPU,
and NVIDIA driver data. It fails before a model load when any requested check
does not match. It does not make a package cryptographically signed; distribute
the final archive itself with a separately published checksum.

For an additional low-level bridge check, point a MinGW-built example directly
at the staged private Python executable:

```powershell
.\build-mingw\qwen_tts_save_wav.exe `
  --worker .\dist\QwenTTSBridge\worker-python\python\python.exe `
  --worker-arg -B `
  --worker-arg -P `
  --worker-arg -s `
  --worker-arg -m `
  --worker-arg qwen_tts_bridge_worker `
  --worker-arg mock `
  --output portable-worker-smoke.wav `
  --text "Portable worker smoke."
```

## Real Qwen Packaging

A real-model artifact must be built from a separately pinned Python 3.11
environment that contains the selected Qwen and optional FasterQwen sources.
Use `-IncludeQwenFork` and, when applicable, `-IncludeFasterQwen` only after
those source trees and their transitive runtime dependencies have been pinned
and validated for that artifact.

```powershell
scripts\setup-python-packaging.ps1 -UseVenv -InstallQwenFork -InstallFasterQwen `
  -FasterQwenSourcePath C:\path\to\faster-qwen3-tts
scripts\package-python-worker.ps1 -UseVenv -IncludeQwenFork -IncludeFasterQwen `
  -FasterQwenSourcePath C:\path\to\faster-qwen3-tts
scripts\model_runtime_manifest.py build `
  --model-path C:\models\Qwen3-TTS-12Hz-0.6B-CustomVoice `
  --repository Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice `
  --revision <pinned-revision> `
  --output .\tmp\customvoice-model-manifest.json
scripts\test-portable-python-qwen-worker.ps1 -UseVenv `
  -ModelPath C:\models\Qwen3-TTS-12Hz-0.6B-CustomVoice `
  -ModelManifest .\tmp\customvoice-model-manifest.json `
  -RuntimeBackend faster
```

The real-model probe is intentionally manual: it hashes the staged runtime and
model with the packaged doctor, requires CUDA, then exchanges PCM with the
staged worker. It uses eager prefill and does not select a bridge compile or
allowlist profile, so it tests packaging rather than an experimental
performance policy. `--no-cuda-graphs` only controls the bridge-requested
upstream optimization hook; it cannot promise that FasterQwen will not use
its own internal CUDA graphs. A successful mock package does not establish
those conditions.

## Current Acceptance

The current beta acceptance is deliberately narrow:

- Windows x64 only.
- A staged Python 3.11 mock worker passes its isolation probe.
- The MinGW C++ WAV example exchanges framed PCM with that staged worker.
- A real Qwen package requires a clean source tree, a recorded wheel/build
  manifest, and a model-specific GPU smoke before distribution.

The next release-pipeline task is to stage the native C++ executables and
their MinGW runtime DLLs alongside the worker, then validate that full folder
from a clean Windows environment. Until that happens, this is a portable
worker beta rather than a one-folder end-user application release.
