# Short-input checkpoint and conditioning comparison

Recorded 2026-11-23. Research only, R1 **NO-GO**. Executes the
[prespecified15-group plan](native-short-conditioning-plan-20261123.md),
after both exact short outcomes in the
[reset study](native-eos-short-reset-20261123.md) failed direct user listening.
Current scoped receipts are separate for
[RU-stress](native-short-conditioning-rustress-cmp50hx-20261123.json) and
[Base](native-short-conditioning-base-cmp50hx-20261123.json).

## Result and limit

All15 new logical groups complete with exactly15 AR attempts in62.437seconds
including identity preflight/postflight, under one1800-second wall bound.
There are no missing groups, timeouts, interruptions, changed identities,
unexpected fallback, repeated-code/PCM disagreements or nonfinite audio.
All independent buffered controls use one prefill, no snapshot/restore and
no committed PCM. The threshold1 full-retry path is only a source-free way
to obtain buffered outputs and full codes; it never actually retries here.

Each short number below is repeated twice with identical complete16-code
history and f32PCM. One codec frame is80ms. Seed64, exact `Нет.` / russian
and `Hi!` / english are unchanged in all cells.

| Checkpoint / conditioning | Нет. frames | Hi! frames | Long control frames | New groups |
| --- | ---: | ---: | ---: | ---: |
| RU-stress / full ICL, reused | 2 | 3 | Not rerun | 0 |
| RU-stress / speaker-only | 13 | 14 | 86 | 5 |
| Base / full ICL | 11 | 8 | 103 | 5 |
| Base / speaker-only | 8 | 11 | 84 | 5 |

The reused RU-stress/full-ICL short files remain failed user listening:
01 has no audible intended word;02 has a strange sound instead of Hi!.
All77 preceding payload files were rehashed and are unchanged. Those failures
are not transferred to any new cell. The user has subsequently assessed all9
new unique selections: scoped word coverage is positive in every new cell,
recorded as **partial_pass** in each model's canonical receipt. Other quality
and release gates remain open.

New selected short WAVs have f32RMS approximately-31.48 to-25.58dBFS,
PCM16 peak6960 to13432, duration0.64 to1.12seconds. Long controls are6.88,
8.24 and6.72seconds. None of the30 saved raw/WAV pairs has peak<=1LSB.
These signal metrics alone did not establish words or rescue. Subsequent
direct user listening below independently confirms intended words; no
semantic conclusion is inferred from signal level.

Generation depends on the checkpoint/conditioning setup under these fixed
inputs. In particular, removing full ICL from RU-stress changes the complete
AR histories and avoids the observed2/3-frame outcomes. A model-wide defect
is not established: both checkpoint and ICL dependence remain scoped to this
seed/text pair. Direct listening now confirms the words in these new cells;
that is a scoped usable mode, not a guarantee on other seeds/texts or voices.

Speaker-only intentionally removes both reference text/codes for AR and
reference availability to the decoder, retaining the same speaker vector.
This is a combined conditioning-mode comparison, not a pure transformer-only
ablation or localization to a layer/kernel. Changing checkpoint may change
model-dependent context; it is not an upstream/native numerical parity test.

## Exact execution

Bridge pre-run documentation HEAD:
`1c7952df64af7cb827fc3d6e000eaba084d155fb`.
Engine and imported tracked helpers remain clean at
`4e47ed266f08cab9e13e277aa460a33bb607e769`, GGML
`c044c6f03892f9d5e98213b05f8afea1f8b0d3c9`.
Existing static probe SHA256
`8bd699d6f12d31198e004ed82ef67a4d6aa515c6a361a52353e203d682abef5f`;
local driver SHA256
`ea058ecc49db9e37a33a4c597f498355c275d044ece04202ed48b5b2e5253710`.
No source change or rebuild. MSVC14.44.35207, CUDA13.3 SM75, driver581.94;
only CMP50HX UUID `GPU-40361931-6cb5-ac58-a059-5ba3e70986fb` was used.
RTX4090 and GTX1060 are not part of this evidence.

