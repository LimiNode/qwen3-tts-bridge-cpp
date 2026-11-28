# RTX 4090 independent native A/B run

Status: artifact identities finalized; independent RTX 4090 execution remains
`not_run` by this preparation task. Use only the exact sealed artifacts below.
No release, tag, model-algorithm change or global dtype/default change is requested.

- Source: `aa2770ec8aeb45d59f42c96c3a1f4f2dc52390d8`.
- ZIP: `QwenTTSBridge-native-aa2770ec.zip`.
- ZIP SHA-256: `f9f810092efb5683d7f7a52648989efa82d84f30b4f5d3e7647205acd2f80175`.
- Build receipt: `package-build-provenance.json` from this same build.
- Build receipt SHA-256: `cc9e2688cbb59a6b81c87d8ad1ba3e0059469843288f001d8a8f6e0e241adc58`.
- Runner SHA-256: `b7e7adc5bec9d73f4cde7ef4abd4d7b6a89a05c8e991f9c83fb9767ac1aa698f`.
- Runtime: `130cb99af9ae12d554962fd0920e08fb4268af01`, ABI 6.
- Frontend: `64f73182d26de60af6c082724b1b199eb7310620`.
- Voice: `kraftwerk_robot_ru_bootstrap_fidelity`, supplied WAV-only registry.

## Exact transfer inventory

Put the following files below the second PC's task directory, preserving
relative paths. The voice files are transferred privately and are not package
assets or source-controlled fixtures.

| Relative path | Bytes | SHA-256 |
| --- | ---: | --- |
| QwenTTSBridge-native-aa2770ec.zip | 436027391 | f9f810092efb5683d7f7a52648989efa82d84f30b4f5d3e7647205acd2f80175 |
| package-build-provenance.json | 13566 | cc9e2688cbb59a6b81c87d8ad1ba3e0059469843288f001d8a8f6e0e241adc58 |
| run-native-ab.ps1 | 21196 | b7e7adc5bec9d73f4cde7ef4abd4d7b6a89a05c8e991f9c83fb9767ac1aa698f |
| corpus.json | 6636 | dd8ede87f57bb12645dc05d1b4c44b7e7f89798d30a1a9a7829c05e26b806f58 |
| voice/registry.json | 578 | 1906bae1c02857e5bb716be3be6e103c4c7a6c6c86dec237a1a09b49a0770977 |
| voice/reference.wav | 844844 | 90e5f7576991ea5b9f0a85e9109f7bd31ff667c4a12d58783a06c650796c3ca1 |

ZIP unpacked size: 580257839 bytes. Reserve space for extraction and retained
WAVs/logs; never free space by deleting historical evidence or model files.

## Checklist

1. On the second PC, keep preparation and all new evidence under that checkout's
   `.tmp/base-acceptance/native-r1-aa2770ec-20261120/`. Do not create sibling,
   system-temp or outside-repository acceptance directories. Keep models under
   that checkout's ignored `models/` tree.
2. Obtain the exact frozen ZIP, build receipt, `run-native-ab.ps1`, `corpus.json`,
   `voice/registry.json` and `voice/reference.wav`. Transfer the reference WAV
   privately; it is not a redistributable package asset. Preserve the exact
   transcript and compare reference/registry SHA-256 with the first-PC inventory.
3. Hash the ZIP before extraction. Extract freshly into the repository-local
   `relocated bundle` folder, including the space. Do not copy developer build
   directories, fake DLLs, Python runtimes, historical ZIPs or test-hook binaries.
   The dependency audit requires installed MSVC runtime files `MSVCP140.dll`,
   `VCRUNTIME140.dll`, `VCRUNTIME140_1.dll` and a suitable NVIDIA driver.
   Do not copy arbitrary system DLLs into the package to bypass diagnostics.
4. Provision the three exact converted native model files. Do not rename or
   substitute the published ONNX codec or an unconverted GGUF. Expected hashes:

   | File relative to models/ | SHA-256 |
   | --- | --- |
   | ru-stress/qwen-talker-1.7b-ru-stress-Q8_0.gguf | f4672741608d145fae169075cb0ec775a5382cbe9183eccb59c7ab9cc4797427 |
   | qwen-talker-1.7b-base-Q8_0.gguf | 4b9a33a236908dd9435a42f7a396e38038329d053b704342a6413c08544c4fda |
   | common/qwen-tokenizer-12hz-Q8_0.gguf | 1883beeed99348fc35e23dd225e9082f93f6f8c109330a33d935baa8acdbfd94 |

