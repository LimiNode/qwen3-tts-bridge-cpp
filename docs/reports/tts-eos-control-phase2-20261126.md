# EOS control phase 2: preparation and execution boundaries

- Date: 2026-11-26.
- Status: active research; new model/GPU runs not executed.
- Input review: Bridge #335 `85461e65`, Engine #53 `3a896743`, Engine #51 `541f1f70`.
- Owner: native TTS research; production defaults, ABI6, QTB, pins and frozen R1 unchanged.
- Prior evidence: [phase1 EOS/accent study](native-eos-control-and-manual-accents-20261125.md).

The phase1 allocation is closed. Preparation and model-free tests below do
not renew it or provide new speech evidence. A new aggregate CMP-only window
has been requested, not assumed. No GTX1060/RTX4090 execution, merge or release
is included. R1 remains **NO-GO**.

## A — bounded EOS and startup interventions

The new source is isolated in `.worktrees/eos-phase2-engine`, based on exact
Engine53 `3a896743ada11cba6bfa7e6fd69c06ec39a10283`. The existing OFF-by-default
research seam is extended, not the public API or production sampler.

The frozen EOS comparison is baseline, constant `penalty:2`, `window:4:8`,
and `decay:4:8`. The window subtracts4 only at completed-frame indices t<8;
decay subtracts `4 * max(0, 1 - t/8)`. Both are exactly zero from t=8.
The horizon includes the existing first two minimum-masked decisions: the
first eligible subtraction is4 for window and3 for decay, not a newly raised
minimum duration. Placement stays after reserved/minimum/guard masks and
before repetition, temperature, top-k/top-p and categorical sampling.

A separate comparison changes only the chosen sampler's key for its first
one or two complete frames: `talker:1`, `talker:2`, `predictor:1`, `predictor:2`.
It uses the existing deterministic per-frame key map, restores the base key
after the declared boundary, and preserves subsequence numbering and draw
count. The other sampler retains its base key throughout. A changed key is
not proof of changed selected codes; inspect the actual first-frame histories.
This is not one-shot EOS substitution, a replay, a new prefill or a snapshot.
Nonbaseline EOS and startup changes cannot be combined in one request.

Original full aligned ICL remains unchanged in all A arms. The small frozen
matrix includes known short/long failures, normal long controls, and a
separately declared Base arm with previously heard original-full-ICL short
answers. Base evidence must not become a RU-stress/CF false-intervention
claim. Old same-setup code/PCM identities can establish a matched control;
duration and energy cannot qualify an unheard short answer.

The old200request batch is not repeated. Discovery and cost measurements
must remain separate; traced first-PCM times are not an uninstrumented latency
benchmark. Full text, extra speech, final phonemes, voice and usable-speech
onset remain listening criteria. The independently frozen
[held-out corpus](tts-eos-phase2-heldout-20261126.json) is not executed or used
to choose/tune a policy. No adaptive policy has a speech-success verdict yet.

The prepared plan fixes80primary plus32separate observer-OFF cost requests
(112total), with upper payload562692096bytes plus2GiB reserve. Full AR/tensor
dumps are off; bounded policy logs remain on, so the small cost comparison is
not a deployment percentile benchmark. The engine's3332focused checks pass
on GCC15.2 and MSVC; feature-OFF/EOS-only syntax checks, static probe build
and host-only self-test pass. Ten runner tests pass. The inherited C4244 in
the research restore path remains; no warning-free full CTest campaign is
claimed. A parent/child concurrent preparation attempt safely lost the
exclusive-directory race before its first write; the complete plan is intact.

Exact preparation identities:

- Probe SHA256: `a0cd6ca9554f0d0015ad723e0c5c0fc0daa88c80abea61f9bcc757c116e8f29e`.
- Engine patch SHA256 over exact3a896743 base:
  `cfab5fed5a1e0fbd9bf5579886e20a34552d1e752c8061258ebf135a0cfa2648`.
