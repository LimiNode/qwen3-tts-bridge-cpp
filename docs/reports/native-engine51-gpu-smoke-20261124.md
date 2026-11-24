# Engine #51: isolated CMP 50HX GPU smoke

Date: 2026-11-24. This is a separate production-candidate check, not a
qualification of the ICL, prefill or rollback research stack.

## Decision

Recommend approving Engine #51 at
`541f1f702e725dc002e0e9ebf6f1460dca8c3100` for separate integration.
The isolated CUDA sampler contracts pass, and ordinary N=1 output is
byte-identical to original `master` for every fixed smoke case and repeat.
No blocking engine defect was found within this scope.

This is a merge recommendation, not a merge or release acceptance. No PR was
marked ready or merged; no Bridge engine pin, production default, public ABI,
QTB protocol or frozen package was changed. **R1 remains NO-GO.**

Canonical receipt:
[native-engine51-base-gpu-smoke-cmp50hx-20261124.json](native-engine51-base-gpu-smoke-cmp50hx-20261124.json).
Its aggregate case result remains `not_assessed`: the declared GPU smoke
passes, but persistent Bridge repeat/restart were not tested. Listening is
also `not_assessed`; a mechanically valid WAV is not proof of spoken content.

## Frozen identities and isolation

| Item | Identity |
| --- | --- |
| Original engine `master` | `130cb99af9ae12d554962fd0920e08fb4268af01` |
| Engine #51 candidate | `541f1f702e725dc002e0e9ebf6f1460dca8c3100` |
| Bridge evidence baseline | `8ccdc515399b6c691a57566cad6098ce0b3e9174` |
| GGML | `c044c6f03892f9d5e98213b05f8afea1f8b0d3c9` |
| GPU | NVIDIA CMP 50HX, SM75, 20,480 MiB |
| GPU UUID | `GPU-40361931-6cb5-ac58-a059-5ba3e70986fb` |
| Driver / CUDA toolkit | 581.94 / 13.3 |
| Model | Original Base 1.7B Q8, SHA-256 `4b9a33a236908dd9435a42f7a396e38038329d053b704342a6413c08544c4fda` |
| Codec | Q8 12 Hz, SHA-256 `1883beeed99348fc35e23dd225e9082f93f6f8c109330a33d935baa8acdbfd94` |

Each engine was built in its own worktree and build directory, from the
original three engine translation units, as a real shared `qwen.dll` with
`QWEN_BUILD`. The unchanged public-ABI CLI was linked to that DLL's import
library and placed beside it. Both startup logs identify the expected engine
revision; the pure-C ABI probes also exercise those shared DLLs.

No research source, research static engine core or research compile macro was
used. The only candidate source modification is a small **test-only** optional
backend selector in `tests/sampling-graph-contract.cpp`. Without the selector,
the test retains its CPU behavior. With
`QWEN_SAMPLING_TEST_BACKEND=CUDA0`, a missing backend fails; it cannot silently
fall back to CPU. The exact patch and executable hash are preserved.

Existing GGML import libraries and their exact matching CUDA/CPU DLLs were
reused from `.build/prefill-engine`; that directory's research `qwen.dll` was
not linked or used. The ordinary CLI's adjacent DLL takes precedence, its
logged version is checked, and binary imports/exports were inspected. The
child-process search path was fixed to the frozen GGML directory, CUDA
`bin/x64`, and Windows system directories. Model, conditioning, source and
runtime inventories are identical before and after the experiment.

The separate prior source review found no blocking defect. The candidate's
exact-head CPU and Windows shared-build CI both passed (2/2). An independent
focused CPU rebuild passed all 21 graph cases; the original-master graph
exposed the expected forced-token/shape failures. These are separate checks,
not a claim that this task reran the complete CTest suite.

## Conditioning and sampling

All ordinary synthesis uses the original complete aligned ICL conditioning:
the 2,048-float Kraftwerk speaker vector, all 16 x 226 reference codes, the
unchanged nonempty reference transcript, and the engine's original decoder
reference context. Nothing was re-extracted or truncated.

The CLI accepts 11-bit packed, codebook-major RVQ rather than the research
probe's I32 input. All 3,616 source integers were packed into exactly 4,972
bytes, independently unpacked using direct bit addressing, and compared
before inference. The original speaker/transcript paths were used directly.

Talker and Predictor retain their ordinary stochastic defaults:
temperature 0.9, top-k 50, top-p 1; Talker repetition penalty 1.05. EOS guard,
forced history, retries, reseeding, prefix reuse, frontend and segmentation
are off. Seeds and texts were fixed before execution. Each CLI call uses
`--max-new 256 --format wav32`; no tensor dumps or timing observers run.