5. Query `nvidia-smi --query-gpu=uuid,name,driver_version,memory.total --format=csv,noheader`.
   Confirm the requested device is RTX 4090. The historical UUID was
   `GPU-8d35c3f3-83b4-de78-56c2-5b9aa1edf721`; do not assume it without checking.
   Record Windows/toolchain/runtime metadata from the supplied package receipt
   and the actual local GPU/driver inventory.
6. Run one smoke case first; inspect the exact original/effective text,
   terminal JSON, WAV and logs. Then run the complete 52-entry matrix with a
   different new run ID. Never rerun into an existing run directory.
7. Return the entire run directory with its provenance, logs, WAVs and index.
   Report every failed and not-run gate. Do not hide a failure by deleting the
   directory or reporting only a later successful run.
8. Leave all human-listening fields `not_assessed`; the user will listen to the
   exact hashed WAVs. Persistent-worker repeats, cancellation, recovery,
   formal restart, peak memory and client TTFA are not exercised by this runner.
   They require the separate native lifecycle/hardware procedure, not invented
   success fields.

## PowerShell commands (no Python)

Adjust only this machine's checkout path, package path, build receipt path and
verified GPU UUID. Use the identical ZIP/corpus/models/settings as CMP 50HX.

```powershell
$repo = (Get-Location).Path # Start in the second PC's bridge checkout.
$task = Join-Path $repo '.tmp/base-acceptance/native-r1-aa2770ec-20261120'
$zip = Join-Path $task 'QwenTTSBridge-native-aa2770ec.zip'
$bundle = Join-Path $task 'relocated bundle'
$build = Join-Path $task 'package-build-provenance.json'
$sha = 'f9f810092efb5683d7f7a52648989efa82d84f30b4f5d3e7647205acd2f80175'
$gpu = 'GPU-8d35c3f3-83b4-de78-56c2-5b9aa1edf721' # Verify against nvidia-smi first.

& (Join-Path $task 'run-native-ab.ps1') -PackageRoot $bundle -PackageZip $zip `
  -PackageBuildReceipt $build -ExpectedZipSha256 $sha -ModelRoot (Join-Path $repo 'models') `
  -GpuLabel RTX4090 -GpuUuid $gpu -RunId rtx4090-smoke-001 `
  -ModelProfile ru-stress -Frontend front -CaseId ru-ordinary

# Full matrix: a new worker per case; 48 positive plain cases + 2 stress + 2 rejection.
& (Join-Path $task 'run-native-ab.ps1') -PackageRoot $bundle -PackageZip $zip `
  -PackageBuildReceipt $build -ExpectedZipSha256 $sha -ModelRoot (Join-Path $repo 'models') `
  -GpuLabel RTX4090 -GpuUuid $gpu -RunId rtx4090-matrix-001