- Plan SHA256: `5ca3e0cee18f1ca7becdda5299d6bea0809d4d89b05a2f1b26f5a70ab3c02d92`.

Payload preparation is
`.tmp/base-acceptance/eos-phase2-cmp50hx-20261126/run-001/`.
A model-free pre-execution identity check confirms source, binary and frozen files
unchanged. No GPU execute stage has been invoked. A later source commit or
edit requires a reviewed refreeze; it must not silently relabel this binary.

## B — retained-code terminal diagnostic

The separate `.worktrees/codec-tail-phase2-engine` extends the existing private
replay probe with `--terminal-decode`. It does not synthesize new AR codes.
Its two fixed inputs are CF18 (86 frames, original226-frame reference,
one-shot seed75) and paired RU06 (22 frames, short56-frame reference,
`Он произнёс слово «замо́к».`, seed2027). Both exact failed artifacts remain.

Compare retained production streaming PCM, independent full decode of
reference+history with the exact reference-sample crop, independently reset
production-ramp streaming, and reset T=1 streaming. Preserve all real frames,
sample counts, F32 outputs, chunk positions, differences and failures. This
will distinguish production chunk/state effects from a defect also present
in independent full decode; it cannot by itself prove an AR/training cause.

Source inspection finds no separate finish/tail API at this revision. The
production terminal operation drains queued real code frames before retiring
the lane. Causal transposed-convolution overlap outside the declared signal
length is right-trimmed by full decode too; it is not an extra hidden PCM
buffer to append. Feeding invented zero/repeated code frames would change
the signal, not perform this flush. No fade, silence, normalization or
fabricated frames are part of the diagnostic. Source inspection is not yet
an executed terminal-state result or a recovered-phoneme verdict.

Preparation payload:
`.tmp/base-acceptance/codec-tail-phase2-cmp50hx-20261126/preparation/`.
The MSVC `/W4 /WX` build and host-only replay/layout self-test pass.
The frozen plan owns exact code, PCM, codec, probe and command identities.
The two model runs remain **not_run** and are bounded to32MiB new results.

- Probe SHA256: `4f33c2b42ec0348ece33faf9889441d3401b1aef8097c0e820c6f6886ba66674`.
- Plan SHA256: `9853a99461298b3b31e44976b0c33daacbecc76ea6b66eb207f41cdbf5429450`.

## C — reproduce the precise voice-drift artifact

Target the first-pass RU-stress08 from the three-model study, **not** paired
CF08. The expected text is:

> Сегодня мы проверили оборудование и записали результаты. Теперь можно спокойно завершить работу.

The new35request plan reuses the exact old `afa3df01` probe and unchanged
sampler, all16 codebooks, original speaker vector SHA256
`4119368fc3a673c29187bbef0c48d3c789e6f05390bae61f3303c4f10ea38698`, and
4.00/8.84/17.60second references with matching saved transcripts. References
remain separately labelled conditioning changes, not equivalent optimization.

For each reference, two independent fresh processes start with the target
RU sentence. The short-reference persistent arm reproduces the exact old22
requests in order, then repeats the target; original/medium persistent arms
use RU/EN/RU. Compare complete codes and PCM to the exact old08, not only
durations. Thus the short arm preserves the historical preceding sequence,
while the other two provide declared persistent controls rather than pretending
to reproduce that same sequence. New same-setup output still needs listening
unless it is byte-identical to a named previously assessed artifact.

Local plan and runner:
`.tmp/base-acceptance/reference-stability-phase2-cmp50hx-20261126/run-001/`.
Preparation verifies source text bytes, models, runtime, references and
original vector; schedule checks pass without loading a model. Worst-case
payload including selection allowance is205307904bytes, plus2GiB reserve.
No new fragment extraction or alternate equal-duration fragment comparison
has run. Such content/coverage controls remain a later separate scope; the
three existing references cannot isolate length from phonetic content.