## Results

The actual backend was CUDA0. The existing 21 sampler graph cases passed,
covering N=1/2/3, stochastic/greedy mixtures, forced token 0, the -1 sentinel,
and predictor rows 0/1/2. Both pure-C shared-ABI probes exited successfully.
These N=2/3 graph checks are **not** whole-model batched synthesis acceptance.

All ten ordinary N=1 calls exited with `natural_eos`, without CUDA/assert
errors or frame-budget termination. Complete WAV and float32 PCM bytes
match between master and candidate in every row:

| Fixed case | Language / seed | Frames, both engines | Audio duration | Master vs candidate |
| --- | --- | --- | --- | --- |
| `Ладно.` | Russian / 2027 | 11 | 0.88 s | Identical |
| `All right.` | English / 2029 | 10 | 0.80 s | Identical |
| Long Russian control | Russian / 2027 | 92 | 7.36 s | Identical |
| Long English control | English / 2027 | 86 | 6.88 s | Identical |

Long Russian control:

> Сегодня мы проверили оборудование и записали результаты. Теперь можно спокойно завершить работу.

Long English control:

> The equipment passed every check this morning. We can now finish the report and close the workshop.

The long Russian case was repeated once in a fresh process for **each** DLL.
Both repeats again produced 92 frames and exactly the same WAV/PCM as their
first invocation. That is fresh-process determinism, not a persistent-worker
or restart-recovery qualification.

All output files have complete RIFF sizes, IEEE float32 mono 24 kHz data,
and exactly `frames * 1920` samples. Serialized samples are finite. The
unchanged CLI sanitizes NaN/Inf to zero, so this does **not** establish the
finiteness of every internal decoder sample. Float32 output is not clamped
or normalized by the evidence tooling.

There are four unique audio outputs. Redundant master/candidate/repeat
copies do not require repeated listening. These exact files have no new
human verdict; no prior Base or research listening verdict was transferred.
Output duration, energy and equality were not treated as speech completeness
or voice-similarity acceptance.

## Preserved harness failures and correction

Two evidence-tool issues were retained explicitly rather than hidden:

1. `run-001` stopped **before CUDA initialization or inference** because a
   new login shell replaced an unrelated `fnm_multishells` PATH directory.
   The exact-PATH guard rejected it. `run-002` freezes only the required
   dependency/system paths; source, binaries, models, settings and the
   shared batch deadline were unchanged.
2. `run-002/results.json` preserves the runner's initial erroneous N=1
   `pass=false` fields. Its classifier required at least two
   `[Load] ... backend` log lines. In both source revisions, `qwen.cpp`
   initializes **one** CUDA0 `BackendPair`, which `pipeline-tts.cpp` passes
   to both the TTS and codec pipelines; one such log line is correct.
   `corrected-analysis.json` independently rechecks the saved output and
   source contract. All other original criteria pass. There was no GPU
   rerun, changed seed, changed engine, or overwritten raw result.

The model-free runner tests pass 9/9, including RVQ boundaries, the expired
deadline, finite/nonfinite float WAVs, complete RIFF accounting and malformed
files. Their log and all analysis/build scripts are retained with hashes.

## Budget, evidence and limits

Payload:
`.tmp/base-acceptance/engine51-gpu-cmp50hx-20261124/run-002/`.
The artifact inventory preserves all commands, UTF-8 input bytes, logs,
before/after identities, binary hashes, outputs and the corrected analysis.
`run-001/PREPARATION-FAILURE.md` preserves the pre-CUDA guard failure.
Ignored payloads are local only; Git does not transfer or back them up.

The root task supplied one absolute deadline, `3170194.937`, for its entire
1,800-second serialized GPU batch. Smoke execution occupied approximately
63.494 seconds, including ABI and graph processes; all inference children
finished before the shared deadline. The GPU lease was released after the
children exited. No extra stage budget or subsequent inference was used.

This experiment does not qualify RU-stress quality, persistent Bridge state,
cancellation, streaming/rollback, N=2/3 whole-model synthesis, package
relocation, RTX 4090, or performance. Fresh-process model loading and
buffered codec decode are not warm first-chunk latency measurements.

Next integration action, subject to review: integrate only Engine #51 as a
separate correction. Do not pull Engine #52/full-text ICL, prefill or rollback
research into that change. A subsequent Bridge pin update requires its own
review and qualification; none is performed by this receipt.
