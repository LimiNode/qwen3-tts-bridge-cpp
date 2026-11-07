# Beta RC model-free closeout — 2026-11-03

This is the current follow-up to the [2026-11-02 receipt](beta-rc-model-free-acceptance-20261102.md).
The immutable package source is `b036642ed4c9ede66b94c7d044b6839f3246976f`;
the branch's subsequent changes concern acceptance tooling and documentation.
Runtime files and the release manifest were not regenerated. There is no
release tag or publication.

## Package identity and source pins

The package is the existing
`.worktrees/beta-rc-candidate/.tmp/beta-rc/QwenTTSBridge-release/` under the
primary repository. Its `release-manifest.json` SHA-256 remains
`bcf76c4243682fff7301d067fd92f86b886ca2fb2f15cc633e49cb28227afef8`.
The worker build/tree manifest hashes are preserved in the earlier receipt.
These source pins describe the checkout, not a claim that every optional
engine is installed in this model-free package:

| Submodule | Commit |
| --- | --- |
| nlohmann-json | `55f93686c01528224f448c19128836e7df245f72` |
| qwentts.cpp | `130cb99af9ae12d554962fd0920e08fb4268af01` |
| speech-animation | `5f384d6ce9abcac10cad4ab8a4777ab621d6fe99` |
| tiny-process-library | `8bbb5a211c5c9df8ee69301da9d22fb977b27dc1` |
| tts-front-cpp v0.2.2 | `f828893b46728544041ab577215640338756a9d4` |
| Qwen3-TTS-streaming | `25cc5886a753035ac3ed9d4000440b2e842e5e56` |
| faster-qwen3-tts | `4bdcd3f8d57fabbdc605152c7958e095321a4e46` |

## Argument-probe diagnosis

Windows PowerShell `5.1.26100.8875` and portable PowerShell `7.6.9` were checked
on the same Windows/CMP 50HX host. Three harness issues were distinguished:

1. In 5.1, `@(... | ConvertFrom-Json)` wraps a root JSON array in a second array:
   the old assertion sees one element instead of two. Direct assignment gives
   the two expected strings, byte-for-byte equal after UTF-8 encoding. In 7,
   the original expression already returns two elements. This is the reproduced
   assertion failure, rather than evidence that CMD transcodes these arguments.
2. The UTF-8 script lacked a BOM. PowerShell 5.1 interpreted its Cyrillic
   literals using the local legacy encoding. Adding a UTF-8 BOM makes both
   shells execute the intended Russian test text.
3. The synthetic probe launcher wrote absolute paths using ASCII. It now uses
   `%~dp0argument-probe.py` and an environment variable for Python, so a Unicode
   output/interpreter path is not serialized into an ASCII batch file.

The exact assertion still covers `spaced value` and
`Русский "текст" \path & tail`; stderr and exit code 19 remain asserted.
The existing launcher/`Start-Process` escaping passed this case in both shells;
it was not replaced. This is evidence for the declared probe, not a promise
about every possible Windows command-line metacharacter combination.

## Isolation and complete CLI runs

Each shell runs the complete harness against its own copy of the same package:

- `E:\QwenTTSBridge RC 20261103\ps51 проверка\перенесённый пакет`
- `E:\QwenTTSBridge RC 20261103\ps7 проверка\перенесённый пакет`

These external copies are the explicit outside-checkout isolation exception;
logs and inventory payloads stay in the primary repository's
`.tmp/base-acceptance/beta-rc-closeout-20261103/`. They are local evidence, not
independent backups. No cleanup of unrelated directories was performed.

The caller's `PYTHONPATH` is cleared, user configuration/Hugging Face caches are
empty, offline flags are enabled, and commands run from an unrelated CWD.
The harness verifies all 35,898 manifest entries before adding mock fixtures.
The outside-repository path enables its repository-path leak assertion.
The independent inspector finds no source-path/module-origin leaks; its Python
executable, worker module and `sys.path` resolve inside the relocated package.

| Check | PowerShell 5.1 | PowerShell 7 |
| --- | --- | --- |
| Complete portable CLI harness | PASS | PASS |
| Exact argument probe and stderr/exit propagation | PASS | PASS |

The harness includes model list/verify, voice list/add/verify, mock design,
synth and play, fail-closed explicit runtime selection, invalid commands and
missing arguments, WAV validation and mock terminal EOS. Mock playback does
not exercise an audio device. The separate transport smoke explicitly launches
the relocated package's `bin/qwen_tts_save_wav.exe` and its packaged Python:
PASS, 4,800 PCM bytes, 24 kHz mono PCM16, **mock terminal EOS**.