The frozen plan SHA256 is
`f6452afa27fbf0467382aaa915df702d62b7de2708096414f1d50a4469d3a7a4`.

## D — actual alternative-model setup

The [initial preflight](alternative-tts-preflight-20261125.md) is preserved.
The new work resolves actual dependency metadata under Windows CPython 3.11.9
(ESpeech) and 3.12.13 (MOSS), freezes exact distribution URLs and expected
hashes, and sizes remote wheel ZIP directories before downloading large files.
The bounded resolver skips full-wheel preparation; neither environment is
installed, import-qualified or inference-qualified. Three small source
archives required audited metadata generation; their build toolchain is not
claimed reproducible. Existing worker/source environments remain unchanged.

| Candidate | Packages | Package member bytes | Model/vocoder bytes | Minimum free bytes, pip first |
| --- | ---: | ---: | ---: | ---: |
| ESpeech RL-V2 | 155 | 5,547,026,542 | 2,751,477,191 | 11,445,595,896 (10.660 GiB) |
| MOSS Local v1.5 | 90 | 5,127,409,690 | 17,595,918,400 | 25,407,682,650 (23.663 GiB) |

These bounds assume no persistent full-wheel cache, dependencies installed
before a single model copy, a 2 GiB reserve and a 512 MiB allowance. They are
not measured filesystem allocation. Downloading weights before installation
raises the respective peaks to 14,197,073,087 and 28,469,081,772 bytes.
ESpeech's exact GUI RUAccent preset adds 524,900,324 bytes of model/dictionary
data; raw/manual-`+` core inference may omit it only as a labelled adaptation.
MOSS's small tokenizer/config files and a qualified shared FFmpeg bundle are
not included. A static FFmpeg executable is not the TorchCodec DLL runtime.

At the final disk check E: had about 7.57 GiB free. Practical start thresholds
are at least 12 GiB free for ESpeech and 25 GiB for MOSS, rechecked after any
Qwen results or installation. No large weight/CUDA-wheel download, package
installation or alternative-model inference has started. Disk shortage is a
resource gate, not an observed speech-quality failure. ESpeech remains first
in the execution order; model-only download sizes are not sufficient budgets.

Pinned ESpeech model revision is `f582b6e5897fe8a5835059405a8439d13bdf7684`;
Vocos is `0feb3fdd929bcd6649e0e7c5a688cf7dd012ef21`. The resolved stack uses
f5-tts 1.1.22, torch/torchaudio 2.10.0+cu128 and transformers 4.57.3.
The stock reference helper caps audio at 12 s and changes its silence/tail;
preserve original and effective reference with the verified transcript to
avoid an automatic Whisper download. Its `streaming=True` path first
generates and decodes an entire text chunk, then yields 2048-sample slices.
This is not within-chunk incremental synthesis. Inputs under 10 UTF-8 bytes
also trigger stock speed 0.3, a declared confound for short-answer timings.
The normal Vocos dependency graph includes Encodec 0.1.1 with CC-BY-NC 4.0
metadata; the Apache-labelled main model alone is not full commercial
licensing clearance. This does not prohibit the requested research run.

MOSS's main revision is `be7766a6735b98bd793f7c79fb720b4d0f5d13b8`.
Its separate tokenizer is not a small side file: revision
`f6e20e543b33d2c252a7ef71bdf8aa71e5ff9169` has three weight shards totalling
8,495,058,856bytes. Together with the declared TTS weights, model+tokenizer
alone require about16.39GiB. Dependencies, staging and reserve are additional.
The tokenizer's stock code accepts FP32/BF16, not an FP16 compute mode; CMP
SM75 therefore needs a separately tested FP32-tokenizer path, not an assumed
FP16 toggle. A stock forward failure has not been observed because it has
not been run. RTX4090 remains a separately approved resource, not a fallback
started automatically.

