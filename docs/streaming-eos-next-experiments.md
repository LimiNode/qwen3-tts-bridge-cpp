# Streaming/EOS follow-up experiment handoff

This is a work checklist, not an acceptance result. See the
[ownership decision](architecture/adr-streaming-segments-and-eos-recovery.md),
[checkpoint comparison](reports/early-eos-source-checkpoint-probe-20261120.md),
[detector replay](reports/native-early-eos-detector-replay-20261120.md) and
[latency study](reports/native-streaming-latency-research-20261120.md).
The current code-prefix candidate is rejected; no live recovery policy or
faster engine is qualified. R1 remains NO-GO. Do not merge or release.

The separate [CMP frame-reseed/shared-prefix study](reports/native-frame-reseed-and-prefix-20261120.md)
and [qwentts Draft PR #49](https://github.com/LimiNode/qwentts.cpp/pull/49)
cover the additional deterministic reseeding and true two-slot experiments.
They do not update the Bridge engine pin or install a live recovery policy.
Current task scope is CMP 50HX only; do not launch RTX work from this addendum.

## Current scoped listening checkpoint

The user listened to all eight WAVs in `matrix-final-006/switch-1` and
`switch-2`: full original text, normal overall speech, with a caveat that
`МГУ` is sometimes too fast. These are four unique seed/policy outcomes with
repeats, not eight independent cases. See the
[canonical receipt](reports/native-eos-switch-listening-cmp50hx-20261120.json).
The broader research corpus, teacher-forced shared-prefix batch and streaming
selector are not accepted by this observation. R1 stays NO-GO.

The user subsequently confirmed the full correct phrase in three selected
one-frame seed-2-prefix continuations: single seed 64 and batch seeds 64/65.
The batch seed-65 WAV gradually fades toward the end; its cause and measured
severity remain unassessed. See the
[prefix listening receipt](reports/native-eos-prefix-listening-cmp50hx-20261120.json).
This establishes scoped coverage, not artifact-free audio or live switching.

Next, characterize that fade without modifying the retained WAVs, freeze a
broader CMP-only corpus and measure the actual EOS/selection timestamp,
serial-prefill cost and committed-PCM deadline before deciding on a true fork
or live selector. Whole-step timing is not a selector implementation. Preserve
baseline and all failures. Review the current Draft PRs before promoting any runtime.
Abbreviation handling belongs in a separate frontend A/B experiment, leaving
the EOS discovery inputs and sampler defaults unchanged.

## Independent RTX 4090 agent

1. Use a task worktree under the local repository's `.worktrees/`, check out
   `feat/streaming-eos-research`, and record the full fetched HEAD before any
   build. Do not run a moving branch without retaining its SHA. Payloads,
   builds and models stay under `.tmp/base-acceptance/<unique-run>/`, `.build/`
   and `models/`, respectively. Do not alter an older package or run directory.
2. Record actual GPU UUID, driver, compiler, CUDA architecture, backend,
   qwen.dll/worker/player SHA-256, manifest and model hashes. Keep the engine
   pin `130cb99af9ae12d554962fd0920e08fb4268af01`, ABI 6. Upstream ABI 6
   alone is not sufficient: its parameter layout differs from this fork.
   A machine-specific engine build is a distinct runtime identity.
3. Use the exact RU-stress Talker SHA
   `f4672741608d145fae169075cb0ec775a5382cbe9183eccb59c7ab9cc4797427`,
   codec SHA `1883beeed99348fc35e23dd225e9082f93f6f8c109330a33d935baa8acdbfd94`,
   Kraftwerk reference WAV SHA
   `90e5f7576991ea5b9f0a85e9109f7bd31ff667c4a12d58783a06c650796c3ca1`
   and exact registry transcript/whitespace policy from PR #330 evidence.
   Never substitute a similarly named voice or Base checkpoint as parity.
4. Reproduce the original complete abbreviation text, raw frontend OFF,
   max-new-tokens 2048, known short seeds 2/4/14/21/31 and controls
   1/42/43/44. Record every seed and outcome, including failures. Separate
   fresh first use, warm persistent worker, repeated seed and restart.
5. Compare identical **complete 16-codebook** bad/good prefixes. Match prompt
   IDs, reference codes, speaker embedding and prefill inputs before comparing
   logits at steps 0..3. Record EOS logit/rank/raw and final probability,
   top alternatives and numerical errors, not just selected token IDs.
   Quantization/precision differences are explicit experimental variables.
6. For source comparison verify merged checkpoint SHA
   `9742ba7f6ca86732875c4a910f8f60988183c525c84e99dd724f02424ee88fe0`.
   Probe Torch CUDA availability before loading; record effective nested
   attention implementation after load, not just the requested `eager`
   argument. The current source comparison used CPU FP32/SDPA, not CUDA.
7. Generate the same one-shot text with/without `--segment-text`, frontend
   ON/OFF and an explicit recorded seed. Retain source byte ranges, actual
   effective text per segment, ordered PCM/WAV, exact terminal outcomes and
   physical playback observations. Check stresses, sentence boundaries,
   reference voice stability and no duplicated/discarded speech. Mock sink
   success does not establish audible continuity or underrun performance.

Ignored local dumps, scripts and model files are **not transferred by Git**.
Before same-input parity, obtain the exact retained evidence bundle from its
owner, verify its inventory and record transfer hashes. The local source
probe driver has workstation-specific paths and a CPU device choice; do not
run it unchanged on another machine or call it a portable reproduction tool.
Reuse the pinned fork's cossim hooks to make a new bounded driver; preserve
the original evidence. If matching inputs/checkpoint are unavailable, report
that boundary rather than substituting a different model.

## Prospective independent corpus

Freeze the following matrix and seed list in an invocation manifest **before**
observing outcomes. Do not refit a classifier on its evaluation split.

- Discovery controls remain the known seeds above; prospective evaluation
  uses seeds 64..79 in the listed order, retained even when generation fails.
- Short valid utterances: `Да!`, `Нет.`, `Hi!`, `Thank you.`
- Unseen RU sentence: `Дежурный инженер осмотрел оборудование и передал смену
  следующему специалисту.`
- Unseen RU multi-sentence text: `В мастерско́й завершили проверку. Теперь
  можно закрыть дверь и отправить подробный отчёт о выполненной работе.`
- Unseen EN sentence: `The engineer inspected the equipment and handed the
  next shift a detailed report about the completed work.`
- RU-stress and Base; frontend ON/OFF; segmentation OFF/ON for multi-sentence
  input; CMP 50HX and RTX 4090 recorded separately.

Save the exact UTF-8 bytes (including U+0301) in a file; the prose line wrapping
above is not an input-byte identity. Use normal sampling, not forced prefixes,
for coverage/quality. Bound the run by a prespecified request/deadline/disk
budget; leave omitted cells `not_run` rather than selecting only successful
seeds. The frozen replay analyzer intentionally supports the old single-text
0..31 discovery run only; it is not the evaluator for this new matrix.

Label speech coverage independently through human listening and/or ASR with
manual inspection of errors. Retain unassessed examples as such. Duration
proxy labels can guide investigation but cannot replace coverage labels.

## Live startup gate and optimization decision

After independent calibration, implement only an opt-in bounded candidate in
the native worker/Bridge, keeping the baseline sampler untouched. Compare
immediate release, selective gating and a short mandatory/adaptive lookahead
on the same cases. Record the actual PCM commit boundary; `N` received frames
alone cannot reveal EOS at the next step. Test at most two additional attempts,
one deadline, explicit-seed opt-in, cancellation/stop, exhaustion and no retry
after commit. Test physical playback, not only callback traces.

Profile the measured prefill span first. Keep prompt/ICL construction,
prefill, first predictor, first codec, callback/stdout and client/player spans
distinct. Report p50/p95, retry frequency, first audible sound, underruns,
RTF, memory and qualified speech coverage. Whole-request phase totals are not
first-frame timings. Compare alternate `1,1,2,4` only as a separate engine
experiment with deterministic and audio-continuity checks; it cannot remove
the prefill span before the first codec frame.

Any demonstrated engine correction/optimization gets a separate fork Draft
PR, with no automatic gitlink update. Any acceptance-state change gets a new
tracked receipt and index entry; never overwrite or promote the PR #330
historical evidence based on a longer WAV or a successful build.