## Size inventory

`scripts/inspect-portable-release.py` inventories the existing package without
altering dependencies. It finds **5,347,491,489 bytes (4.98 GiB), 35,919 files**.
The difference from 35,898 manifest entries is the manifest itself and 20 mock
model fixture files left by the earlier manual smoke. The manifest deliberately
excludes `models/`. Its four `.safetensors` candidates are each four-byte
fixtures, not actual model weights. This is an inventory of the tested local
package, not a claim that the fixtures are valid models or distribution inputs.

| Component | Bytes |
| --- | ---: |
| `worker-python/` | 5,331,727,271 |
| Python core, excluding site-packages | 133,061,829 |
| site-packages (within worker total) | 5,192,690,402 |
| torch (within site-packages) | 4,522,037,003 |
| torch/lib, including CUDA DLLs (within torch) | 4,435,159,806 |
| `bin/` | 997,888 |
| `config/` | 814 |
| `models/` mock fixtures | 226 |
| `qwen-tts.cmd` | 357 |
| `release-manifest.json` | 14,764,893 |
| Release marker | 40 |

The ten largest files, all under `worker-python/python/Lib/site-packages/torch/lib/`:

| File | Bytes |
| --- | ---: |
| torch_cuda.dll | 908,188,672 |
| cublasLt64_12.dll | 674,667,520 |
| cudnn_engines_precompiled64_9.dll | 513,926,688 |
| cusparse64_12.dll | 379,535,872 |
| cudnn_adv64_9.dll | 282,445,872 |
| cufft64_11.dll | 276,121,600 |
| torch_cpu.dll | 265,089,024 |
| cusolver64_11.dll | 225,683,456 |
| cusolverMg64_11.dll | 157,071,360 |
| cudnn_ops64_9.dll | 126,508,576 |

Manifest-hash duplicate candidates of at least 1 MiB are Python's
`Doc/html/NEWS` / `NEWS.txt` (1,563,659 bytes each) and torch's
`_C/_VariableFunctions.pyi` / `_VF.pyi` (1,242,210 bytes each). No large duplicated
CUDA DLL group was found at that threshold. Smaller duplicates were not audited.
No `__pycache__`, `.cache`, `.pytest_cache` or `.git` payload files were found.
The checkout-path scan found no matches in UTF-8 Python/JSON/text/PTH/CMD/CFG/INI
files; it does not inspect binary debug strings. Optional/dev packages such as
Gradio and Nuitka remain installed; no dependency trimming was attempted.

## Model/runtime prerequisites and beta gates

The local Base snapshot
`C:\Users\User\.cache\huggingface\hub\models--Qwen--Qwen3-TTS-12Hz-1.7B-Base\snapshots\fd4b254389122332181a7c3db7f27e918eec64e3`
has **13 files, 4,544,229,700 bytes**. All sizes/SHA-256 hashes match the protected
historical `qwen3-tts-12hz-1.7b-base-manifest.json`, directory-manifest hash
`d47209b486d4e6929a554e09f5be87803309be68387ac075c0b1f7e62a1f7d66`.
No weights were downloaded. The manifest's revision is null; the snapshot
directory identifies the local revision and is not rewritten into the old manifest.

However, `inspect-portable-python-worker.ps1 -ProbeQwenImport` fails with
`ModuleNotFoundError: No module named 'qwen_tts'`. The build manifest has only
the bridge-worker wheel, and no Qwen/Faster runtime package is installed.
The earlier inspector PASS was a worker/isolation probe without this option.
This candidate cannot perform real Base synthesis until a new runtime-complete
package is assembled and sealed. Its new hashes will require fresh portable
acceptance; the present mock results cannot be transferred to it.

| Gate | Current result |
| --- | --- |
| C++ SDK/build and installed consumers | 28/28 CTest rerun PASS; both installed consumers previously PASS |
| Isolated model-free portable CLI | PASS in both shells |
| Complete Base 1.7B checkpoint availability | PASS: local 13-file manifest verification |
| Qwen/Faster imports in this exact RC package | FAIL: runtime not provisioned |
| Real CMP 50HX synthesis from this RC | NOT RUN: runtime prerequisite fails |
| Real-model PCM / natural EOS | NOT RUN for this RC |
| Physical playback | NOT RUN for this RC |
| Human listening | NOT RUN for this RC |
| PR #231 / frontend v0.2.3 | DEFERRED for this beta; keep v0.2.2 |
| RTX 4090 | DEFERRED to the next beta; not a blocker for this beta |
| Publication | BLOCKED_RUNTIME_AND_REAL_ACCEPTANCE; no tag/release |

