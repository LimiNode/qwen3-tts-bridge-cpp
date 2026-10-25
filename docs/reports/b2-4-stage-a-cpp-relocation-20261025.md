# B2-4 Stage A C++ transport and relocation receipt

Status: **PASS for model-free C++ integration and relocated portable runtime**.

This receipt extends the model-free Stage A package receipt. It does not claim
real Base inference, CUDA synthesis quality, or listening acceptance.

## Provenance

```text
bridge main: 3ffa55588b80824e58e58b8ec745f7abdc4b599a
worktree: chore/b2-4-stage-a-integration
toolchain: Visual Studio 17 2022, MSVC 19.44.35228.0, x64
generator: Visual Studio 17 2022
configuration: Release
```

Build command:

```powershell
cmake -S . -B build/stage-a-integration -G "Visual Studio 17 2022" -A x64
cmake --build build/stage-a-integration --config Release --target qwen_tts_save_wav -- /m:4
```

The resulting `qwen_tts_save_wav.exe` is 450,048 bytes with SHA-256:

```text
DBD264613E432FEDD3D942B15C7DD40CC032A8A8F0E9D38B6B39373E79242B9D
```

The sealed portable package was not rebuilt or modified:

```text
E:\_repoz\qwen3-tts-bridge-cpp\.worktrees\b2-4-pip-completion\dist\QwenTTSBridge\worker-python
files: 35,935
bytes: 5,332,328,507
build-manifest.json: EEAB721B426813545CC82D6624BBE8D432050366266B67BF68463FE2BD514F88
portable-python-tree-manifest.json: 40C9B1431CA5F8903A23C97D89A3CB0CDAB04AF9B12EE646562C5397493E9BBC
```

## C++ transport smoke

Command:

```powershell
.\scripts\test-portable-python-worker-cpp.ps1 `
  -Python py -PythonArgs @('-3.11') `
  -ExampleExe <Release>\qwen_tts_save_wav.exe `
  -WorkerRoot <sealed>\dist\QwenTTSBridge\worker-python `
  -OutputPath .tmp\stage-a-cpp-smoke.wav `
  -MockChunks 2 -MockChunkMs 100
```

Result: **PASS**, exit code `0`.

The C++ client connected to the sealed package, received two mock PCM chunks,
and wrote a non-empty WAV. Validation passed for 9,600 PCM bytes, 24,000 Hz,
mono, 16-bit PCM. Worker lifecycle ended with `completed`,
`termination_reason=eos`, and `hit_eos=true`. The run used the staged Python
runtime and did not depend on the developer virtual environment.

## Relocation

The sealed package was copied, without rebuilding, to:

```text
E:\stage-a-relocated\QwenTTSBridge\worker-python
```

The original package was not changed. The copied `build-manifest.json` and
`portable-python-tree-manifest.json` hashes matched the sealed values above.
The relocated `qwen_tts_doctor.cmd` completed with exit code `0` and reported:

```text
acceptance_pass: true
GPU: NVIDIA CMP 50HX, capability 7.5, driver 581.94, CUDA 12.8
```

The relocated source-path inspection passed with no `source_path_leaks` and no
`module_origin_leaks`; all worker, Qwen, Torch and Transformers origins were
inside the relocated runtime. A packaged mock-worker smoke from the relocated
launcher also passed with two chunks and exit code `0`.

## Base 1.7B prerequisite inventory

The intended external CMP 50HX Base checkpoint is present at:

```text
E:\_repoz\qwen3-tts-bridge-cpp\tmp\cmp50hx-r3-external-models\Qwen3-TTS-12Hz-1.7B-Base
```

The primary `model.safetensors` is 3,857,413,744 bytes with SHA-256:

```text
38FC7FC51C5E776E840414B6FD443962E9411B9654888FD7913E4DA643CB857C
```

The release-facing registered voice candidate is
`kraftwerk_robot_ru_bootstrap_fidelity`, backed by
`examples/assets/voice-profiles/kraftwerk_robot_ru_fidelity.wav` (844,844
bytes, SHA-256
`90E5F7576991EA5B9F0A85E9109F7BD31FF667C4A12D58783A06C650796C3CA1`).
The reference asset is repository-provided and its provenance remains the
experimental character-profile record in `docs/voice-assets-provenance.json`.

This inventory is not a real-model acceptance: a complete external model-file
manifest and deployment-local voice registry still have to be frozen before
starting Base synthesis. No real model, CUDA synthesis, or listening run was
performed here.

## Gate summary

| Gate | Result |
| --- | --- |
| Release C++ binary build | PASS |
| C++ → sealed portable worker mock smoke | PASS |
| Relocated manifest integrity | PASS |
| Relocated doctor | PASS |
| Relocated source-path inspection | PASS |
| Relocated packaged mock smoke | PASS |
| Base 1.7B real synthesis | NOT RUN |
| Listening acceptance | NOT RUN |
| RTX 4090 validation | NOT RUN |
