# B2-4 portable Python acceptance inventory

Date: 2026-10-25  
Bridge main: `66c429bfeab6d8225eb38cc7ac857f602a822004` (post-merge B2-3)  
Target machine: CMP 50HX  
Status: **blocked at external-artifact provisioning**

This is an inventory, not a real-model acceptance receipt. No model weights,
private runtime trees, or generated package output are added to the repository.

## Required external inputs

| Input | Repository contract | Inventory result |
| --- | --- | --- |
| Python 3.11 portable runtime | `scripts/package-python-worker.ps1`, marker `.qtb-portable-worker-root` | **Missing**: `dist/` contains only `.gitkeep` |
| Portable build and runtime-tree manifests | `worker/src/qwen_tts_bridge_worker/doctor.py` | **Missing**: no `build-manifest.json` or runtime tree in `dist/` |
| Base 1.7B model directory | `scripts/test-portable-python-qwen-worker.ps1 -ModelPath/-ModelManifest` | **Missing**: `models/` contains only `.gitkeep` |
| Base model manifest | `doctor.py` model verification contract | **Missing**: no committed or local manifest for the Base checkpoint |
| Registered voice registry | `-VoiceRegistryPath`, `config/voice-profiles.example.json` | **Available as example only**; no local release registry was found |
| Reference audio | `examples/assets/voice-profiles/*.wav` | **Available**: four tracked example WAV profiles; hashes must be captured for the selected release profile |
| Qwen source/runtime dependencies | pinned submodules and lock files | **Available as source inputs**: Qwen streaming/faster-Qwen submodules and packaging lock files; this does not constitute an installed portable runtime |

Historical CMP reports contain model/runtime hashes and prior playback evidence,
but they do not provide the external model tree, portable Python tree, or a
current doctor manifest needed for this gate. They must not be reused as a
substitute for the clean-environment run.

## Model-free checks available now

The following checks run without model weights or CUDA inference:

```text
PYTHONPATH=worker/src
python 3.11 -m unittest \
  tests.python.test_packaging_profile \
  tests.python.test_portable_doctor \
  tests.python.test_runtime_tree_manifest \
  tests.python.test_voice_profiles
```

Result on this worktree: **42 tests passed**.

These checks cover packaging command construction, portable marker and manifest
validation, runtime-tree hashing, model-manifest validation fixtures, and voice
registry parsing. They do not prove that a real Qwen model can load or produce
audio.

The real portable probe remains intentionally unavailable until the external
inputs exist:

```powershell
.\scripts\package-python-worker.ps1 -UseVenv -Clean -IncludeQwenFork
.\scripts\test-portable-python-qwen-worker.ps1 `
  -UseVenv `
  -ModelPath <external Base 1.7B directory> `
  -ModelManifest <matching manifest> `
  -VoiceRegistryPath <release voice registry>
```

The current checkout fails before execution because
`dist/QwenTTSBridge/worker-python/qwen_tts_doctor.cmd` is absent. This is an
expected provisioning failure, not a worker or transport failure.

## Next unblock

Provision, outside Git, one exact Base 1.7B checkpoint and its per-file
SHA-256 manifest, a selected registered voice registry plus reference-WAV
hashes, and a Python 3.11 portable package built from the frozen commit and
submodule pins. Then run the doctor, packaged worker/transport smoke, physical
playback, cancellation/recovery, and listening gates on CMP 50HX. Keep the
RTX 4090 run independent until the CMP artifact bundle is frozen.