```

The commands do not close R1 release gates on their own. Relocation is still
inside a checkout; literal clean-host/outside-checkout qualification remains
`not_run` under the current repository-local directory restriction.
The native runtime in this build was reused with manifest/hash verification,
not rebuilt. Human listening and the exact bundled `vcomp140.dll` 14.50
redistribution/legal scope remain `not_assessed`. CMP 50HX execution/status is
owned by the separate live matrix and its canonical receipt, not this handoff.

## Verification and fresh extraction

Run the following after assigning `$task`, `$zip`, `$bundle` and `$build` as
above, but before either synthesis command. This is an artifact integrity
check, not a new inference harness.

```powershell
$expected = [ordered]@{
  'QwenTTSBridge-native-aa2770ec.zip' = 'f9f810092efb5683d7f7a52648989efa82d84f30b4f5d3e7647205acd2f80175'
  'package-build-provenance.json' = 'cc9e2688cbb59a6b81c87d8ad1ba3e0059469843288f001d8a8f6e0e241adc58'
  'run-native-ab.ps1' = 'b7e7adc5bec9d73f4cde7ef4abd4d7b6a89a05c8e991f9c83fb9767ac1aa698f'
  'corpus.json' = 'dd8ede87f57bb12645dc05d1b4c44b7e7f89798d30a1a9a7829c05e26b806f58'
  'voice/registry.json' = '1906bae1c02857e5bb716be3be6e103c4c7a6c6c86dec237a1a09b49a0770977'
  'voice/reference.wav' = '90e5f7576991ea5b9f0a85e9109f7bd31ff667c4a12d58783a06c650796c3ca1'
}
foreach ($relative in $expected.Keys) {
  $actual = (Get-FileHash -LiteralPath (Join-Path $task $relative) -Algorithm SHA256).Hash
  if ($actual -ne $expected[$relative]) { throw "Hash mismatch: $relative" }
}
if (Test-Path -LiteralPath $bundle) { throw 'Refusing existing extraction directory' }
Expand-Archive -LiteralPath $zip -DestinationPath $bundle
& (Join-Path $task 'run-native-ab.ps1') -ListCases
```

The exact UTF-8 corpus is also retained at
[`../acceptance/native-r1-aa2770ec-corpus.json`](../acceptance/native-r1-aa2770ec-corpus.json).
Copy it as `corpus.json` beside the transferred runner, preserving its hash.
The runner is an ignored diagnostic payload transferred by its exact hash;
it is not a new supported product CLI or a second inference engine.

## Separate raw lifecycle/resource qualification

After the A/B runner releases the GPU, transfer these additional private
diagnostic files under the same task's `lifecycle/` directory. They are not
shipping ZIP assets and must not be substituted into `bin/`:

| File | SHA-256 |
| --- | --- |
| `run-native-lifecycle.ps1` | `487e4ac0f006a77be049200b922da32f79663a0e44e6dabba137c68c615d73e1` |
| `sample-processes.ps1` | `041b88ca434b0dbb625d3b9d67a3760cf639202c067064ddc85b4f1f1cc7c5d0` |
| `qwen_tts_latency_benchmark.exe` (503296 bytes) | `57093572263483c390aaeeeacb842ad546ad5ab008a42f50e5f51e9307111437` |

The existing benchmark was built from exact `aa2770ec`, MSVC 19.44 Release,
tests/hooks OFF. Its first-PC source is
`.worktrees/native-cli-acceptance/.build/native-aa2770ec-release/Release/`.
Verify all three hashes before running; do not rebuild a different source and
silently reuse this inventory. With the same verified `$gpu`/`$task`:

```powershell
& (Join-Path $task 'lifecycle/run-native-lifecycle.ps1') `
  -BenchmarkPath (Join-Path $task 'lifecycle/qwen_tts_latency_benchmark.exe')

# The command above is plan-only; execution requires the explicit switch.
& (Join-Path $task 'lifecycle/run-native-lifecycle.ps1') -Execute `
  -BenchmarkPath (Join-Path $task 'lifecycle/qwen_tts_latency_benchmark.exe') `
  -GpuLabel RTX4090 -GpuUuid $gpu -RunId qualification-01
```

For each profile: 3 warmups, 30 measured requests, six cancellations after
first PCM, same-worker post-cancel requests, then 3 requests on a distinct fresh
worker without warmup. The independent watchdogs are bounded; owned subprocess
cleanup, JSON, stderr, module paths and memory samples are retained. Do not run
concurrently with the A/B matrix or another GPU workload. Supply a new run ID
for another experiment; preserve failures.

This is raw four-text RU/EN client/worker qualification, not frontend, WAV,
physical-playback or full-corpus quality acceptance. TTFA starts at submission
after ready, excluding process startup/model load. GPU memory is sampled
device-wide use, not process-exclusive VRAM or an instantaneous peak. Per-WAV
resources, forced-crash recovery, soak/leak and listening remain separate gates.
Return the entire lifecycle directory, including failed or incomplete phases.

## Evidence boundary

The runner retains original/effective text, launcher invocation, native
stdout/stderr, worker metrics, WAV/terminal JSON and hashed case receipts.
It requires natural EOS and valid PCM16 mono 24 kHz WAVs. Successful completion
is not proof of accent accuracy, intelligibility or voice similarity.
Worker `first_chunk_callback_ms`, `synthesis_ms` and derived worker RTF must
not be described as client TTFA or end-to-end RTF. Measurements absent from
the independent RTX run remain `not_run`; CMP observations do not transfer.

This handoff is an assignment and frozen transfer inventory, not a canonical
acceptance receipt. The completed CMP 50HX run, source/CI closeout and tracked
acceptance index are maintained separately by the root task. Return failures,
not-run gates and complete artifacts without editing that earlier evidence.