MOSS's pinned upstream helper at
`934d6826b084c46a0d033402174d5f8ac4ed2519` implements incremental AR-frame
generation plus a stateful codec and emits audio during generation. This is
source evidence, not a measured first-PCM result. Its HF processor passes raw
text to the tokenizer; the English slash-delimited IPA example is not proof
of Russian IPA support. The resolved stack uses torch/torchaudio 2.9.1+cu128
and transformers 5.0.0 without FlashAttention. FP16 TTS plus FP32 codec/SDPA
is only an unexecuted CMP candidate; actual fit under 18 GiB remains unknown.

Local dependency evidence is in `.tmp/tts-alternatives-phase2-20261126/`:

| Frozen evidence | SHA256 |
| --- | --- |
| `espeech-windows-cp311.lock.txt` | `3f66d8c35e585b846b99d95118b702955bf3b1d8b296d2696f3be357604fb284` |
| `espeech-dependency-budget.json` | `92d10b51aab34f150a49cf688baee18c08c85cfd412d2a495715ee3f4295d2b8` |
| `moss-windows-cp312.lock.txt` | `53079d60c7bbe2d4cb297770a7de2a30a670cffd13a35a68d6a933b35e2d1fd5` |
| `moss-dependency-budget.json` | `49a482cb7cacde7b84171f7ec3282398f27d4f128f97be429886d99c621fe6c6` |
| `task-d-summary.md` | `0268655f47da2c0aab4ea377b7db05021d76ce13b84ba6f1626febe875e97d9f` |

Failed metadata attempts and zero-byte reports remain historical failures,
not successful resolver results. The completed reports are
`espeech-resolved-012.json` and `moss-native312-resolved-011.json`.

Keep dependency resolution, local hash-verified download, installed import,
stock inference, actual incremental PCM, pronunciation and listening as
separate gates. A disk refusal is not a negative speech-quality result.

## E — existing accent contrasts only

Use the unchanged folder
`.tmp/base-acceptance/eos-control-cmp50hx-20261125/run-001/listening-eos-and-accents`.
No regeneration or rewritten sealed README is needed:

| Files | Model / input | Question |
| --- | --- | --- |
|21–23 |RU-stress raw/selective/all-available |Is ordinary `докуме́нты` correct; which sounds most natural? |
|24–25 |RU-stress nonstandard selective/all |Is `до́кументы` followed without distortion? |
|26–28 |CF raw/selective/all-available |Is ordinary `докуме́нты` correct; which sounds most natural? |
|29–30 |CF nonstandard selective/all |Is `до́кументы` followed without distortion? |
|31–32 |RU-stress/CF raw, seed2027 |Is the complete expected sentence intelligible? |

All expect `Он произнёс слово документы.`, with only the declared stress
variants and `сло́во` in all-available inputs. Record complete text, stressed
vowel, extra sounds/phoneme distortion and naturalness separately. File31
has only two frames: this is a diagnostic flag, not a new human verdict.
These manual variants are not an executed frontend. Selective marking remains
a candidate. Nonstandard stress alone is not a release gate; normative
pronunciation, complete text and voice continuity remain required.

## F — Engine51 remains isolated

The [integration decision](native-engine51-integration-decision-20261125.md)
and original isolated smoke remain valid in their declared scope. No repeat
of passed CPU, graph-level CUDA or ordinary N=1 smoke is planned. The missing
experiment is whole-model N=2/3 with unequal lengths, admission, retirement,
lane compaction and continued correct routing of the longer surviving lane.
New matched solo controls serve that experiment, not a duplicate master smoke.
Use only exact541f1f70 plus any explicitly recorded test-only observation
seam; do not link the EOS/prefix/ICL research engine into the candidate.

The isolated `.worktrees/engine51-batch-phase2` build adds only the
OFF-by-default `QWEN_RESEARCH_BATCH_TRACE` observation seam. It emits stable
serial/seed, full 16-code frames, active width, admission, retirement, real
pending-frame drain and both slot/codec compactions. The public shared-DLL
ABI remains unchanged; independently compiled header layout checks match the
ctypes caller. The MSVC `/W4 /WX` build and eight model-free harness tests
pass. This is an instrumented candidate, not the untouched binary and not a
whole-model GPU result.