PR #231 is still Open/Draft at `489d8cc329f09ec70ea40cf060353b90413feffb`.
Its report has no targeted listening receipt for `ru_genitive_decimal`.
The current beta keeps its accepted v0.2.2 pin; the v0.2.3 change is not needed
to close the mechanical CLI gate. This RC does not silently integrate #231 or
transfer earlier Base/VoiceDesign listening verdicts to new artifacts.

Before publication: include the pinned Qwen/Faster runtime through the existing
packaging path, freeze and verify new manifests outside the checkout, then run
the registered Base voice through persistent sequential synthesis, active
cancellation/recovery and restart, PCM/natural-EOS checks, physical playback
and scoped human listening on CMP 50HX. Preserve input/voice/model/runtime
hashes, latency and exact WAV hashes in a new canonical receipt/index entry.
Checkpoint availability no longer warrants `BETA_BLOCKED_MODEL_ARTIFACT` on
this machine; runtime provisioning and actual acceptance are the remaining gates.

## Reproduction and raw evidence

From `.worktrees/beta-rc-candidate` (use the installed Python 3.11 path for
`$python`, and the recorded portable `pwsh.exe` for `$pwsh`):

```powershell
$source = ".tmp/beta-rc/QwenTTSBridge-release"
$env:PYTHONPATH = $null
$env:HF_HUB_OFFLINE = "1"
$env:TRANSFORMERS_OFFLINE = "1"
# For each fresh run, also set HF_HOME to a fresh empty directory under .tmp.
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/test-portable-user-cli.ps1 `
  -PackageRoot $source -OutputRoot "E:\QwenTTSBridge RC 20261103\ps51 проверка" -Python $python
& $pwsh -NoProfile -File scripts/test-portable-user-cli.ps1 `
  -PackageRoot $source -OutputRoot "E:\QwenTTSBridge RC 20261103\ps7 проверка" -Python $python
python scripts/inspect-portable-release.py $source --forbidden-root "E:\_repoz\qwen3-tts-bridge-cpp"
& $pwsh -NoProfile -File scripts/inspect-portable-python-worker.ps1 `
  -WorkerRoot "E:\QwenTTSBridge RC 20261103\ps7 проверка\перенесённый пакет\worker-python" `
  -ForbiddenRoots "E:\_repoz\qwen3-tts-bridge-cpp"
& $pwsh -NoProfile -File scripts/test-portable-python-worker-cpp.ps1 -Python $python `
  -ExampleExe "E:\QwenTTSBridge RC 20261103\ps7 проверка\перенесённый пакет\bin\qwen_tts_save_wav.exe" `
  -WorkerRoot "E:\QwenTTSBridge RC 20261103\ps7 проверка\перенесённый пакет\worker-python" `
  -OutputPath "E:\_repoz\qwen3-tts-bridge-cpp\.tmp\base-acceptance\beta-rc-closeout-20261103\packaged-cpp\mock.wav"
ctest --test-dir .build/beta-rc-msvc -C Release --output-on-failure
python scripts/validate-acceptance-receipts.py
git diff --check
```

The harness refuses existing output unless explicitly marker-checked with
`-Clean`; prefer a fresh run directory. Raw logs, inventories and the original
probe reproductions are in the local evidence directory described above.
An inventory fixture also checked total/component sizes and weight/cache/path
detection. The tracked report records the observations; ignored payloads are
not independently inspectable through GitHub.

Raw payload identities (relative to that evidence directory; PowerShell output
redirection produced UTF-16 logs/JSON):

| Payload | Bytes | SHA-256 |
| --- | ---: | --- |
| portable-cli-ps51.log | 1,618 | `fa9d0c2a006dd7a323b8b8dfd21b65626df7e06059e94711c874b42737dbd6fc` |
| portable-cli-ps7.log | 1,588 | `5baddda8294ea276a5d508b252d53b2680e7c918a51e26cd99dbc5ccbb368447` |
| package-inventory-final.json | 7,108 | `b96a308a266f95576fc1394ab3bd525447a2b4148de829cc4c379bbdfacf09be` |
| isolated-worker-inspector.log | 7,490 | `fa2b517702bbbd7d0b8fd5ef154f3af5244d085ab569d46baca57089a8546eb6` |
| base-inventory.json | 932 | `ff959c95ec77cfce7f8232ae986e1fcceb01b8d0ca0ca17128530d586904950b` |
| ctest.log | 8,128 | `50225fdd2e64a1f20895baee42ded50b35cf672d1458ba72b22ea6ba9ea95e82` |
