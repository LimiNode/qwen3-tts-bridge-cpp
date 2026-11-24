# Reference conditioning: prepared crops, GPU comparison not run

- Date:2026-11-24. Research only; R1 remains **NO-GO**.
- Frozen [batch plan](native-reference-source-plan-20261124.md).
- Canonical model receipts: [RU-stress](native-reference-conditioning-rustress-cmp50hx-20261124.json)
  and [Base](native-reference-conditioning-base-cmp50hx-20261124.json).

## Outcome and exact stopping boundary

The reference A/B/C comparison is **not_run**, not a negative model result.
CPU preparation completed, but **zero native extractions, zero AR attempts
and zero synthesized WAVs** were produced. Original-latent regeneration,
short/medium candidate latents, EOS observations and latency measurements
therefore remain not_run.

The shared1800s batch began06:15:20UTC, with the frozen absolute monotonic
deadline3170194.937 /06:45:20UTC. When the supplied reference lease was used,
the runner rejected it before launching the extractor: the deadline had
already expired. Immediately afterwards the observed clock was06:47:55UTC,
monotonic3170349.859. The recorded error is
`explicit execution and existing finite shared<=1800s deadline required`.
The deadline was not reset and no GPU child was launched. This check does
not say that extraction or either checkpoint failed; neither was evaluated.
The exact refusal is preserved in `run-001/execution-refusal.json`.

## Prepared inputs and checks

The actual original Kraftwerk reference remains17.6s PCM16 mono24kHz,
422400samples; SHA256
`90e5f7576991ea5b9f0a85e9109f7bd31ff667c4a12d58783a06c650796c3ca1`.
Its complete transcript was previously confirmed by the user. No original
or historical WAV, model, sealed inventory or latent file was modified.

| Fragment | Exact source samples, end-exclusive | Duration | Transcript | Expected reference frames |
| --- | --- | ---: | --- | ---: |
| Short |0..96000 |4.00s | `Я твой слуга, я твой работник.` |56 |
| Medium |96960..309120 |8.84s | `Жёлтый луч мягко лёг на шестерёнки; внизу щёлкнуло реле, сверху загудел вентилятор.` |116 |

Each PCM payload is an exact continuous slice, without resampling,
normalization, trimming inside the slice, or synthesized replacement.
Nonzero cut boundaries have at least100ms measured silence on each side,
using existing FFmpeg `silencedetect=noise=-35dB:d=0.10`. The original native
ICL preparation appends12000zero samples before extraction; the same padding
was prepared for all three references. The table's56/116 counts, and226 for
the original, are **derived expected counts**, not newly encoded codes.

Offline cached faster-whisper-small, CPU/int8,8threads, beam5, Russian,
word timestamps ON and VAD OFF, was run on all three source WAVs. It supports
the complete short phrase and natural sentence boundaries. Both medium and
full ASR return `шестерёнке`/`загудил` instead of the user-confirmed registry's
`шестерёнки`/`загудел`. The raw recognition/timestamps, local model hashes and
that discrepancy are retained. ASR does not supersede the user's transcript
confirmation or establish forced alignment/new crop-specific human listening.

Twelve model-free runner tests pass: fixed text/seed matrix, sample boundaries
and silence margins, rejection of word cuts/invalid sizes, exact integer PCM,
exclusive writes, native11-bit RVQ unpacking/codebook order, original-latent
equality gate, original-versus-crop speaker split and storage bounds. The
prepared candidate RVQ inputs have not been encoded by those tests.

## Preserved experimental design

Use aligned full ICL and unchanged stochastic Talker/Predictor defaults.
For RU-stress and Base compare original A, each crop with original speaker B,
and each crop with crop-derived speaker C. Keep the four frozen text/seed
pairs from the batch plan; do not select new seeds after outcomes.

The runner first requires exact original-reference speaker and complete-code
regeneration before any crop synthesis. It preserves both failed equality
checks rather than proceeding with a changed extraction baseline. This gate
has **not run**. The existing extractor and retained corrected static probe
are reused in place; no model, DLL or release-package copy was created.

The prospective probe is the retained `afa3df01` build, SHA256
`6c86e4d69f0c0dbc26e35c360e0b6903dc976b0ad61aa3c34dbbaaa1bbe0f6fa`.
No execution of that probe occurred in this stage. Prior aligned A outputs
were rechecked against70sealed identities and their pinned inventory; they
remain previous results, not newly performed controls or B/C evidence.

The fixed plan contains32new diagnostic attempts and64observer-OFF streaming
attempts across eight conditioning cells. Diagnostic prefill/logits times
must stay separate from first-PCM timings; first PCM is not first audible
speech. All96new attempts remain not_run. No reference-related quality,
prefill or TTFA improvement was measured.

## Evidence and listening selection

Payload root:
`.tmp/base-acceptance/reference-conditioning-cmp50hx-20261124/run-001/`.
The sealed inventory covers40files/4721270bytes, excluding itself; SHA256
`13b5d577307da2fc4066a271bfb4be1a01e98bf63edac9dfb4b3d0dd4e5a6825`.
It retains exact crops/padding/transcripts, prospective jobs, CPU ASR,
silence log,12-test result, refusal, preserved transitive runners and audit.
Ignored payloads are not transferred or backed up by Git.

`listening-reference-inputs/` contains only three unmodified reference inputs:
00original,01short and02medium, plus README and exact-copy manifest. These
are **not generated comparison outputs**; no new model/listening success is
claimed. There are no duplicate synthesized candidates to hand off.

A separately authorized new bounded batch can reuse this preparation, first
execute the original-extraction gate and then run the unchanged B/C matrix.
The current batch cannot be continued by resetting its deadline. Base and
RU-stress retain separate receipts; earlier positive/failed listening remains
attached to its exact artifacts. Root-cause attribution, shorter-reference
benefit, voice fidelity and numerical parity remain unresolved.

No production default, model/engine pin, Bridge gitlink, ABI6, QTB, frozen
R1package, merge, tag or release changed. Full-text layout remains the
completed negative experiment; rollback development remains frozen.
