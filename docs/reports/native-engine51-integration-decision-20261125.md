# Engine #51: integration recommendation and remaining batch scope

- Date: 2026-11-25.
- Exact candidate: `541f1f702e725dc002e0e9ebf6f1460dca8c3100`.
- Production base: `130cb99af9ae12d554962fd0920e08fb4268af01`.
- Status: narrow merge recommendation retained; no merge or Bridge pin change.
- [PR #51](https://github.com/LimiNode/qwentts.cpp/pull/51) remains open Draft.

## Existing evidence, reused rather than rerun

The [independent review](native-engine51-independent-review-20261124.md)
and [isolated GPU report](native-engine51-gpu-smoke-20261124.md) already
cover the changed sampler graph and ordinary N=1 behavior. A read-only GitHub
check on 2026-11-25 confirms the same exact head and successful `cpu-build`
and `windows-msvc-shared` jobs. This is not new CI execution.

CUDA tests cover21 graph cases, including N=2/3, mixed greedy/stochastic
lanes, forced token zero, -1 sentinel and predictor rows0/1/2. Ten ordinary
N=1 calls and real C-ABI probes passed; complete PCM matches master.
Those checks are sufficient evidence for the narrow graph-shape/forced-token
correction and unchanged tested N=1 output. No blocking finding requires a
repeat of those unchanged tests.

They are **not** end-to-end N=2/3 whole-model synthesis evidence. A synthetic
graph cannot prove heterogeneous job admission, decoder-lane compaction,
retirement, or continuity of a surviving longer request. The canonical smoke
receipt correctly remains aggregate not_assessed, with no transferred speech
or full Bridge-lifecycle verdict.

## Separate decisions

1. Recommend integrating only #51's narrow sampler correction after the
   maintainer's explicit merge decision. Do not bundle #52, ICL geometry,
   EOS intervention, prefix or rollback research.
2. Before representing N=2/3 whole-model behavior as qualified, fill that
   precise missing scope in a separate, resource-approved isolated candidate
   run. No new defect or performance claim is inferred from the missing test.
3. A later Bridge pin update is its own reviewed change with exact engine
   manifest/ABI and relevant Bridge/runtime checks. An engine merge alone
   does not accept the R1 package or close quality/restart/dual-GPU gates.

## Minimal remaining batch experiment, not executed

Use the real shared candidate DLL and unchanged public/internal harness from
the isolated qualification path, not the EOS research engine. Preserve Base
Q8 and full aligned ICL identities. Fix distinct texts/seeds, N=2 then N=3,
with unequal lengths and mixed Talker/Predictor sampling modes relevant to
the correction. Compare each lane to a newly declared matched solo control;
do not assume floating-point batched/solo PCM equality without measuring it.
Record full codes, PCM, errors and admitted/retired lanes through uneven
completion, including the last surviving request. Include forced-zero/sentinel
semantics only through an explicitly test-only seam, not a new public ABI.

Checks: no CUDA/assert failure, finite unsanitized captured samples, valid
code ranges, correct lane/request routing, complete drain and exactly one
terminal event. Any changed trajectory needs exact-artifact listening before
speech/voice acceptance; duration is not a substitute. Retain all failures.
N=2/3 generation must fit a separately agreed time/VRAM/disk budget.

No GPU execution, source change to #51, repeated CPU/N=1 smoke, ready-state
change, merge, Bridge gitlink, ABI, QTB or frozen-package mutation occurred
while preparing this decision. **R1 remains NO-GO.**