The exact model hashes are in the plan and separate receipts. RU-stress and
Base Q8_0 each occupy2079448256bytes; codec Q8_0 and original Kraftwerk speaker,
226-frame reference and transcript retain their original identities.
Models and runtime are reused in place, not copied or deleted. All selected
assets and source/inputs are independently hashed before/after. There is no
loaded-module audit. Each cell has its own loaded process; its five requests
share the engine, and cells execute sequentially, with no parallel inference.

Frontend, segmentation, prefix reuse, guard and scheduled reseeding remain
OFF. All15 effective sampler descriptions exactly match retained defaults:
stochastic Talker/Predictor, temperature0.9, top_k50, top_p1, min2, original
repetition settings. No top1, minimum-duration rescue or text change.
Each logical operation retains one60-second deadline and256-frame cap.

## Verification and artifacts

Payload: `.tmp/base-acceptance/short-conditioning-cmp50hx-20261123/`.
All136 payload files are inventoried. Plans, model paths, exact input hashes,
environment, source/probe/runtime identities, raw outputs, full histories and
all repeats are retained. The local runner and imported local helper sources
are preserved under `evidence-tools/`; tracked engine helpers are pinned by
engine HEAD. No production script or policy is added by this local driver.

Root separately compares actual repeated code/PCM bytes, all effective
samplers and all1547520 samples across30 sourcef32/PCM16 WAV pairs. Every
sample exactly matches documented rounding/clamping, mono24kHz. Fifteen
duplicate original/final pairs are artifact copies, not30 AR attempts.
All9 selected copies match source bytes. Local schedule/positive guard and
trigger/repeat/count/conditioning-negative checks pass; no new C++ build or
engine CTest run was necessary for this source-free probe reuse.

## Listening decision

One folder: `listening-conditioning/`.01-03 expect `Нет.`,04-06 expect `Hi!`;
within each triplet the order is RU-stress/speaker-only, Base/full-ICL,
Base/speaker-only.07-09 are the same three modes on the original MGU phrase.
README gives exact expected text, and selection-manifest gives paths/hashes,
duration and level before listening. No trimming, normalization or silent
failure exclusion was performed. All prior failures remain retained.

On2026-11-23 the user reports the following for these exact selections:

| Files | User observation | Scoped result |
| --- | --- | --- |
|01-03|Each says Нет.|Intended word confirmed in all three new modes.|
|04|Recognizable Hi!/Хай, rising intonation, less English-like than05/06.|Word accepted; intonation difference retained, not a rejection.|
|05-06|Hi!, falling intonation; both described as more English-like than04.|Intended word confirmed in both Base modes.|
|07-09|Full MGU phrase, without laughter, cough or extra sounds.|Coverage and these named artifact classes confirmed for the long controls.|

Absence of every possible short-file
artifact, exact voice identity, final-tail quality and sequential isolation
are not inferred. Aggregate listening_result stays not_assessed because
partial_pass is scoped, while intelligibility passes in each model receipt.
The agent did not listen. Frozen payload's initial not_run metadata remains
historical evidence; tracked receipts/index own the updated verdict.

Occasional stress on O in процессор is reported among07-09 without exact
file attribution. Keep it as a nonblocking pronunciation/accent-model note,
not an EOS failure or proof of which layer/model feature caused it. Neither
text nor accents were changed in this experiment.

Compared with the failed RU-stress/full-ICL controls, removing ICL avoids
these two missing-word outcomes at seed64, and both tested Base modes also
speak the requested words. Full retry64 alone did not fix the original
RU-stress/full-ICL setup. This identifies a useful conditioning/checkpoint
dependency, not a universal early-EOS detector or production fallback.

Next, if continuing quality qualification, use a bounded held-out set of
short texts/seeds and evaluate voice fidelity in full-ICL versus speaker-only
mode. Keep these discovery examples out of that success denominator. No
further GPU run, production mode selection, automatic ICL fallback or
new seed search was performed as part of this listening update.

No production defaults/pins/ABI/QTB/models/frozen package change, merge, tag
or release. Streaming timing, physical playback, production worker recovery,
multi-lane, restart and broader hardware/quality acceptance remain open.
