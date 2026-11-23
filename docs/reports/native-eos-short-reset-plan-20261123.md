# Short-input full-retry reset control on CMP 50HX

Prespecified on 2026-11-23 after failed aggregate listening to the
[corpus/checkpoint selection](native-eos-corpus-checkpoint-20261123.md).
Research only; production pins, defaults, models and release package stay
unchanged. R1 remains NO-GO. No seed search or new rollback matrix.

## Question and fixed workload

Does full retry reproduce an independently admitted seed64 generation for
the same short text, rather than merely extending a retained failed prefix?
Use the existing engine `4e47ed266f08cab9e13e277aa460a33bb607e769` and exact
RU-stress Q8_0 / Kraftwerk full-ICL conditioning from the preceding study.
Only CMP 50HX UUID `GPU-40361931-6cb5-ac58-a059-5ba3e70986fb` is in scope.

Ten logical groups, two repeats of each cell:

| Text / language | Independent seed64 | Full retry1009 to64 |
| --- | ---: | ---: |
| `Нет.` / russian | 2 | 2 |
| `Hi!` / english | 2 | 2 |
| Original126-byte MGU phrase / russian | 2 streaming controls | Not run |

All attempts retain input bytes, seeds, finish reason, complete available
code histories, raw PCM and WAVs, including failures. Existing rollback
1009-to64 artifacts are compared in place, not regenerated.

## Matching the decoder without changing the engine

The ordinary probe baseline uses streaming decode; full retry uses buffered
decode with a different reference-context schedule. Direct PCM comparison
between these modes cannot diagnose retry reset.

For the four short independent controls, use the existing buffered
`full-retry` path at seed64 with `trigger_max_frames=1`. These are controls,
not recovery attempts: require **triggered=false, attempt_count=1,
prefill_count=1**, no snapshots and no restore. If any such control has at
most one frame, its gate fails and reset interpretation stops. Do not change
its threshold after seeing the result. Actual retry groups use threshold8,
original1009 and continuation64. Require an actual second prefill and compare
their final complete codes and buffered PCM against the independent64
originals. Expected bound is14 AR attempts, including four conditional
second attempts; an unexpected fresh-control trigger invalidates this plan.

The two long streaming64 controls must match the retained natural-EOS
84-frame original and raw PCM. Repeat disagreement, changed asset identity,
failed long control or invalid mechanics blocks causal interpretation.
All work shares one absolute1800-second deadline established before identity
preflight. Per-operation60-second deadlines are not reset for retries.

## Decision and limits

- Fresh64 and retry64 disagree: inspect retry/state reset before any rescue claim.
- Both are useful but retained rollback is not: retained prefix is a candidate cause.
- Both are near-silent or fail listening: neither retry64 nor retained-prefix
  rollback is a remedy for these short inputs. This alone does not prove a
  model defect; checkpoint/conditioning comparison is a subsequent decision.

Compare complete codes before PCM across differing decoder modes. Explicitly
label near-silent WAVs before any listening handoff. Duration, amplitude and
natural EOS do not establish words; new listening remains not_run. This is
not streaming latency, physical playback, production worker, multi-lane or
release acceptance. Stop after this small stage to examine its result.