The frozen schedule has 14 requests: seven matched solo controls, three at
N=2 and four at N=3, including overflow admission and all four
greedy/stochastic Talker/Predictor combinations. All use original full ICL,
256-frame caps and at most 64 MiB of results. The harness preserves callback
PCM before assessment; code/PCM comparison with matched solo outputs remains
postprocessing work, not an equivalence assumption.

An independent model-free audit found and reproduced a false-positive
survivor gate in the first preparation: it could count a fresh overflow
singleton after both original lanes retired. The corrected analyzer requires
a subsequent frame from the same serial that underwent both nontrivial
compactions. Its negative fixture rejects the former false positive while
the genuine-survivor fixture still passes. Only the analyzer/tests and their
documentation changed; the observation DLL stayed identical.

Local evidence is
`.tmp/base-acceptance/engine51-batch-phase2-cmp50hx-20261126/preparation/`.

- DLL SHA256: `68f2b31fdeba48ccb14fd87252a6274fb4b1dc2fa9ea007b1973b90bab13d579`.
- Current `plan-v2.json` SHA256:
  `2ad55e1d1be9406db4308d5b7868517f7da288f51d6c57f85d987d1a9ac0c1fa`.
- Superseded, unexecuted `plan.json` remains intact with SHA256
  `e5dc6da209187adbd7d0a5f0b34e6de0b23323e3c08a960bf383aee48774770b`.

The supervisor must verify every current frozen asset, enforce the aggregate
resource/deadline bounds and terminate the owned process tree if necessary.
Requested width, unequal lengths and post-compaction survivor work must
actually be observed; correct queued solo work cannot qualify N=2/3.

Guarded-merge recommendation and a later Bridge pin update remain separate
maintainer decisions. Neither is authorized by preparing or running this test.

## 2026-11-27 supervised CMP 50HX execution

The separately approved aggregate window started at `2026-11-27T01:09:57Z`
(04:09:57 MSK) and ended normally after 472.984 seconds, without renewal,
forced termination or resource violation. The supervisor checked 231 unique
frozen assets before execution. It observed a sampled peak of 5,786 MiB device
memory, a minimum free disk of 61,203,529,728 bytes and a peak payload of
98,118,060 bytes. These are device-total samples, not allocator telemetry.
The exact supervisor log and postprocessing manifest are retained under
`.tmp/base-acceptance/eos-phase2-window-20261127/`.

### A — 112 requests

All 112 mechanical collections passed and all frozen identities remained
unchanged. The ten fresh baselines (RU-stress, CF and Base) were byte-identical
to their retained controls. The 32 observer-OFF cost controls also matched the
corresponding traced code/PCM outputs, so the bounded observation did not alter
this matrix.

The short «Ладно.» control remained near-silent: RU-stress and CF produced
2 frames with `penalty:2`, 4 with `window:4:8`, and 2 with `decay:4:8`.
None is a speech-success result. On the long MGU seed75, window and decay
produced 86 frames in both models; the CF outputs are byte-identical to the
historical one-shot/penalty4/6 artifact whose listening result is the truncated
«проце». The longer waveform therefore does not establish recovery. Window and
decay first-PCM cost for the long control stayed around 178 ms; the apparent
short-case RTF improvement is only a longer near-silent buffer.

Changing the first Talker/Predictor keys changes selected codebooks in some
cases and restores the base key at the declared boundary, but does not repair
«Ладно.»: EOS remains at 2 frames for the relevant RU/CF arms. Base short
controls remain mechanically valid; `penalty:2` lengthens some Base controls,
while window/decay match baseline. No semantic success is inferred.

### B — two retained-code terminal diagnostics

