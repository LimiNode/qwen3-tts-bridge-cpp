# Native R1 post-merge qualification, 2026-11-20

Status: **NO-GO for public release**. The source/package candidate is frozen;
hardware qualification and human listening are separate gates. No release,
tag, R2 feature, model algorithm, protocol, or dependency pin was changed.

## Source and CI

- Baseline merged PR #327: `b9660576ece29eab2c4d97d6d00afe6b248f7e86`.
- Test correction #328: `2fccd4936c7236cfba3dbced692771b9c7d59c26`, merged
  as `2a24db15dd52cb29d223e3ac949da8b6fe179e55`.
- Launcher/package #329 exact head:
  `5234aa879964c2e9de781ba338a5eec834e58343`.
- Frozen merged source candidate:
  `aa2770ec8aeb45d59f42c96c3a1f4f2dc52390d8`.
- [Exact candidate C++ CI](https://github.com/LimiNode/qwen3-tts-bridge-cpp/actions/runs/44657104799):
  7/7 jobs success. CTest: default 42/42; native-worker 28/28; no-examples
  24/24; speech-animation 27/27; speech-animation-player 46/46; native ABI 33/33.
- [Exact candidate Python CI](https://github.com/LimiNode/qwen3-tts-bridge-cpp/actions/runs/44657104842):
  success; 509 tests, 6 skipped, Ruff pass, Pyright 0 errors.

PRs #321-#327 remain closed; superseded heads were not re-merged. A later
receipt/handoff-only commit is not a new binary candidate. The ZIP below keeps
the exact source identity above; do not regenerate it merely to embed its own
receipt commit.

## Fatal/stderr CI diagnosis

The original failing job was `135837916915` in workflow `44602661270`.
On exact baseline MSVC Release, the focused scenario failed 2/30 runs. A
dedicated receipt captured `all_terminal_errors_observed`, rather than only
the parent watchdog's nonzero child exit code.

The test deliberately blocked `StdIoTransport.stderr_handler`, but stderr and
Receive events share the transport callback dispatcher. Consequently the test
blocked the terminal frames it was waiting for. Success depended on whether
terminal frames preceded the diagnostic filler. The adjacent after-fatal
scenario had the same harness defect. This is not evidence of a production
fatal-path defect.

The corrective reuses independent Win32 pipes: stderr remains unread while
stdout drains. Explicit fake-engine barriers and both pending `Queued` events
establish admission before releasing the injected active callback failure.
The test requires exactly one expected Error for all three requests, no PCM,
fatal process exit 1, and bounded teardown. An unrelated harness race now
treats pipe EOF before process-handle signalling as EOF, while retaining the
existing exit deadline. Failure diagnostics use an independent retained file.
No production source or timeout was changed; duplicate harness code was removed.

Final Release and Debug each passed 30 prefill and 30 after-fatal watchdog
executions, plus 3/3 complete native-worker runs. Release callback, stdout
integrity and stdio suites also passed 3/3. The historical failed workflow was
rerun successfully after diagnosis; that rerun is not the evidence for the
corrective, whose own PR and post-merge workflows passed separately.

## Local model-free qualification

These full local builds are on correction `2fccd493`, not falsely attributed
to the later launcher-only merged source:

| Configuration | Full CTest | Log SHA-256 |
| --- | --- | --- |
| MSVC 19.44 x64 Release | 46/46 | `2f231d03a45393a4ed2cc9a4aaab6804676a6f1ff240b59c5f7b4221e61e6567` |
| MSVC 19.44 x64 Debug | 46/46 | `77212a95ba1060040793889af08a970cd9b33d7d7b731207a938d9bc8e9175e5` |
| MinGW GNU 15.2 Release | 46/46 | `27dd0dbc413865578cdf8d3c7753f74e3d3ae423a1b00bd35d6c2c702189f789` |

Installed C++17 consumer with frontend and WinMM: build/run pass. Separate
production worker with tests/hooks disabled: 0/9 test-hook identifiers versus
9/9 in the instrumented positive control. No dependency pins changed.

On the final launcher source, the local supported base Python 3.11 interpreter
passed 509 tests, 7 skipped; Ruff 0.15.20 passed; Pyright 1.1.411 reported no
errors or warnings. The different skip count is environment-specific. An
earlier unsupported Python 3.14 attempt and a Windows venv-launcher termination
test failure are retained, superseded by the supported direct-interpreter run;
they are not claimed as native runtime defects.

## Frozen package

Local ZIP:
`.worktrees/native-cli-acceptance/dist/QwenTTSBridge-native-aa2770ec.zip`.

- SHA-256: `f9f810092efb5683d7f7a52648989efa82d84f30b4f5d3e7647205acd2f80175`.
- Compressed: 436,027,391 bytes. Unpacked: 580,257,839 bytes, 31 files.
- MSVC 19.44 x64 Release, CMake 4.2.3; tests/hooks OFF, frontend/WinMM ON,
  in-process native OFF, Python discovery disabled.
- Fresh bridge executables built from the frozen merged source; unchanged
  runtime reused from verified pinned qwentts `130cb99af9ae12d554962fd0920e08fb4268af01`,
  ABI 6, CUDA 13.3, architecture 75. The DLL was not rebuilt in this task.
- Frontend: `64f73182d26de60af6c082724b1b199eb7310620`.
- Runtime manifest's `130cb99` is the documented short pin; the separate build
  receipt records the full source pin and hashes all eight runtime files.
- Runtime `qwen.dll`: `b426dada07c2747c35df634f4c0782ea2b5cbba1cbe2001a8ca57a8afa590901`.

| Production executable | SHA-256 |
| --- | --- |
| `qwen_tts_native_worker.exe` | `e8b5077aabbae72e6f54d654dbf542e6767558364c05479fbf4c6e1d8b81d539` |
| `qwen_tts_save_wav.exe` | `8bd1930ca975e08a370ade1d50318f1b7f87621daa1db33f6164e76ad5876675` |
| `qwen_tts_play.exe` | `f773894eab2a68c3fe28aee24d62a51d0ee32ef36065aebc47d39933940e3ec4` |

PE closure, ZIP reopen/checksums and extraction checks passed. Dependency audit:
`pass_with_prerequisites` (`MSVCP140.dll`, `VCRUNTIME140.dll`, `VCRUNTIME140_1.dll`).
No Python/PyTorch, model weights, user recordings or test binaries are shipped.
The packaged launcher selects RU-stress Q8 by default, Base explicitly, hashes
external models even offline, handles Unicode, and requests strict natural EOS.

Unique notices are included for Bridge, qwentts, GGML, TinyProcessLib,
nlohmann/json, frontend, CUDA 13.3 LICENSE/EULA and installed VS notices. Their
presence is not legal distribution approval: the exact redistribution scope of
`vcomp140.dll` 14.50.35719.0 remains **not_assessed**. It matches the installed
System32 file, while the recorded VS2022 toolset is 14.44.

Build provenance is retained at
`.tmp/base-acceptance/native-r1-aa2770ec-20261120/package-build-provenance.json`
(SHA-256 `cc9e2688cbb59a6b81c87d8ad1ba3e0059469843288f001d8a8f6e0e241adc58`).
Package inventory, dependency imports, config, notices and full runtime hashes
are in that receipt and the ZIP-bound manifests.

## Relocation and real models

Extraction directory:
`.tmp/base-acceptance/native-r1-aa2770ec-20261120/relocated bundle`.
All new acceptance directories remain inside the repository, per the user's
explicit directory policy. Successful native execution here demonstrates
in-repository relocation with spaces, not a clean host or literal
outside-checkout qualification. Those gates remain `not_run`.

Models remain in the canonical ignored `models/` root, without new copies:

| Model | SHA-256 |
| --- | --- |
| Base Q8 talker | `4b9a33a236908dd9435a42f7a396e38038329d053b704342a6413c08544c4fda` |
| RU-stress converted Q8 talker | `f4672741608d145fae169075cb0ec775a5382cbe9183eccb59c7ab9cc4797427` |
| Shared Q8 tokenizer/codec | `1883beeed99348fc35e23dd225e9082f93f6f8c109330a33d935baa8acdbfd94` |

Voice: `kraftwerk_robot_ru_bootstrap_fidelity`. Existing PCM16 mono 24 kHz
reference: 844,844 bytes, 17.6 seconds, SHA-256
`90e5f7576991ea5b9f0a85e9109f7bd31ff667c4a12d58783a06c650796c3ca1`.
The registry preserves the exact reference transcript; the reference is not a
candidate output or a package asset.

The A/B corpus has 52 entries: 48 ordinary RU/EN cases across both profiles
and frontend/raw, two explicit-U+0301 RU-stress cases, and two early Base accent
rejections. New worker per entry; no warmup, seed override or sampling override
is exposed by the packaged launcher. Raw effective text must equal the input.
Terminal JSON and readable nonzero PCM16 mono 24 kHz WAVs are checked, including
natural EOS and absence of assisted/max-token termination. Completion does not
prove quality.

The completed CMP 50HX one-shot batch has 52 entries: 51 mechanical passes,
one failure, 49 published WAVs and two expected early Base accent rejections.
RU-stress: 26/26 mechanical checks. Base: 25/26, including both expected
rejections; 23 of 24 positive syntheses produced qualified WAVs. These counts
are PCM/EOS/routing observations, not a content-completeness or quality verdict.
Worker timing metrics are not client TTFA or end-to-end RTF.

An important mechanically passing outlier is RU-stress/raw `ru-abbreviations`:
only 3 codec frames / 0.24 seconds for the multi-sentence request. Natural EOS
and nonzero WAV checks passed, but complete content delivery is not established.
Treat this as suspected premature EOS requiring exact-artifact listening and
diagnosis, not as intelligibility or full-sentence success. Its WAV and
`ru-stress-raw-abbreviations-short-output.json` are preserved unchanged.

A [separate diagnostic follow-up](native-r1-raw-abbreviations-eos-diagnosis-20261120.md)
rules out empty input: full126-byte UTF-8 text,22 BPE body tokens, direct native
text forwarding. The engine selected EOS at step3 and the saver retained all
three frames. One unchanged-input cold repeat produced7.44s; seed42/43/44 pairs
produced8.08/6.96/6.64s. These diagnostic repeats do not replace the original
outlier or supply a listening verdict. The original random seed/logits were not
retained, so the underlying reason for that early EOS remains unresolved.

An actual Base + frontend `en-numbers-dates` run failed the natural-EOS gate:
the worker generated 2,048 frames (163.84 seconds of PCM), reported
`execution_outcome: max_tokens`, and the saver exited 1 without publishing
either the WAV or terminal JSON. Thus the saver guard worked, but this is a
failed synthesis case, not a natural-EOS success. The failed case directory,
stderr and separate `base-front-en-numbers-dates-failure-analysis.json` retain
the original/effective text and worker metric. No retry-until-green, seed
change or model-algorithm fix was applied; the generation cause is unresolved.
The corresponding Base/raw case completed with natural EOS. This is a scoped
A/B observation, not proof that text preparation alone caused the failure;
the launcher did not expose a fixed seed or per-step generation trace.

The exact logged frontend text demonstrates the targeted `2 книги` ->
`две книги` agreement correction. It also exposes an uncorrected broader
inflection limitation: `за 1250 рублей` becomes
`за одна тысяча двести пятьдесят рублей`, rather than the required accusative
`за одну тысячу двести пятьдесят рублей`. This is preserved in the
`ru-numbers-dates` receipts; the narrow assertion for `две книги` is not a
general number-grammar or pronunciation PASS. No frontend algorithm is changed
in this packaging/acceptance task.

## Persistent requests, cancellation, restart and resource observations

Separate nonshipping driver `qwen_tts_latency_benchmark.exe` was built from
the same `aa2770ec` source, MSVC Release, tests/hooks OFF. SHA-256:
`57093572263483c390aaeeeacb842ad546ad5ab008a42f50e5f51e9307111437`
(503,296 bytes). It is not a ZIP asset or another inference implementation.
Both profiles use the exact packaged worker/runtime and the same registry and
models. This driver submits four raw RU/EN ordinary/ending texts; it does not
invoke the frontend, packaged launcher, WAV publication or physical playback.

For each profile, 3 dedicated warmups preceded 30 measured requests. All 24
non-cancelled requests completed with natural EOS; 6 cancelled after first PCM.
Indexes 6/11/16/21/26 completed after same-worker cancellation. Each invocation
then shut down, followed by 3 successful requests on a distinct fresh worker
with no warmup. No failed requests, duplicate terminal events or late delivered
PCM were observed. All four bounded lifecycle phases and shutdown observations
passed; this does not exercise forced-crash/restart recovery or a soak test.

| Profile | Persistent worker PID | Restart worker PID | Warm client TTFA median | First client TTFA after restart | Warm completed-request RTF median |
| --- | ---: | ---: | ---: | ---: | ---: |
| Base | 83844 | 76112 | 180.305 ms | 1401.264 ms | 0.294 |
| RU-stress | 108516 | 57660 | 179.543 ms | 1436.392 ms | 0.295 |

TTFA here starts at request submission after worker ready, excluding process
startup/model load. The warm median is benchmark-reported; warmups and cancelled
requests are distinguished in raw JSON. This raw four-text scope is not a
latency or quality guarantee for the full frontend corpus. No seed override or
before/after performance improvement is claimed.

Sampling observed at most 4,264 MiB device-wide GPU use, not process-exclusive
VRAM or a guaranteed instantaneous peak. Worker private bytes peaked in the
samples at 5,530,144,768 (Base) and 5,527,928,832 (RU-stress). Maximum observed
working sets were 3,065,995,264 and 3,065,675,776 bytes respectively. These are
lifecycle-only samples, not per-WAV resource measurements or a memory-leak proof.
Each persistent phase has 29 worker samples and 33 GPU samples; each restart
phase has 6 worker samples and 10 GPU samples. Gaps/ownership checks and raw
measurements are retained, not filled with interpolated values.

Parent PID, executable path and creation time establish worker ownership.
Sampled `qwen.dll`, all GGML/CUDA DLLs and `vcomp140.dll` paths point to the
repository-local `relocated bundle/runtime/qwentts`, not a developer build
tree. No Python/Torch module was observed. Windows/driver/declared VC++
prerequisites remain host-provided, so this is not a clean-host acceptance.

Evidence: `.tmp/base-acceptance/native-r1-aa2770ec-20261120/lifecycle/CMP50HX-qualification-01/`.
The canonical receipts hash the raw benchmark JSON, memory/module samples,
stderr and each phase receipt. Both receipts remain blocked: Base has an
actual corpus EOS failure; RU-stress aggregate content acceptance is withheld
for the 0.24-second outlier even though its mechanical checks passed.

Start listening with
`.tmp/base-acceptance/native-r1-aa2770ec-20261120/listening/REVIEW-FIRST.md`,
then `listening/CMP50HX/cmp50hx-matrix-001/index.md` for all 49 WAVs and
`index.json` for exact original/effective text and output hashes. Human
listening of the matrix artifacts remains `not_assessed`. The independent
second-PC instructions are in [the RTX 4090 handoff](native-r1-aa2770ec-rtx4090-handoff.md).

## Seeded early-EOS follow-up

The [seeded diagnostic](native-r1-seeded-early-eos-cmp50hx-20261120.md) and
[separate canonical receipt](native-r1-seeded-early-eos-cmp50hx-20261120.json)
reproduce the raw abbreviations failure at seeds2/14 (3 frames,0.24s), including
original max2048 and guard OFF/ON. Saved finite weights and exact F32 sampler
replay show model EOS probability90.5919% after the three-frame bad history.
Controlled audio-prefix substitutions reproduce identical step3 logits across
seeds; the convergence guard is unrelated and does not prevent early EOS.
This closes the missing reproducible-seed diagnostic, not the content failure
or release gate. No production fix/default change or listening PASS is claimed.

## Scoped word-stress feedback and separate corrected candidate

The user reported incorrect stress in "мастерской" in the earlier
`cmp50hx-smoke-001/ru-stress/front/ru-ordinary/speech.wav`, not the matrix WAV.
That exact smoke artifact is 7.36 seconds, 353,324 bytes, SHA-256
`229cd5debf0cebb7ccb5fffd8fde61b9ef0f9ef380b20c4c41d96e037af8142e`.
The [separate smoke feedback receipt](native-r1-ru-stress-smoke-feedback-cmp50hx-20261120.json)
records a failed `pronunciation_stress` criterion only; all unrelated criteria
remain unassessed. No judgment transfers to the 6.88-second matrix WAV.

A new candidate in
`listening/CMP50HX/cmp50hx-stress-corrective-001/ru-stress/front/ru-ordinary/`
uses explicit "мастерско́й" (U+0301 after the final о), preserved in the logged
effective text. The unchanged packaged launcher/runtime/models produced readable
nonzero PCM16 mono 24 kHz, natural EOS, 92 codec frames, 7.36 seconds, 353,324
bytes, WAV SHA-256
`e0f7a6dce285c869ce744eb04dccd36f3102e7318f28e173ffea10d4e397c898`.
The new pronunciation remains unassessed by a human; it does not replace the
original artifact or repair the frozen matrix by implication. R1 stays NO-GO.

The distinct 0.24-second outlier is
`listening/CMP50HX/cmp50hx-matrix-001/ru-stress/raw/ru-abbreviations/speech.wav`:
"МГУ находится в Москве. Инженер проверил USB-порт, GPS и новый процессор."
It is 11,564 bytes, 3 codec frames, SHA-256
`0411d394523849e46624cfa278a1e1e0d5ee66bdc7d785f33deafbafcd36566f`.
No new listening observation exists for it in this follow-up.

Follow-up validation accepted all five indexed receipts, verified all local
artifact identities in both matrix receipts and the new smoke receipt, and
passed 22 regression tests (one existing Windows symlink skip). The optional
stress criterion preserves the five required criteria and cannot hide a
declared stress failure or unassessed status behind an aggregate listening
pass. JSON Schema execution was not run locally because `jsonschema` is not
installed; the executable receipt validator and its regression tests ran.

## Cleanup

Audited cleanup removed 105 local and 102 live origin branches, using exact
MERGED PR heads and ancestry checks, guarded local expected-SHA deletions,
and one atomic remote push with exact leases. No worktree, model or evidence
was deleted by branch cleanup. Non-ancestor superseded heads, checked-out and
dirty worktrees were preserved. Ref/SHA inventories are retained in
`.tmp/postmerge-cleanup/audit-20261120.json` and `receipt-20261120.json`.
Their SHA-256 values are respectively
`11961795757eb48a3f8ec64621d5debb03e5365b49573c9697646a79312b672f`
and `33c0cb45c1a5533c15fe93e4745e4588f236033c037d1913ecb1d97abefb6a93`.

To recover disk space, only four completed task-created build directories in
the stabilization worktree were removed after preserving their CMake caches
and CTest logs under `.tmp/postmerge-cleanup/build-receipts/`. They can be
rebuilt from correction `2fccd493`. No historical acceptance payloads or model
weights were removed. The primary checkout's tracked tree is clean; the 323
preexisting untracked reports remain untouched. This is not a claim that the
entire checkout has no untracked files.

## Receipt validation

The tracked acceptance index now includes separate version-2 native Base and
RU-stress receipts, preserving every older receipt/verdict. The validator
accepted all four indexed receipts. Both new receipts also passed local
payload existence, byte-count and SHA-256 verification against the primary
checkout. Regression tests: 18 run, one skipped because directory symlinks are
unavailable; no failures. This validates evidence structure/integrity, not
speech quality or closed release gates.

## Remaining gates

- Independent RTX 4090 execution of this exact ZIP/models/corpus; no verdict
  transfers from earlier Python or native candidates.
- Human listening of these exact hashed RU/EN artifacts: `not_assessed`.
- Clean-host and literal outside-checkout qualification: `not_run` under the
  repository-local directory restriction.
- Exact CUDA/VC++ prerequisite and redistribution review, including vcomp scope.
- Forced-crash recovery, long-run soak/leak, physical playback and per-A/B-case
  peak-resource measurements remain `not_run`. Completed raw lifecycle tests
  do not close these separate gates.
- Base/frontend max-token failure and suspected RU-stress premature EOS need
  diagnosis; numeric case inflection remains a frontend limitation.

Keep the ZIP local and unpublished. No R1 support/default promotion is made.
