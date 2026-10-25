# B2-4 Stage A portable-package receipt

Status: **PASS for the model-free portable Python package on CMP 50HX**.

This receipt does not claim Base-model inference, CUDA synthesis, listening
acceptance, or the separate PR #231 hardware gate.

## Provenance

```text
main: 21c8cf48a0d2e57e6db86af0ae518c699793d93f
Python: 3.11.9
venv pip: 24.0
torch: 2.10.0+cu128
torchaudio: 2.10.0+cu128
Qwen3-TTS-streaming: 25cc5886a753035ac3ed9d4000440b2e842e5e56
faster-qwen3-tts: 90b596d2ffa41eb2da173db92e6f896df11b19cb
GPU probe: NVIDIA CMP 50HX, compute capability 7.5, driver 581.94
```

The exact locked install ran in a fresh venv with temporary staging redirected
to E:. It started at `2026-10-25T12:52:35.4426806Z`, completed at
`2026-10-25T13:01:11.5350904Z`, and returned `exit_code=0` (about 516 seconds).
The canonical setup then installed both pinned editable Qwen sources without
changing the lock or packaging scripts. `pip check` passed.

## Portable package

Command:

```powershell
.\scripts\package-python-worker.ps1 `
  -UseVenv -VenvPath '.tmp\pip-completion\venv' `
  -OutputRoot 'dist\QwenTTSBridge' -Clean `
  -IncludeQwenFork -IncludeFasterQwen
```

The resulting local package is under `dist/QwenTTSBridge/worker-python`.
It contains 35,935 files totaling approximately 5.33 GB, including:

- `.qtb-portable-worker-root` marker;
- `build-manifest.json`;
- `portable-python-tree-manifest.json`;
- `qwen_tts_worker.cmd`;
- `qwen_tts_doctor.cmd`;
- pinned Qwen and Faster-Qwen wheel artifacts and source provenance.

Manifest hashes:

```text
build-manifest.json:
EEAB721B426813545CC82D6624BBE8D432050366266B67BF68463FE2BD514F88

portable-python-tree-manifest.json:
40C9B1431CA5F8903A23C97D89A3CB0CDAB04AF9B12EE646562C5397493E9BBC
```

The package's own staging isolation probe and portable-path checks passed. No
absolute worktree path was found in the scanned text payloads, and no `.pyc`
or `.pyo` files remained.

## Acceptance checks

| Check | Result |
| --- | --- |
| exact locked distributions | PASS |
| `pip check` | PASS |
| Qwen/Faster editable source identity | PASS |
| portable marker and build manifest | PASS |
| runtime-tree manifest build and verify | PASS |
| portable doctor | PASS (`acceptance_pass: true`) |
| packaged mock-worker smoke, 2 chunks | PASS |
| C++ transport smoke | NOT RUN — no Release transport binary exists in this clean worktree |
| model files / real inference / listening | NOT RUN by Stage A design |

The doctor reported CUDA availability and the CMP 50HX identity, but no model
was provided and no synthesis was executed. The mock smoke used
`qwen_tts_worker.cmd` and completed successfully.

## Decision

The earlier Stage A blocker was the bounded provisioning budget, not a package
or dependency defect. A sufficiently long run completed the exact locked
environment, and the canonical portable package path now passes its model-free
checks. Stage A can be closed as **PASS** for this machine and package receipt.

The following remain separate gates:

- real Base 1.7B model provisioning and playback;
- CUDA/quality/listening acceptance;
- C++ transport smoke when a Release binary is available;
- independent RTX 4090 validation after candidate freeze.
