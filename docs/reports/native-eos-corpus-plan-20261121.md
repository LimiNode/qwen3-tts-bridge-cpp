# CMP-only corpus expansion and EOS-decision timing plan

Frozen before GPU execution on 2026-11-21. Research only; R1 **NO-GO**.
User scope: CMP 50HX only, retain all attempts and WAVs for listening.
No default, sampler, model, Bridge engine pin, frozen package, live selector,
merge or release changes. Engine work stays in qwentts Draft PR #49; the
Bridge report stays on the existing Draft PR #331 task branch.

## Baseline corpus tier

Two sequential direct-engine runs, RU-stress Q8_0 and Base 1.7B Q8_0, with
the same exact retained Kraftwerk speaker/reference conditioning and common
Q8_0 codec. N=1, normal baseline sampling, no forced prefix or recovery.
Frontend OFF, segmentation OFF. Texts, conditioning, models, executables,
runtime files and invocation receive byte/hash identities before each launch.

| Text label | Exact text |
| --- | --- |
| original | МГУ находится в Москве. Инженер проверил USB-порт, GPS и новый процессор. |
| ru-yes | Да! |
| ru-no | Нет. |
| en-hi | Hi! |
| en-thanks | Thank you. |
| ru-unseen | Дежурный инженер осмотрел оборудование и передал смену следующему специалисту. |
| ru-two-sentences | В мастерско́й завершили проверку. Теперь можно закрыть дверь и отправить подробный отчёт о выполненной работе. |
| en-unseen | The engineer inspected the equipment and handed the next shift a detailed report about the completed work. |

The script writes the exact UTF-8 bytes, including U+0301, without a newline;
those files, not Markdown wrapping, own input identity. The explicit accent is
a frozen input variable, not a claim of Base's stress-rendering capability.
For each model the fixed order is original seeds 2/14/42 twice (6 controls),
then each text in table order with seeds 64..79 and one repeat of seed 64.
Total: **142 requests/model**, including **128 corpus cases**, 6 discovery
controls and 8 repeats. Of the 128 cases, 64 use legitimate short texts.

Some seeds/texts were already seen in the 2026-11-20 matrix. This is corpus
expansion, not an entirely independent held-out evaluation or detector
calibration. Keep the exact text/seed labels and do not fit a classifier or
claim an unbiased failure-rate reduction from this sample.

Each model uses one loaded persistent engine. Request zero is first use;
later requests are warm on that engine, not fresh-worker/restart tests. The
two models are never loaded concurrently. Bound generation to 256 codec
frames, each group to 60 s, each child to 600 s, each model's runner to 900 s;
reserve at least 2 GiB free disk. The combined GPU experiment budget is
1800 s including the timing controls below. Stop and record remaining cases
as `not_run` rather than replacing failed runs or omitting failures.

## Timing tier

An observational, compile-flag-only internal hook timestamps effective Talker
token selection **before predictor/codec work**, using the same steady clock
as probe admission and PCM callbacks. It stores the first eight selections
plus a later EOS in bounded memory. No extra device readback, tensor dump,
sampling draw, rejection or live PCM decision is introduced. Capture original
sampled token, effective token, prefix-forcing status and job/lane identity.
Guard-forced stops, cancellation and errors are not mislabeled natural EOS.

Use the new observer on the baseline corpus without verbose full-frame trace.
Separately compare observer ON/OFF on fixed original-text seeds 2/14/42/64/65
to check raw-PCM transparency. If budget remains, observe N=1/N=2 seed-2
one-frame-prefix continuations 64/65 and independent pairs (2,42)/(14,43),
each repeated. These discovery timing controls are not corpus successes.
Their complete manifests must be frozen before launching, with no adaptive
seed/text selection. Full frame tracing, if used for transparency, is a
separate instrumental condition and must not be pooled as untraced timing.

Measure selection-to-first-PCM and selection relative to the first chunk's
audio-duration budget; distinguish the fourth Talker decision from completion
of the entire fourth engine step. Record serial admission intervals separately
from accumulated prefill duration. These remain direct-engine callback wall
times, **not** an implemented selector, Bridge commit, GPU kernel timings,
physical audible onset, or a proof of glitch-free switching. No live fork,
winner selection or loser cancellation is installed in this tier.

## Retention and scoring

Payload root: `.tmp/base-acceptance/eos-corpus-decision-20261121/`.
Before rebuilding the disposable research build, preserve its earlier probe,
DLLs and CMake cache under `runtime-before/`; retain previous evidence intact.
New build logs, plan-only manifests, execution manifests, seeds, raw PCM,
unaltered PCM16 mono 24-kHz WAVs, failures and SHA inventories stay local.
Ignored payloads are not transferred/backed up by Git.

Natural EOS with <=12 frames on a non-short label is only the existing
duration-anomaly proxy. Count all outcomes by model/text/seed and keep
legitimate short texts separate. Record status, finish reason, limits,
cancellation, watchdog, PCM validity and missing cases. Speech coverage and
quality stay `unassessed` until new named listening/inspection is recorded.
Do not pick only longer WAVs or use normalization as a repair.

Frontend ON, segmentation ON, true Bridge/player PCM commit, physical
playback, restart qualification, new recovery algorithms, and RTX 4090 are
**not run in this tier**, not implicitly passed. Update the report/status
with actual results and the remaining boundary; promote no release gate from
a model-free check or a longer WAV.
