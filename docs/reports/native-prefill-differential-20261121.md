# Prefix-KV differential follow-up

Status: bounded CMP 50HX research complete; scoped three-file user listening recorded.
Date: 2026-11-21. No engine pin, ABI, sampler or release/default promotion.

This follows the [prefill study](native-prefill-study-20261121.md) and its
13 exact-file user observations. Those observations remain authoritative only
for the original files. Separate user listening for the three short-text WAVs
below was subsequently recorded on2026-11-21.

## Scope and controls

GPU UUID `GPU-40361931-6cb5-ac58-a059-5ba3e70986fb`, CMP 50HX, driver581.94,
MSVC19.44/CUDA13.3 sm75. Models, text and conditioning are the same frozen
payloads as the original study. Every request uses seed64. No RTX run.
The campaign stayed inside the approved approximately30-minute GPU interval;
all GPU work was finished before13:01 UTC. No benchmark is inferred from
instrumented durations.

Thirteen complete diagnostic runs each execute four processes (baseline and
prefix, each with taps OFF/ON), with four requests per process: original,
original, short Russian `Да!`, original. Total:208 outcomes, intentionally
limited to four frames. All104 OFF/ON pairs preserve raw PCM, logits, frames
and terminal status. All240 recorded native K/V restores are byte-exact;
snapshot stability and preservation through the suffix are checked separately.
Only the default CustomVoice run captures all28 layers. Other runs capture
layer0; this is not a claim of full-layer coverage for Base/RU-stress.

The [machine-readable record](native-prefill-differential-20261121.json)
anchors every plan, result and reviewed layer analysis by size/SHA-256, and
records missing executable retention and excluded taps. Full payloads are in
`.tmp/base-acceptance/prefill-differential-20261121/`.

## Where the first difference appears

Input embeddings and layer0 attention-normalization output are exact. The
first valid differing stage is Q projection, **before** RoPE, attention, or
reading restored KV. For prefix86, its maximum absolute delta is4.77e-7
RU-stress and7.15e-7 Base. Their full/suffix lengths are236/150, both on MMQ.
Changing the prefix boundary to64 does not eliminate the RU divergence.
This boundary experiment is not the previous attention-window64 experiment.

For CustomVoice original text, the full33-row/suffix24-row comparison is
exact through all captured layers, final logits and PCM in the default run,
including A/A and A/B/A returns. The short text has14 full rows and5 suffix
rows; Q-projection delta rises to3.12e-4 and final-logit delta to0.317353.
Manual prefill attention and disabled operation fusion do not remove this
pre-attention difference. These controls contradict damaged KV-copy and
Flash-Attention-only explanations; they do not prove every cache lifecycle.

### Observed CUDA dispatch and a discriminating control

An isolated patch on pinned GGML `c044c6f03892f9d5e98213b05f8afea1f8b0d3c9`
logs the actual host-selected layer0 Q-projection route. It confirms MMQ for
full14 and MMVQ for suffix5. Disabling fusion keeps these paths observable.
These are dispatch logs, not a complete CUDA kernel trace or GPU timings.

| CustomVoice short-text control | First layer Q delta | Final-logit max delta | PCM |
| --- | ---: | ---: | --- |
| Prefix9, ordinary dispatch | 3.12e-4 | 0.317353 | differs |
| Prefix5, suffix9, same MMQ side of threshold | 0 | 0 | exact in bounded run |
| Prefix6, suffix8, crosses to MMVQ | 3.12e-4 | 0.362149 | differs |
| Prefix9, forced cuBLAS f32 | 7.15e-7 | see raw record | differs |
| Prefix9, forced MMQ | 0 in captured layer0 | 0.00169516 | exact in bounded run |

Forced controls change Q8_0 Talker matrix dispatch only when there is more
than one column; single-slot decode is unchanged. Forcing MMQ eliminates the
large first-layer difference and reduces the final-logit delta about187-fold.
It does not establish mathematical equivalence: later differences remain.
Conversely, Base/RU differences persist while both shapes use MMQ, so the
MMQ/MMVQ transition is not a complete explanation for every model/shape.
Internal reduction/tile choices within a route were not traced.

## Full speech follow-up, not just four frames

A separate complete12-request run uses the same frozen patched runtime,
seed64, max_tokens256, no tensor taps, and the same four-request sequence
for baseline, ordinary prefix9, and prefix9 with forced MMQ. All12 requests
produce finite valid PCM and report natural EOS, without reaching the limit.

