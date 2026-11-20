# ADR: streaming speech segments and bounded early-EOS experiments

- Status: accepted boundaries; recovery and detector qualification pending
- Date: 2026-11-20
- Baseline: bridge `aa2770ec`, qwentts `130cb99`, ABI 6

## Context

Real-time streaming is the primary workload; writing WAV is a secondary sink.
The seeded RU-stress investigation in [PR #330](https://github.com/LimiNode/qwen3-tts-bridge-cpp/pull/330)
reproduces natural EOS after three codec frames for a complete 22-token input.
Natural EOS and nonempty PCM therefore do not establish spoken-text coverage.
The existing convergence guard handles overlong generation, not this failure.

Native categorical selection has been checked against retained weights. That
does not establish native forward parity with the source checkpoint. Recovery
must not be described as correcting native arithmetic without a matched-input,
matched-history comparison. The
[external-source audit](../reports/early-eos-external-source-audit-20261120.md)
records which published remedies actually address different failure mechanisms.

## Ownership and invariants

1. qwentts owns forward computation, sampling, EOS and reproducible engine
   seeds. Fix a demonstrated engine defect in the fork, in a separate PR.
   Do not silently change the Bridge gitlink, ABI or sampler defaults.
2. Bridge/native worker owns attempt orchestration and the irreversible PCM
   commit boundary. Audio playback consumes accepted PCM; it cannot retract
   audio already sent to an application or device.
3. Text planning is model-neutral and precedes per-segment frontend
   preparation. Each segment is prepared once; retain source byte offsets
   separately from effective text. Voice, language and instruction remain
   unchanged. An accent or whitespace is not silently reconstructed.
4. Inference remains sequential in one persistent worker. Generate the next
   segment while previous audio plays using the bounded existing sink queue;
   do not introduce parallel GPU inference or an unbounded prefetch queue.
5. Cancellation, stop, one monotonic deadline, bounded buffering and exactly
   one terminal event apply to the entire logical operation. A segment or
   attempt does not obtain a fresh operation deadline.

## Complete speech segments

Use complete sentence boundaries, including closing punctuation. Protect
abbreviations, initials, decimals, combining accents and quoted spans. Do not
split every fixed number of characters or words and call the result complete.
Ambiguity may conservatively keep sentences together. A bounded indivisible
span that exceeds capacity fails explicitly instead of silently truncating.

The first executable composition is opt-in one-shot
[`qwen_tts_play --segment-text`](../streaming-speech-segments.md). Each segment
is a normal QTB request; no protocol field or stable client lifecycle changes.
One playback epoch preserves queued prior audio. Later failure stops future
segments and prevents final WAV publication; already audible audio remains
irreversible. Request-level metrics or animation must not be mislabeled as
logical multi-segment receipts. Interactive replacement, cross-segment prosody
and aggregate timing require separate verification.

Segmentation is not an EOS fix: smaller requests can still terminate early.
Actual pronunciation, coverage and sentence-boundary continuity need listening
or independent ASR in addition to mock source-preservation tests.

## Streaming-first recovery experiments

Keep immediate release and the unchanged sampler as controls. Compare:

- selective first-/second-frame risk gating;
- a short fixed or text-adaptive lookahead gate;
- bounded retry of a rejected, entirely uncommitted attempt.

At most two additional attempts share the same deadline and memory budget.
Retain initial and subsequent seeds, effective text and conditioning identity,
frame counts, finish reason, rejection reason and commit state. An explicit
user seed disables automatic reseeding unless separately opted in. Model,
transport, nonfinite-audio or cancellation failures are not indiscriminately
retried as early EOS. Exhaustion produces an explicit error, not a short WAV
reported as success.

Release buffered PCM immediately after the selected startup policy passes,
then continue ordinary streaming. Do not buffer every complete sentence by
default. Once PCM is committed, never secretly replay the sentence. Report
partial-output failure on a detected later anomaly; a continuation strategy
needs its own evidence. WAV publication may wait for final validation while
sharing the same attempt policy.

Three frames arriving is **not** proof that EOS will not occur on the next
model step. A gate intended to hide a three-frame failure must observe its
terminal decision or evidence of continuation before committing that prefix.
Codec callbacks contain variable numbers of frames; a callback count is not
a codec-frame count. Memory limits apply before appending a chunk.

Duration, PCM energy and natural EOS are diagnostic features, not proof that
all text was spoken. A universal minimum frame count can reject legitimate
short answers and accept incomplete long answers. Thresholds/classifiers
remain experimental until calibrated on held-out texts/seeds for each
declared model/language scope. No classifier is enabled merely because it
recognizes seeds 2 and 14 from the discovery sentence.

## Evidence order and performance work

1. Preserve the exact source checkpoint, GGUF, prompt/reference tensors and
   complete forced audio histories. Compare native CMP/RTX/CPU and PyTorch
   where practical. Q8 native versus unquantized PyTorch is a checkpoint
   comparison, not automatically arithmetic parity; isolate quantization.
2. Retain bounded first-step logits/codes, sampler statistics, PCM features
   and terminal outcomes. Separate discovery, calibration and held-out data.
   Publish confusion counts, false negatives/positives and missing evidence.
3. Measure startup/first-use/warm persistent workers separately. Measure
   first PCM, first audible sound, gate decision and physical playback
   independently; include p50/p95, retries, RTF, memory and underruns.
4. Profile before optimizing. The
   [retained native latency study](../reports/native-streaming-latency-research-20261120.md)
   locates prefill as the dominant measured warm first-PCM span. Existing
   predictor graphs and codec state must not be reimplemented. An alternate
   chunk schedule is a separate experiment, not a demonstrated prefill fix.
5. Qualify speech coverage and audio continuity on CMP 50HX and RTX 4090.
   A longer WAV or better RTF alone cannot promote a candidate.

Keep the frozen R1 package and PR #330 historical receipts immutable. New
experiments use new repository-local payloads and explicit identities.
Update canonical receipts when an acceptance gate changes. Research,
segmentation unit tests and a source audit do not close a hardware/listening
gate. R1 remains **NO-GO**; no automatic merge, tag or release is authorized
by this experiment.
