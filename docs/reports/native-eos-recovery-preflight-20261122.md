# Early-EOS recovery: corrective closure and blocked GPU preflight

Recorded 2026-11-22. Research-only preparation; **no new model inference or
listening**. R1 remains **NO-GO**. See the
[frozen staged plan](native-eos-recovery-plan-20261122.md).

## Completed technical correctives

| PR | Exact HEAD | Verification | Scope / readiness |
| --- | --- | --- | --- |
| [Bridge #331](https://github.com/LimiNode/qwen3-tts-bridge-cpp/pull/331) | `09c10a1d6f67a7d3d76d43d0cb5db1d9b39779d1` | stress 10/10, local CTest 48/48, exact-HEAD CI 8/8 | Draft; test corrective verified, parent research scope not promoted |
| [Engine #51](https://github.com/LimiNode/qwentts.cpp/pull/51) | `541f1f702e725dc002e0e9ebf6f1460dca8c3100` | CPU shared/C ABI, 6 CTests, 21 graph cases x100, CI 2/2 | independent Draft corrective; awaits independent approval |
| [Engine #49](https://github.com/LimiNode/qwentts.cpp/pull/49) | `5da56ed987ee83ea16d2c26ee75c89d88df3d2d9` | existing research checks only | research Draft; not a production merge unit |
| [Engine #50](https://github.com/LimiNode/qwentts.cpp/pull/50) | `b16d8af6c365e9deb0fd503df9a695c1092ad4f4` | local CTest 19/19; exact-HEAD CI 2/2 | research Draft stacked on #49; checkpoint GPU correctness unverified |
| [Bridge #332](https://github.com/LimiNode/qwen3-tts-bridge-cpp/pull/332) | current report branch; prior `ed031044` superseded | 20 receipts validated; 17 validator tests pass, 1 optional skip | Draft stacked on #331; now carries #331's test corrective; new CI pending publication |

Bridge #331's native test read callback-owned stderr strings before shutdown
had joined/drained the dispatcher. The old failing CI log contains the
expected cache-hit metric interleaved with the failed assertion. Reads now
follow external `client.stop()`; equivalent observations were audited, and
two sleep-poll loops removed. Only the test changed. Exact-HEAD workflows:
`44959400416` and `44959400391`. The corrective was carried to332 as
`0e954212`; that does not merge the parent research branch into main.

Engine #51 is based directly on the actual engine default `master` at
`130cb99af9ae12d554962fd0920e08fb4268af01`. Its two-file diff fixes the
Predictor sampler's strided `[1,N]` uniform versus `[N]` mask, contiguous
materialization, forced token0 and per-slot forced-row strides. Expanded
N=1/2/3 stochastic/greedy/mixed/forced tests fail on the old implementation;
isolated mutants also fail. CI workflow `44959760479` passes both CPU jobs.
No reseeding, prefix experiments or runner code entered this corrective.
Public ABI, probabilities, defaults and Bridge engine pin remain unchanged.

Engine #50 still incorporates #49; Bridge #332 still incorporates #331. Neither
child may be merged independently while implicitly promoting its parent's
research changes. No PR was merged or marked ready for review.

## Implemented, not hardware-qualified

Engine #50 adds a strictly opt-in single-slot **buffered/uncommitted** checkpoint
seam, not a live streaming fork. It captures padded Talker KV/write position,
Predictor KV, hidden bridge, slot/prompt/reference ownership, complete16-code
history, repetition/RNG state and pending inputs. Restored owning pointers
are rebound. The existing buffered codec redecode is used; codec streaming
state is not snapshotted. No audible PCM exists to retract in this stage.

The probe retains original and final code/PCM artifacts for unchanged replay,
current-boundary EOS resampling, rollback1 and rollback2. Restoring unchanged
seed/subsequence must pass byte-exact complete-code **and** f32PCM checks,
without another prefill. This requirement has **not yet run on GPU**.
Source compatibility/selftests do not establish numerical replay correctness.
Up to9 host snapshots can cost approximately530MB; this is not yet a cheap
production ring buffer or a measured VRAM/fork overhead.

The new runner freezes 14 streaming controls, 21 replay pairs and 21 conditional
recovery pairs. It refuses later stages on a retained baseline or replay
mismatch. Independent collection checks actual seed/restore boundary/trigger,
original terminal/frame count, complete-code files and PCM bytes. A separate
owned-process `finally` kills/reaps even when writing watchdog diagnostics
fails. Negative tests cover these omissions found by independent review.
The new top-k2/4 probe controls are separate from the recovery intervention;
they have not generated new qualification audio.

Local validation:

- MSVC CUDA research probe compiled successfully; probe `--self-test` PASS.
- All 19 configured model-free CTests PASS; the recovery Python suite has 16
  tests. Earlier prefill Python checks: 62 run, 61 PASS, 1 optional dependency skip.
- A full-suite run initially failed two old corpus fixtures because they
  consulted real free disk. Those fixtures now supply disk availability;
  an added negative test verifies the real2GiB runner guard still blocks
  before input preparation/GPU/process startup. Guard thresholds are unchanged.
- `git diff --check` PASS. No hardware/listening gate changed, so this is a
  preflight report, not a new accepted-model receipt.

## Exact local payload and current blocker

Payload root: `.tmp/base-acceptance/eos-recovery-20261122/`.
The original frozen models, Q8codec, prepared reference and retained runtime
were hashed in place; no large runtime/model copy or evidence deletion.
`full-plan-001` is preserved historical preparation; `full-plan-002` contains
the hardened runner's current plan and exact identities.

Research EXE `probe-binary/eos-research-probe.exe` SHA-256:
`ef53929578325efba9c74028997adbb8ee486c3470ef108ba462505deaf94435`.
It was compiled at engine `382e20a3fd52d341820d35f6ea5a2d5c23d42447`;
the later `b16d8af` changes runner/tests/CI only, not native sources. This
static-core probe is not Bridge/native-worker or packaged `qwen.dll`
acceptance. Runtime DLLs remain in the earlier
`eos-corpus-decision-20261121/runtime-current/` directory.

Actual `--execute` preflight refused before model hashing/load or process
startup: required **859,439,104bytes** including512MiB safety reserve, but
only **448,802,816bytes** were available. `preflight-blocked.log` SHA-256:
`775e876ca795488e0060e3826a171ce89c75e41a8e7b121f713e114b1fb3ebf0`.
Even the separately frozen short smoke cannot run below the512MiB reserve.
No GPU time or new WAVs were produced, and no old audio was relabeled.

Next required action: make sufficient disk space available, then run the
unchanged frozen matrix into a **new** directory. Do not delete earlier WAVs,
historical evidence, models or runtime bundles as routine cleanup. The
first discriminating result is exact unchanged replay on the known five
short controls and healthy seeds. Only a pass permits interpretation of
rollback candidates. Full retry, live PCM buffering, one-prefill dual fork,
risk detector/combinations, held-out quality, audible timing and RTX validation
remain **not_run**, not inferred from this implementation or earlier seeds.
