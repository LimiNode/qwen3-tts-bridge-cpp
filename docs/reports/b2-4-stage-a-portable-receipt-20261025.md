# B2-4 Stage A portable receipt

Date: 2026-10-25  
Bridge main: `cbc6d76006ab0dbd538015d8697e0b5d6864d4a8`  
Worktree: `feat/b2-4-stage-a`  
Target: CMP 50HX  
Status: **BLOCKED during packaging-environment setup**

This receipt records a model-free attempt only. No model was downloaded or
loaded, no CUDA inference was run, and no real-model or listening result is
claimed.

## Source identity

The clean worktree was created from `origin/main` after B2-4 merge. All pinned
submodules were initialized successfully:

| Dependency | Commit |
| --- | --- |
| `external/cpp/nlohmann-json` | `55f93686c01528224f448c19128836e7df245f72` |
| `external/cpp/qwentts.cpp` | `130cb99af9ae12d554962fd0920e08fb4268af01` |
| `external/cpp/speech-animation` | `5f384d6ce9abcac10cad4ab8a4777ab621d6fe99` |
| `external/cpp/tiny-process-library` | `8bbb5a211c5c9df8ee69301da9d22fb977b27dc1` |
| `external/cpp/tts-front-cpp` | `f828893b46728544041ab577215640338756a9d4` |
| `external/python/Qwen3-TTS-streaming` | `25cc5886a753035ac3ed9d4000440b2e842e5e56` |
| `external/python/faster-qwen3-tts` | `90b596d2ffa41eb2da173db92e6f896df11b19cb` |

The `speech-animation` row above is the exact submodule SHA reported by
`git submodule status`; the repository path is intentionally not inferred from
the remote branch label.

## Environment setup

Host Python: `3.11.9`  
Packaging venv: `.venv-packaging`  
Disk available before setup: approximately 79 GB on `E:`

Canonical command attempted:

```powershell
.\scripts\setup-python-packaging.ps1 `
  -UseVenv `
  -InstallQwenFork `
  -InstallFasterQwen
```

The first attempt ran for 604 seconds and timed out while executing the
locked-requirements installation (`pip install -r worker/requirements-packaging.lock.txt -e worker`). A second attempt made no progress and was stopped after the
pip process became idle without network connections. Only the processes created
by this receipt were stopped.

The partially prepared venv reports:

```text
pip check: No broken requirements found.
qwen_tts_bridge_worker: importable
torch: importable
qwen_tts: not installed
faster_qwen3_tts: not installed
```

This is insufficient for packaging with the selected Qwen/Faster source
profiles. No manual installation was substituted for the canonical setup.

## Stage A execution status

| Gate | Result | Evidence |
| --- | --- | --- |
| pinned submodule initialization | PASS | all seven entries checked out at the SHAs above |
| Python 3.11 packaging venv | PARTIAL | `.venv-packaging` exists; setup command did not complete |
| package build and marker | NOT RUN | `dist/` contains only `.gitkeep` |
| build/runtime-tree manifests | NOT RUN | no portable package was produced |
| portable doctor | NOT RUN | `qwen_tts_doctor.cmd` is absent |
| source-path leakage inspection | NOT RUN | no portable package was produced |
| packaged mock-worker smoke | NOT RUN | no `qwen_tts_worker.cmd` is present |
| optional C++ transport smoke | NOT RUN | no portable package and no Release example were available |

Model-free unit coverage was rerun locally with Python 3.11 and
`PYTHONPATH=worker/src`:

```text
tests.python.test_packaging_profile
tests.python.test_portable_doctor
tests.python.test_runtime_tree_manifest
tests.python.test_voice_profiles
42 tests passed
```

These tests validate packaging/manifest/registry logic and do not constitute
portable-package acceptance.

## Classification and unblock

The current blocker is **packaging-environment provisioning**, before package
construction. It is not a worker, transport, model-quality, or CUDA failure.

Resume Stage A by completing the same `setup-python-packaging.ps1` command in an
environment where the locked dependency installation finishes. Then run the
documented `package → inspect → doctor → mock-worker → optional C++ transport`
sequence and capture package/runtime hashes, commands, exit codes and receipts.
Stage B1/B2 real Base acceptance remains independent and blocked until its
external checkpoint, model manifest, voice registry and hardware/listening
inputs are provisioned.
