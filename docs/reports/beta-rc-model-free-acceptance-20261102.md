# Beta RC model-free acceptance — 2026-11-02

This receipt covers the model-free release-candidate checks performed on
`release/beta-rc-candidate` at source revision
`b036642ed4c9ede66b94c7d044b6839f3246976f`.

The receipt does not claim real-model quality, RTX 4090 acceptance, or a
release tag. Model weights were not downloaded.

## Build and SDK checks

- MSVC x64 Release build: PASS (text frontend ON, WinMM ON, examples and tests
  ON; native and speech-animation backends OFF).
- CTest: `28/28 PASS`.
- Installed consumer with text frontend ON + WinMM: compile/link/run PASS.
- Installed consumer with text frontend OFF + WinMM: compile/link/run PASS;
  text frontend headers/target absent.
- `qwen_tts_play.exe --help`: PASS.

## Portable package

Package roots are intentionally under ignored `.tmp`:

- worker package: `.tmp/beta-rc/QwenTTSBridge`
- assembled release: `.tmp/beta-rc/QwenTTSBridge-release`

The staged worker package is approximately 5.33 GB (4.97 GiB) and uses Python
3.11.9, Torch `2.10.0+cu128`, and CUDA runtime 12.8. No real model weights are
included; the follow-up inventory distinguishes leftover mock fixtures.

| Artifact | Size | SHA-256 |
| --- | ---: | --- |
| `worker-python/build-manifest.json` | 6,739 | `bdaf9afe7a633dcbba6c6b3b9511a55ca252ea07c5fd4c4f5f2edfe3cae4609d` |
| `worker-python/portable-python-tree-manifest.json` | 5,871,763 | `1ce52bf4c042d69cb511897204084bca712d33adfe49236f898d08a9da3fb90a` |
| `release-manifest.json` | 14,764,893 | `bcf76c4243682fff7301d067fd92f86b886ca2fb2f15cc633e49cb28227afef8` |

Checks:

- `test-portable-python-worker.ps1`: PASS on CMP 50HX (CUDA visible; mock
  worker smoke).
- `test-portable-python-worker-cpp.ps1`: PASS (4,800 PCM bytes, 24 kHz mono
  PCM16, mock terminal EOS).
- `inspect-portable-python-worker.ps1`: PASS; no repository source-path leaks.

## Relocated CLI smoke

Using the assembled package from an unrelated working directory and empty
user/Hugging Face caches:

- `models list --json`: PASS (portable dummy model inventory).
- `voices add` and `voices verify --backend python`: PASS.
- `design --acceptance-mock-worker`: PASS; WAV and receipt valid.
- `synth --acceptance-mock-worker`: PASS; WAV and receipt valid.
- `play --acceptance-mock-worker --acceptance-mock-playback`: PASS and quiet.
- Explicit missing `--save-wav-executable`: fails closed as expected.
- Both mock WAVs: 3,840 PCM bytes, 24 kHz mono PCM16; receipt reports
  `terminal_state=completed`, `termination_reason=eos`, and `hit_eos=true`.

The full `test-portable-user-cli.ps1` was also attempted. This historical run
reached the final argument-probe assertion but failed under Windows PowerShell
5.1. Its initial suspected cause was Unicode forwarding through PowerShell/CMD;
that attribution was not established by this run. The complete harness result
was INCOMPLETE, even though earlier package, registry, mock synthesis/playback,
fail-closed, and manifest checks passed. See the
[2026-11-03 closeout](beta-rc-model-free-closeout-20261103.md) for the subsequent
reproduction, corrected diagnosis, and current gate statuses.

## Open gates

- Real Base/VoiceDesign model acceptance: NOT RUN in this receipt.
- Human listening: NOT RUN in this receipt.
- RTX 4090 acceptance: DEFERRED to the second PC.
- PR #231 text-frontend listening decision: separate, still Draft.
- No release tag or publication was performed.
