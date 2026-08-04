# Authoritative Baseline: 2026-08-03

## Scope

This report records the repository-quality baseline used before further
voice-clone runner changes. It is not a real-model latency benchmark or an
acceptance claim for a GPU runtime profile.

The checks ran in a detached, clean source worktree at commit
`4e07ba9e9af51d446791d483cff8c07207bff961`
(`test(transport): diagnose worker handshake timeouts`). The worktree had no
tracked modifications. Its disposable Python virtual environment was excluded
from the source-state check.

## Environment

| Field | Value |
| --- | --- |
| OS | Windows x64 |
| CMake | 4.3.3 |
| C++ compiler | MinGW-w64 GCC 16.1.0, UCRT, POSIX, SEH |
| CMake generator | MinGW Makefiles |
| Python | 3.12.10 |
| nlohmann/json submodule | `55f93686c01528224f448c19128836e7df245f72` |
| tiny-process-library submodule | `8bbb5a211c5c9df8ee69301da9d22fb977b27dc1` |
| Qwen3-TTS-streaming submodule | `408236366b7cab3567e57c6b9183303e1f3700d9` |

## Results

| Gate | Result |
| --- | --- |
| `scripts/check-python.ps1` | PASS |
| Ruff | PASS |
| Pyright | PASS, 0 errors / 0 warnings |
| Python unit tests | PASS, 410 tests, 6 skipped |
| MinGW full CMake build | PASS |
| Full CTest | PASS, 10/10 in 54.95 s |

## Stdio Handshake Check

`stdio_transport_test` exercises a freshly launched mock Python worker for
each run. The test now has a 15-second startup deadline for the `ready` frame,
a 60-second CTest watchdog, and emits queued-frame, transport-error, worker
stderr, and exit-status diagnostics on failure. It has no retry path.

Two independent fresh-process startup series were completed on the same local
machine. They measure a newly launched worker, not a cold operating-system,
filesystem, Defender, or Python-package cache state:

| Series | Result | Duration |
| --- | --- | --- |
| `ctest --repeat until-fail:100` | 100/100 PASS | 470.22 s total; max 5.15 s, p99 5.09 s |
| Post-diagnostic-change repeat | 20/20 PASS | 94.36 s total; max 5.00 s |

The earlier isolated timeout was therefore not reproduced, but a future
recurrence now fails visibly rather than silently consuming a generic
five-second frame wait.

## Boundary

This baseline unblocks deterministic bootstrap-runner hardening. It does not
replace the separate CUDA/model validation required for a voice-profile or
runtime-performance claim.

## Post-Hardening Addendum

The historical baseline above intentionally remains tied to `4e07ba9`. After
bootstrap-runner hardening, the exact source head
`c688afeb3094732763a2dee0628392a25f3fa844`
(`fix(voice-clone): harden bootstrap candidate evidence`) was independently
checked in the same clean detached worktree setup.

| Gate | Result |
| --- | --- |
| `scripts/check-python.ps1` | PASS |
| Ruff | PASS |
| Pyright | PASS, 0 errors / 0 warnings |
| Python unit tests | PASS, 414 tests, 6 skipped |
| MinGW full CMake build | PASS |
| Full CTest | PASS, 10/10 in 53.34 s |

This addendum records repository health at that exact head.

## Schema-3 Validation Addendum

The current provenance implementation was then validated from a clean detached
source worktree at
`d08684dfcd55a741efb0ae794da661274672bc10`
(`docs(voice-clone): document reproducible candidate evidence`). As before,
the worktree had no tracked modifications; its disposable virtual environments
were untracked local tooling.

| Gate | Result |
| --- | --- |
| `scripts/check-python.ps1` | PASS |
| Ruff | PASS |
| Pyright | PASS, 0 errors / 0 warnings |
| Python unit tests | PASS, 416 tests, 6 skipped |
| MinGW full CMake build | PASS |
| Full CTest | PASS, 10/10 in 54.65 s |

The runner's real-model CUDA smoke remains separate evidence: this source-only
gate verifies the schema-3 fail-closed contracts and their regression tests,
not model audio quality or clone identity.

## Schema-4 Recorded-Hash Addendum

Schema 4 added a recorded wheel `RECORD` hash manifest to the bootstrap
contract, separates diagnostic locations from identity, revalidates the
embedded contract during resume, and hashes only tracked Python sources. It
also checks the trace fields supplied by the then-current FasterQwen revision.
The schema is intentionally incompatible with earlier candidate sidecars, but
is historical only: it does not prove actual installed Python file bytes.

The source-only gate passed before this addendum was written:

| Gate | Result |
| --- | --- |
| `scripts/check-python.ps1` | PASS |
| Ruff | PASS |
| Pyright | PASS, 0 errors / 0 warnings |
| Python unit tests | PASS, 418 tests, 6 skipped |

## Schema-5 Actual-Content Addendum

Schema 5 replaces the historical wheel-`RECORD` identity with an actual-byte
manifest of the active Python runtime. It also requires a clean tracked and
untracked source tree, a complete terminal generation trace, and an actual-byte
tree manifest for the staged portable Python runtime. A candidate run therefore
fails closed when an installed package file changes without a corresponding
`RECORD` update, when an unrecorded runtime file appears, or when the model
trace cannot prove EOS completion.

The implementation head was
`218cddd6d2e806a81c33e9dceba2cc7a90776c22`
(`fix(provenance): verify runtime bytes for voice clone evidence`). The runtime
checks below were performed from a clean detached staging worktree so that the
clean-source policy was part of the tested contract.

| Gate | Result |
| --- | --- |
| `scripts/check-python.ps1 -UseVenv` | PASS |
| Ruff | PASS |
| Pyright | PASS, 0 errors |
| Python unit tests | PASS, 422 tests, 6 skipped |
| MinGW full CMake build | PASS |
| Full CTest | PASS, 10/10 in 51.72 s |
| Strict Python runtime manifest | PASS; build 190.03 s, verify about 90 s, 17.9 MB manifest |
| Portable Python package mock smoke | PASS; staged tree manifest built and reverified |
| C++ against staged portable mock worker | PASS; 14,400 PCM bytes in 3 chunks |
| Schema-5 CUDA clone smoke | PASS; `eos`, 50 generated/emitted codec steps, 50 PCM frames |

The strict runtime rehash is deliberately expensive: it is an authoritative
integrity gate rather than a per-request operation. The portable package check
continues to be a mock-worker packaging smoke. A real Qwen/CUDA one-folder
package and the deferred blind four-profile identity evaluation remain separate
release work; neither is claimed by this report.
