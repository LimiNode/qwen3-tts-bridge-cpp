# Independent review: qwentts.cpp PR #51

- Review date: 2026-11-24.
- PR: <https://github.com/LimiNode/qwentts.cpp/pull/51>.
- Exact head: `541f1f702e725dc002e0e9ebf6f1460dca8c3100`.
- Base: `master`, `130cb99af9ae12d554962fd0920e08fb4268af01`.
- State checked with `gh pr view` and `gh pr checks`: open Draft;
  `cpu-build` and `windows-msvc-shared` both successful, Actions run
  `44959760479`.
- Separate detached review checkout: `.worktrees/review-engine51`.
- Discovery: the exact review worktree has no graph index; targeted source
  reads were used, not the stale C-drive engine graphs.

## Verdict

No blocking defect found in the changed code. The patch is a narrow
per-slot predictor-sampler correction, not an early-EOS or speech-quality
qualification. It is suitable for a separate integration decision after the
usual engine/runtime acceptance; this review does not authorize that integration.

The diff changes only `src/sampling-graph.h` and
`tests/sampling-graph-contract.cpp`. Public ABI headers, model pins, generation
defaults and Bridge source are untouched. Nothing was integrated into the
ICL geometry experiment.

## Mechanism checked

1. `src/sampling-graph.h:194`: the uniform tensor is a strided `[1,N]`
   view into `[2,N,steps]`. Materializing it and reshaping to `[N]`
   gives the greedy mask the same shape as token IDs; the CPU SCALE
   implementation requires contiguous input
   (`ggml/src/ggml-cpu/ops.cpp:4574`). This prevents invalid broadcast for
   `N>1`, without changing the stochastic CDF order or the greedy argmax.
2. `src/sampling-graph.h:203`: `[N,steps]` forced values are contiguous
   within a step. The `[N]` view at `step_idx * nb[1]` selects the
   correct row. The old `[1,N]` view incorrectly used the step stride
   as its lane stride.
3. `src/sampling-graph.h:204`: `step(forced + 0.5)` accepts the valid
   integer token `0`; the documented `-1` sentinel remains unforced.
   Valid codec IDs are exactly representable in the F32 override tensor.
4. Callers were checked at `src/code-predictor-forward.h:368,471` and
   `src/pipeline-tts.cpp:331,348`: graph width, sampler dimensions,
   per-frame uploads and the diagnostic-only override flag agree with
   the corrected shapes. No ownership, concurrency or ABI change is added.

The semantic-economy pass found no new speculative abstraction, cache,
duplicate policy or dead branch in this patch.

## Independent local checks

To avoid duplicating the GGML build on the nearly full drive, the exact
head's graph regression source was compiled anew, linking the existing CPU
GGML import libraries and DLLs built from
`c044c6f03892f9d5e98213b05f8afea1f8b0d3c9`.
This is a focused regression rebuild, **not** a newly repeated full CMake,
shared-library or six-CTest build.

MSVC 19.44, x64 Release, C++17, `/MD /O2 /DNDEBUG /utf-8 /W4 /WX
/wd4505 /wd4100`; definitions `GGML_BACKEND_SHARED`, `GGML_MAX_NAME=128`,
`GGML_SHARED`, `GGML_USE_CPU`, `_CRT_SECURE_NO_WARNINGS`.

Reproduction from the repository root after `VsDevCmd.bat -arch=x64`:

```powershell
$reviewRoot = 'E:/_repoz/qwen3-tts-bridge-cpp'
$reviewArgs = @(
    '/nologo', '/std:c++17', '/EHsc', '/MD', '/O2', '/DNDEBUG', '/utf-8',
    '/W4', '/WX', '/wd4505', '/wd4100', '/DGGML_BACKEND_SHARED',
    '/DGGML_MAX_NAME=128', '/DGGML_SHARED', '/DGGML_USE_CPU',
    '/D_CRT_SECURE_NO_WARNINGS',
    "/I$reviewRoot/.worktrees/review-engine51/src",
    "/I$reviewRoot/.worktrees/sampler-batch-fix/ggml/include",
    "$reviewRoot/.worktrees/review-engine51/tests/sampling-graph-contract.cpp",
    "/Fo:$reviewRoot/.build/review-engine51/pr51-sampler.obj",
    "/Fe:$reviewRoot/.build/review-engine51/pr51-sampler.exe",
    '/link',
    "$reviewRoot/.build/sampler-batch-fix/ggml/src/ggml.lib",
    "$reviewRoot/.build/sampler-batch-fix/ggml/src/ggml-cpu.lib",
    "$reviewRoot/.build/sampler-batch-fix/ggml/src/ggml-base.lib",
    '/machine:x64', '/INCREMENTAL:NO', '/subsystem:console'
)
& cl @reviewArgs
$env:PATH = "$reviewRoot/.build/sampler-batch-fix;" + $env:PATH
& "$reviewRoot/.build/review-engine51/pr51-sampler.exe"
```

- Exact-head graph contract: **PASS**, all 21 cases, process exit `0`.
  Covers `N=1/2/3`, stochastic/greedy mixtures, token zero, unforced
  sentinel and distinct forced rows at steps `0/1/2`.
- Negative control: the **same test source and GGML libraries**, but with
  the include path changed to `external/cpp/qwentts.cpp/src` at actual
  production base `130cb99`, first reports forced-token-zero
  `expected 0, got 1`, then fails `GGML_ASSERT(ggml_can_repeat(b, a))`
  at `N=2`, process exit `-1073740791`. Output names were
  `master-sampler.obj` and `master-sampler.exe`.
- `git diff --check 130cb99af9ae12d554962fd0920e08fb4268af01...HEAD`:
  **PASS**.
- Review checkout remains clean.

Logs: `.tmp/pr-metadata/icl-geometry-20261124/review51-{build,test,master-build,master-test}.log`.

SHA-256 of independently compiled test:
`318cbcd88951ad962f518551f289588c519dee096f9a2451c870b9b0fc007206`.
Negative-control test:
`68c8500250aeadaefe89ad3872cc0c92b12f089c9926dd5df8aa23996238d43a`.

Retained CPU DLL identities:

| DLL | SHA-256 |
| --- | --- |
| `ggml.dll` | `801db7aaf96069b675990d9251e25044bf0bfae81bc590b8ae261acdd51bf4d7` |
| `ggml-base.dll` | `045c232a5ccff368654cf5a9db6e9850ca9a34d705a3aca518be25389472a249` |
| `ggml-cpu.dll` | `25f2bf97cb71f48a5792f0901fc20711c956a563475835486c8957e8c728d83a` |

## Limits

No GPU, model synthesis, listening, CUDA-graph performance or end-to-end
shared-library qualification was performed by this review. Exact-head CI is
external evidence, distinct from the focused local regression above. The
additional contiguous operation has no measured latency claim here. This
review does not establish that the correction fixes RU-stress short speech,
and does not close R1 NO-GO gates. No merge, pin change, PR comment or release
was made.
