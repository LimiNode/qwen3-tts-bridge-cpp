# Short-input full-retry reset controls on CMP 50HX

Recorded 2026-11-23, following the
[prespecified plan](native-eos-short-reset-plan-20261123.md). Research only;
R1 remains **NO-GO**. The
[canonical receipt](native-eos-short-reset-cmp50hx-20261123.json) owns current
mechanical, listening and release status separately.

## Result

All10 logical groups and14 AR attempts complete in41.172 seconds including
identity preflight and postflight, within the shared1800-second bound.
No missing group, timeout, interruption or changed identity occurs. The four
short fresh64 controls do not trigger their threshold1 fallback: each uses
one prefill and one attempt, no snapshot or restore. All four actual
1009-to64 retry groups trigger at threshold8, perform a second fresh prefill
and use no checkpoint. Complete16-code histories **and same-decoder f32PCM
match independently admitted64 byte-for-byte**, in both repeat orders.
The hypothesized retry-reset failure is **not reproduced** in these cases.

| Text / language | Original1009 frames | Fresh64 frames | Retry final64 frames |
| --- | ---: | ---: | ---: |
| `Нет.` / russian | 2 | 2 | 2 |
| `Hi!` / english | 2 | 3 | 3 |

Both long original-text64 streaming controls reach naturalEOS at84frames
(6.72seconds), with exactly the retained rawPCM hash. These are healthy
mechanical controls, not a new general quality acceptance.

The original1009 short outputs are effectively silent: all four retained
original-attempt WAVs have absolute PCM16 peak<=1 integer unit; sourcef32
RMS is approximately-98.61dBFS. Fresh/retry64 outputs contain more signal:
`Нет.` is0.16seconds, f32RMS-35.71dBFS, PCM16peak3522;
`Hi!` is0.24seconds, f32RMS-31.85dBFS, PCM16peak4964.
Subsequent direct user listening is **fail** for both new short selections:
01 has no audible intended word;02 has a short strange sound rather than Hi!.
More signal and naturalEOS therefore did not mean recovered speech.
Earlier failed fresh64 listening and aggregate failed rollback listening
remain scoped to their earlier artifacts. In particular, different codec
modes prevent silently transferring those verdicts to these new WAVs.

Full retry64 is **not a remedy for these two tested short inputs**. Short natural
EOS is not unique to rollback: independent generation itself chooses EOS
after2/3frames, and direct listening now rejects their words. A valid short
word could also end quickly, so duration alone was not the failure criterion. General model
failure, native-forward failure and conditioning failure are not distinguished.

## Decoder confound and retained rollback

The ordinary probe baseline is streaming: full226-frame reference priming and
the1/2/4/8 ramp. Full retry is buffered, with the reference tail and chunked
decode. Matching short fresh controls use the existing buffered full-retry
path with threshold1; the required NOT-triggered gate passes for all four.
Thus the reset comparison actually matches decoder conditions, without an
engine change or extra replay. The failure path could have attempted18 AR
generations; it was not reached and the observed count is exactly14.

Both new original1009 code histories equal the preceding corpus originals.
Their buffered PCM does **not** equal the preceding streaming PCM; this is
recorded as a non-gating cross-decoder observation, not a reset failure.
The retained live rollback1009-to64 cases (RU group3, EN group18) remain at
2frames with sourcef32RMS around-98.75dBFS. Those saved failed cases were
not rerun. Different continuation codes or more signal are not semantic rescue.

## Provenance and checks

Bridge pre-run documentation HEAD:
`047080b68bc75aa0281bd54d828ed9b715a6fc47`.
Engine and imported runner helpers remain clean at
`4e47ed266f08cab9e13e277aa460a33bb607e769`, GGML
`c044c6f03892f9d5e98213b05f8afea1f8b0d3c9`.
Static probe SHA256:
`8bd699d6f12d31198e004ed82ef67a4d6aa515c6a361a52353e203d682abef5f`.
MSVC14.44.35207, CUDA13.3 SM75, driver581.94, CMP50HX UUID
`GPU-40361931-6cb5-ac58-a059-5ba3e70986fb`; no RTX4090.
RU-stress Q8_0, codec, speaker vector,226-frame reference and transcript keep
their preceding exact identities, recorded in plan and canonical receipt.
Frontend, segmentation, prefix reuse, scheduled reseeding and EOS guard OFF;
default stochastic Talker/Predictor/min2 unchanged. No model or runtime copy.

Payload: `.tmp/base-acceptance/eos-short-reset-cmp50hx-20261123/`.
Local runner/spec and model-free audit source are retained in `evidence-tools/`;
models/runtime reused in place and independently hashed before/after.
Probe selftest and runner's model-free schedule/hash/guard/deadline checks
pass. Root separately compares actual fresh/retry code and PCM bytes and all
18 saved raw-to-WAV pairs:395520 samples exactly match documented rounding,
PCM16 mono24kHz, with no conversion loss or normalization. Eighteen files
include duplicate fresh-original/final artifacts, not18 synthesis attempts.

## Listening and next decision

One small folder: `listening-reset-controls/`, with01=`Нет.`,02=`Hi!`,03=long
control. Each short selection represents two identical independent64 and
two identical full-retry64 outputs. Exact source/copy hashes are retained;
all original failures and repeats remain in `probe/`. The four nearly silent
original1009 outputs are explicitly labeled and need no repeated handoff.
On2026-11-23 the user reports01 has no audible intended word and02 has only a
short strange sound. Both fail intelligibility;03 and the other quality
criteria remain unassessed. The canonical receipt/index record this failure;
frozen local initial not_run metadata is preserved. The agent does not claim
to have listened.

This stage is complete and both short files fail. Do not extend seed search
or describe64 as a rescue: the next small
discriminating study is RU-stress/Base crossed with full Kraftwerk ICL versus
speaker-only, reusing these RU-stress/full-ICL controls and retaining languages,
texts, seeds and decoding mode. That study is **not_run**, not silently added
to these10 groups. No production worker orchestration, live latency, physical
playback, multi-lane, restart or release qualification is claimed.

No source/ABI/QTB/default/pin/package change, merge, tag or release.
