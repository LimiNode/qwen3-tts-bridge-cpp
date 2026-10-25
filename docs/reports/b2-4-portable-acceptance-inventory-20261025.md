# B2-4 portable Python acceptance inventory

Date: 2026-10-25
Bridge main inspected: `66c429bfeab6d8225eb38cc7ac857f602a822004`
Target machine: CMP 50HX
Status: **Stage A not yet executed; Stage B blocked by external artifacts**

This report records only paths inspected in this worktree. It does not claim
that artifacts are absent from every CMP 50HX directory. Model weights,
private runtime trees, and generated package output remain outside Git.

## Two independent acceptance stages

### Stage A — model-free portable acceptance

Stage A does not require a Base 1.7B checkpoint. Once a packaging environment
is provisioned, the reproducible sequence is:

```powershell
.\scripts\setup-python-packaging.ps1 `
  -UseVenv `
  -InstallQwenFork `
  -InstallFasterQwen

.\scripts\package-python-worker.ps1 `
  -UseVenv `
  -Clean `
  -IncludeQwenFork `
  -IncludeFasterQwen

.\scripts\inspect-portable-python-worker.ps1 `
  -WorkerRoot 'dist\QwenTTSBridge\worker-python'

.\scripts\test-portable-python-worker.ps1 `
  -UseVenv `
  -WorkerCommand 'dist\QwenTTSBridge\worker-python\qwen_tts_worker.cmd'

# Optional, when the Release C++ example is already built:
.\scripts\test-portable-python-worker-cpp.ps1 `
  -UseVenv `
  -ExampleExe 'build\default\Release\qwen_tts_save_wav.exe'
```

The first two commands install/package the pinned source dependencies. The
portable package then verifies its marker, build manifest and runtime-tree
hashes; `inspect-portable-python-worker.ps1` checks for source-path leakage;
the worker test runs the packaged **mock** engine; and the optional C++ step
checks transport integration. Paths are quoted so spaces in a checkout do not
change argument boundaries. All generated output belongs under `dist/` and
temporary evidence under `.tmp/`.

Stage A must record the package/runtime hashes and the mock/transport receipt,
but it is not real-model or CUDA acceptance.

### Stage B — real Base 1.7B acceptance

Stage B remains blocked until the external inputs below are provisioned. The
generic portable Qwen probe accepts `-ModelPath` and `-ModelManifest` and a
speaker such as `-Speaker serena`; it does **not** accept
`-VoiceRegistryPath` and does not exercise a registered Base `voice_id`.

The registered Base profile gate belongs to the release runner, which supports
all three arguments together:

```powershell
.\scripts\run-real-model-release-acceptance.ps1 `
  -PlayerPath 'build\default\Release\qwen_tts_play.exe' `
  -PythonPath 'dist\QwenTTSBridge\worker-python\python\python.exe' `
  -CustomVoiceModelPath '<external CustomVoice model directory>' `
  -RuntimeCachePath '.tmp\real-model-runtime-cache' `
  -BaseModelPath '<external Base 1.7B directory>' `
  -VoiceRegistryPath '<external release voice registry.json>' `
  -VoiceId '<registered voice id>'
```

`-BaseModelPath`, `-VoiceRegistryPath`, and `-VoiceId` are an all-or-nothing
group. The runner performs the registered-voice persistent/restart checks;
`-Speaker` in the generic probe is not an equivalent substitute. Keep this
stage marked **NOT RUN/BLOCKED** until the model, manifest, registry and
hardware/listening evidence exist.

## Worktree inventory

| Input | Contract | Result in this worktree |
| --- | --- | --- |
| Python 3.11 portable runtime | `scripts/package-python-worker.ps1`, `.qtb-portable-worker-root` | **Not present**: `dist/` contains only `.gitkeep` |
| Portable build/runtime manifests | `worker/src/qwen_tts_bridge_worker/doctor.py` | **Not present**: no package, `build-manifest.json`, or runtime-tree manifest under `dist/` |
| Base 1.7B checkpoint | `-ModelPath`/`-ModelManifest` and release runner | **Not present in this worktree**: `models/` contains only `.gitkeep`; external CMP paths were not inspected |
| Base model manifest | doctor model verification contract | **Not present in this worktree** |
| Release voice registry | release runner `-VoiceRegistryPath` | `config/voice-profiles.example.json` is present; no local release registry was found in the inspected worktree |
| Reference audio | selected registry profile | Four tracked example WAVs under `examples/assets/voice-profiles/`; release selection and hashes remain to be recorded |
| Qwen/Faster sources | pinned submodules and packaging locks | Present as source inputs; an installed portable runtime is not present |

Historical CMP reports under `docs/reports/` contain prior model/runtime hashes
and playback evidence. They are historical evidence, not the current portable
package, current model manifest, or a substitute for Stage B.

## Model-free validation already executed

On this worktree, with `PYTHONPATH=worker/src` and Python 3.11:

```text
python -m unittest \
  tests.python.test_packaging_profile \
  tests.python.test_portable_doctor \
  tests.python.test_runtime_tree_manifest \
  tests.python.test_voice_profiles
```

Result: **42 tests passed**. These are local checks, not a GitHub CI result.
They cover packaging command construction, marker/manifest validation,
runtime-tree hashing, model-manifest fixtures and voice-registry parsing.

Stage A package/doctor/transport acceptance has not yet run because the
portable output and packaging environment are not present. The current
`test-portable-python-qwen-worker.ps1` path fails first on its required worker
command (`dist/QwenTTSBridge/worker-python/qwen_tts_worker.cmd`); it cannot
reach the doctor or model checks until that package exists.

## Next unblock

Provision the Stage A Python 3.11 packaging environment and run the model-free
sequence above in an isolated worktree. Preserve the package manifest, runtime
hashes and mock/transport receipts. Separately provision one exact Base 1.7B
checkpoint, per-file SHA-256 manifest, release voice registry and reference-WAV
hashes for Stage B. Do not treat Stage A as Base model acceptance, and keep the
RTX 4090 run independent until the CMP artifact bundle is frozen.