CF18 (86 frames) and RU06 (22 frames) completed successfully. Production-ramp
streaming reproduced the retained PCM **bit-for-bit** in both cases, with zero
pending real frames after finish. Fixed-T=1 streaming and independent full
decode differ numerically from retained production PCM; full decode is not
bit-identical either. The diagnostic reports `terminal_flush_extra_samples:0`.
Thus the current terminal drain is not dropping a hidden queued tail, and
full decode is not a drop-in replacement. The generated codes themselves and
the missing phoneme remain an AR/conditioning/decoder interaction target;
the WAVs are prepared for separate listening, not declared semantically fixed.

### C — 35 reference-stability requests

All 35 collections passed mechanically. The short-reference fresh and
persistent RU target requests are byte-identical to the historical first-pass
RU-stress08 (codes and PCM). Medium and original references produce distinct
codes/PCM (92 frames in the fresh RU controls versus 90 for short), so the
earlier drift is reproducible only with the short reference and its historical
session sequence in this setup. Voice continuity remains a listening gate.
No alternate equal-length natural fragment was run.

### F — Engine #51 whole-model qualification

Solo, N=2 and N=3 groups all passed the mechanical routing, conservation and
terminal-event checks. N=2 observed width2, both compactions and 40 frames
from the same compacted survivor. N=3 observed width3, three slot/codec moves
and 173 post-compaction survivor frames. The analyzer's false-positive fixture
is now rejected by the refrozen `plan-v2.json` criterion. N=3 includes natural
EOS variation, so semantic speech coverage remains unassessed; batch/solo
code/PCM comparison is recorded separately and is not assumed equal. The
instrumented DLL remains isolated and no merge or pin change is authorized.

### Listening handoff

The postprocessor created exact, unnormalized selections:

- `.tmp/base-acceptance/eos-phase2-cmp50hx-20261126/run-001/listening-phase2-a`
  — nine A controls/candidates;
- `.tmp/base-acceptance/codec-tail-phase2-cmp50hx-20261126/run-001/listening-terminal`
  — six retained/full/T=1 WAVs for B;
- `.tmp/base-acceptance/reference-stability-phase2-cmp50hx-20261126/run-001/listening-voice-phase2`
  — seven C artifacts plus the original reference;
- `.tmp/base-acceptance/engine51-batch-phase2-cmp50hx-20261126/run-001/listening-batch-phase2`
  — seven F batch artifacts.

All remain `not_run` for listening. Duration, RMS, natural EOS and mechanical
completion are not semantic speech success.

## Current stopping boundary and quality review

No new GPU/model output is claimed. Requested shared bounds are30minutes,
one CMP50HX model process at a time,18GiB VRAM, at most1GiB new results and
at least2GiB free disk. The timer must start with execution, not preparation;
each child inherits one nonrenewable deadline. Alternative-model installation
requires its independently sized disk decision. No unique prior artifact,
model, WAV or journal has been deleted.

A, B, C and F together have a worst-case planned payload of 868,663,296 bytes,
below 1 GiB with room for aggregate monitoring logs. There are 161 planned AR
requests (including 32 separate cost controls), plus two retained-code codec
diagnostics. This count is preparation, not an executed new matrix. Remaining
work is actual supervised execution after a new resource decision, exact-code
and PCM analysis, compact WAV selection, separate listening and indexed
canonical receipts. Alternative-model setup/inference and existing E listening
remain open gates; this report does not declare phase 2 complete.

Reuse is intentional: A extends the existing research sampler; B extends the
existing codec replay probe; C composes retained manifest/collection and
owned-process helpers; E uses existing files. No second inference, rollback,
frontend or production backend implementation is introduced. Canonical model
receipts must be added/updated with actual new hardware/listening outcomes,
not manufactured from these preparation checks.

Documentation verification: all 49 existing canonical receipts validate;
17 validator tests pass and the optional `jsonschema` test is skipped.
The runner's ten tests, voice-study model-free schedule check, batch
harness's eight tests and whitespace checks pass. None loads a TTS model.