For `Да!`, baseline generates9 frames/0.72s. Ordinary prefix generates
37 frames/2.96s. Forced MMQ returns9 frames/0.72s and **the entire raw PCM
and WAV are byte-identical to this run's baseline**, not merely the first
chunk. Their WAV SHA-256 is
`b9ec1db3f43ef8e653a69e48061328c8c78fb1536d4310403f56190aa6b74d91`.
The final logits still differ by0.00169516. This is a useful narrow candidate
for preventing the observed prefix-induced trajectory change. It is not
universal proof of cough removal or early-EOS prevention, and does not inherit
the earlier file07 listening verdict: that earlier WAV has a different hash.

One directory contains three unchanged WAV copies:
`.tmp/base-acceptance/prefill-differential-20261121/listening-customvoice-mmq/`:

1. `01-baseline-yes-seed-64.wav`.
2. `02-prefix-default-yes-seed-64.wav`.
3. `03-prefix-mmq-yes-seed-64.wav`.

The user listened to all three exact files and reports:

- File01 says `Да`, without the cough heard in02.
- File02 says `КхмКхм Да`: coughing/throat-clearing before the expected word.
- File03 says `Да`, without the cough heard in02.

Sizes/SHA-256 and original source copies were independently checked. Files01/03
are 34,604 bytes and byte-identical, not independent quality trials. File02 is
142,124 bytes, SHA-256
`c30574dba774f57be2d5eaada48dd86f4b5b3f8fd8d60172e2c5170d36b78939`.
This is direct scoped listening evidence that forced MMQ avoids the ordinary
prefix-induced cough on this text/seed64, not merely a duration-based inference.
Broader voice fidelity, final tail, sequential isolation and other texts/seeds
are not assessed. Full original-phrase results remain unlistened; no favorable
selection is substituted for the complete run. Generated manifests/results
remain unchanged, including their historical unassessed fields.

Separate indexed canonical receipts preserve the
[ordinary-prefix failure](native-prefill-default-short-listening-cmp50hx-20261121.json)
and [scoped MMQ/baseline observation](native-prefill-mmq-short-listening-cmp50hx-20261121.json).
The earlier failed prefix receipt is not superseded. Both new release
dispositions remain blocked; no production profile is promoted.

## Diagnostic corrections and provenance limits

The first manual-attention capture marked a RESHAPE view as output but did
not retain its backing allocation. Its apparent large attention-output delta
was invalid: downstream O projection/residuals and final outputs were exact.
The private diagnostic now pins the full backing-owner chain. A fresh manual
A/A control is exact at this tap. The reviewed analyzer excludes old unpinned
view captures while retaining valid owned Q/K/V and KV observations. Earlier
files remain unchanged, with reviewed analysis saved separately.

The first six runs recorded initial probe hash
`6f715e84dccb0c6dce7c9a288a4f67bed25943ce6423bff9af382debd2260acd`
but did not retain that executable before a rebuild. This is a provenance
limitation, not a fully retained binary claim. Later runs freeze their runtime
in each run directory. The tracked dispatch patch extends the initial logged
patch with an opt-in MMQ branch; earlier plans retain their original patch
hash. Patched DLLs remain local evidence only. The GGML checkout was restored
to the pinned source after testing; no submodule commit was changed.

`customvoice-speech-followup-001` generated eight requests before a collector
error: an exclusive JSON writer was mistakenly used twice for one results
file. Raw audio/logs for both blocks remain; its third block was not run.
The corrected full repetition is `customvoice-speech-followup-002`. Neither
the failure nor its generated audio is deleted or counted as complete.

## Decision and next check

The larger CustomVoice short-text drift has a demonstrated contribution from
shape-dependent matrix dispatch. A consistent MMQ route is a promising
research control; it is not yet a production setting. The three-file listening
check is complete. Next, test more short texts/seeds and measure uninstrumented
latency/cost with the same kernels. For Base/RU, investigate intra-MMQ shape
effects separately before claiming equivalent prefix reuse. No new cache
framework, hidden retry, startup EOS gate or release change follows from this
evidence. The previous approximately46ms prefix saving is not remeasured by
these diagnostic runs.

The subsequent [short-utterance study](native-prefill-short-20261121.md) broadens
the text/seed controls and measures timing separately with the retained runtime.
It does not transfer the three-file listening verdict to any new recording.
