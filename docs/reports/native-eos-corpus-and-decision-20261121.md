# CMP 50HX corpus expansion and actual EOS-decision timing

Status: completed bounded research; scoped listening failures; R1 **NO-GO**.
This follows the [pre-run plan](native-eos-corpus-plan-20261121.md), not a new
sampler, live selector, recovery policy or release qualification.

## User listening follow-up (2026-11-21)

The user assessed the 19 numbered convenience copies. The exact statement,
per-file labels and original artifact hashes are in the
[listening record](native-eos-corpus-listening-20261121.json).

| Named subset | Recognized normal text | Uncertain | Failed text recognizability |
| --- | ---: | ---: | ---: |
| RU-stress | 4 | 1 | 6 |
| Base | 7 | 0 | 1 |

Normal text: files01/09/10/11/12/13/15/16/17/18/19. File05 only resembles
"да" and stays uncertain. File02 resembles "але" or "мг", not the requested
phrase; files03/04/06/07/08/14 fall under the user's remaining-files report:
inaudible **or** very short and meaningless. Do not assign one alternative
or an exact physical silence mechanism to each file from this grouped wording.
Voice fidelity, artifacts and final tail were not separately assessed.

RU-stress seeds72/75/78 are now requested-text listening failures, not merely
duration anomalies. A later file-specific clarification explicitly confirms
the full expected normal phrase in Base file18 (106 frames / **8.48 s**).
Its initial failure inferred from the grouped remainder, and the dependent
duration-proxy false-negative claim, are **superseded**. Initial wording and
the exact clarification are preserved in the listening record. Current totals
are **11 confirmed, 1 uncertain, 7 failed**. Base file14 still fails despite
being a legitimate-short input. Short texts must be validated,
not simply excluded from semantic failure accounting.

These 19 are an enriched, nonrandom subset of 284 baseline WAVs. The other
265 and all 36 controls retain unassessed coverage; no listening or quality
verdict transfers to them. Original generated observations/CSV/inventories
are preserved as pre-listening snapshots, with this linked record as the
per-file label overlay. Canonical receipts now record failed listening while
retaining passed mechanical PCM/natural-EOS checks. No new inference ran.

The [saved-PCM audit](native-eos-corpus-listening-pcm-audit-20261121.json)
reverified all 19 source/copy hashes, PCM16 mono 24-kHz format and exact
clipped/rounded raw-f32 conversion, with zero mismatches and all raw values
finite. No convenience-copy or WAV serialization corruption was found.

| WAV | Duration | PCM16 RMS, dBFS | Saved signal |
| --- | ---: | ---: | --- |
| 03 | 0.16 s | -107.70 | >98% zero samples, near quantization floor |
| 04 | 0.24 s | -109.28 | >98% zero samples, near quantization floor |
| 14 | 0.88 s | -25.57 | Substantial level; not globally silent |
| 18 | 8.48 s | -24.64 | Substantial signal across .10..8.42 s |

For file18, 387/424 nonoverlapping 20-ms windows have normalized RMS >=.005;
file14 has 32/44. This descriptive threshold is not a speech detector. File14's
negative observation cannot be explained by global file silence or low overall
gain, but energy alone establishes neither intelligible speech nor its failure
mechanism. File18's full speech is now explicitly confirmed by the user, not
inferred from these energy measurements. Its focused clarification is closed.

## Identity and scope

Bridge plan `59d8fc04e6f86b1423635e4549b2d8f6b2944e27`; clean engine source
`0de7ec5c7467bc5a1cbf5b82e42d2f270016fbd3`; ggml
`c044c6f03892f9d5e98213b05f8afea1f8b0d3c9`. MSVC Release, CUDA 13.3,
sm75, CMP 50HX UUID `GPU-40361931-6cb5-ac58-a059-5ba3e70986fb`, driver
581.94. The statically linked research probe SHA-256 is
`c9ab5a3d9d26bf1d53030b66c4afc32e90e2567d7bf3ed0ea80fc48c09270578`.
The co-built qwen.dll is identified but is not the executing engine.

The [tracked evidence](native-eos-corpus-evidence-20261121.json) records model,
codec, exact UTF-8 inputs, retained Kraftwerk conditioning, executable/DLL,
manifest and result hashes. The Bridge engine pin remains `130cb99`; no
working profile or frozen package changed. This tier used direct engine
callbacks, frontend OFF and segmentation OFF. No Bridge PCM commit, physical
playback, restart or RTX run occurred.

After the run, engine commit `5da56ed987ee83ea16d2c26ee75c89d88df3d2d9`
only reformats the corpus runner's model-family arguments/description. The
measured executable and retained run driver remain the recorded `0de7ec5`
identities; no inference or performance result is reassigned to the later HEAD.

## Baseline corpus results

Each model ran sequentially in one persistent engine: eight texts with seeds
64..79 (128 cases), six original-text controls and eight seed-64 repeats.
The [complete 284-row table](native-eos-corpus-observations-20261121.csv)
retains every baseline outcome. There were no missing cases, engine errors,
max-token stops, PCM/artifact errors or invalid decision captures.

| Observation | RU-stress Q8_0 | Base 1.7B Q8_0 |
| --- | ---: | ---: |
| Outcomes / natural EOS | 142/142 | 142/142 |
| Non-short corpus duration anomalies | 3/64 | 0/64 |
| Legitimate-short corpus cases, excluded from anomaly denominator | 64 | 64 |
| Legitimate-short outputs with <=12 frames | 62/64 | 56/64 |
| Repeated full raw-PCM and WAV identities | 11/11 | 11/11 |
| Warm direct callback TTFA p50/p95, ms | 179.235/180.722 | 178.789/180.320 |

RU-stress original text produced these new anomalous corpus outcomes:

| Seed | Frames | WAV duration | EOS after first PCM | Slack against first 80-ms chunk |
| --- | ---: | ---: | ---: | ---: |
| 72 | 6 | 0.48 s | 105.462 ms | -25.462 ms |
| 75 | 2 | 0.16 s | 22.155 ms | 57.845 ms |
| 78 | 3 | 0.24 s | 54.984 ms | 25.016 ms |

The table records duration anomalies; listening for these three subsequently
failed as described above. Baseline forcing was
OFF; the observer records sampled/effective EOS token 2150 and natural-EOS
finish reason, not a convergence-guard stop. The original nonempty text bytes
are unchanged. Why those seeds selected EOS is not established by a timing
hook: this run did not capture comparative forward/logit probabilities.

Of the RU-stress corpus, 32 text/seed pairs were already seen in the earlier
matrix; all 32 reproduce its full raw PCM. Among previously exposed non-short
pairs the proxy is 0/24; among non-short pairs absent from that matrix it is
3/40. This is not an unbiased held-out failure-rate estimate. Base plan flags
refer to reuse of pairs from the **RU-stress** matrix, not earlier same-Base
checkpoint evidence. No complete-code trace was enabled on these corpus runs.
The original Base controls 2/14/42 produced 89/85/94 frames, each repeated.

## Actual selection time, not whole-step time

The compile-flag-only observer timestamps the effective Talker choice before
predictor/codec work. It stores the first eight decisions and later EOS, with
no extra sampling, tensor readback or live PCM policy. Both clocks use the
probe's steady clock. A separate ON/OFF control used five seeds twice with
full trace: **10/10** matching metadata, complete codes, raw f32 and WAVs.
This supports output transparency in those cases, not zero measurement cost;
the sequential ON/OFF design is not a clean latency benchmark.

For warm N=1 corpus requests, an exact frame-3 selection exists in 92/141
RU-stress and 141/141 Base cases. RU has 49 earlier terminal decisions instead.
The exact frame-3 delay after first PCM was p50/p95 55.154/56.396 ms for RU
and 55.192/56.078 ms for Base; all observed warm frame-3/earlier-terminal
decisions fit within 80 ms. First-use frame-3 decisions miss by 33.260 ms
(RU) and 27.340 ms (Base).

**Seed 72 is a counterexample to a frame-3 detector:** it chooses non-EOS at
frame 3, then EOS at frame 6, too late for that first-chunk budget. Timely
observation of continuation at frame 3 does not establish complete speech.
Legitimate short answers also show why a universal frame minimum is unsafe.

## Paired timing controls

All five pre-frozen control stages completed, retaining 36 lane outcomes.
The paired observations below use the **latest decision relative to the
earliest first PCM**, not independent per-lane trials. Warm excludes the
entire first group. Each stage is tiny discovery evidence, not qualification.

| Untraced warm control | Groups | Frame-3 decision after earliest PCM | First-chunk budget misses |
| --- | ---: | ---: | ---: |
| Forced one-frame prefix, N=1 | 3 | 54.900..62.776 ms | 0/3 |
| Same prefix, N=2 | 1 | 88.930 ms | 1/1, by 8.930 ms |
| Independent N=2 | 3 | 98.289..105.750 ms | 3/3, by 18.289..25.750 ms |

The first 1920 f32 samples in each prefix-dual pair match exactly. However,
both differing second chunks had already reached the probe callback before
the frame-3 pair decision. The probe retains every lane and does not route a
winner to a player. No glitch-free transition or retractable PCM is implied.
Warm serial admission is about 160 ms for N=1, and about 161..163 ms **per
lane** for N=2, whose first PCM arrives around 355..357 ms. There is no
zero-cost state fork or demonstrated fresh-backup admission inside 80 ms.

## Retention, listening and next decision

All **320** outcomes, including short and unsuccessful-duration examples,
remain under `.tmp/base-acceptance/eos-corpus-decision-20261121/`. Sequential
probe times were 184.375 s RU, 219.562 s Base and 84.734 s controls, within the
authorized 1800-s combined budget. No further synthesis was launched for this
batch. `runtime-current/` retains the measured build; `runtime-before/`
preserves the older build. Final inventories and exact local analysis drivers
are retained. They are not transferred or backed up by Git.

For the first listening pass, open that root's **`listening-first-pass/`**:
19 numbered WAVs, byte-identical copies without trimming/gain/normalization.
It contains seed 64 for every text/model and all three corpus anomalies.
`LISTENING.md` links original files; the folder's manifest maps each copy to
its source/hash. Assess full text separately from pronunciation, voice,
artifacts and final tail. The subsequent 19-file listening result is recorded
above; all other new speech/listening verdicts remain unassessed.

The task-local timing driver is not a reusable failure-safe runner: assertions
or artifact errors could interrupt final bookkeeping. This run completed all
five stages and independent file/hash checks; no result was lost. The
tracked baseline runner has separate model-free failure-preservation tests.
The paired supplement preserves the earlier analysis rather than overwriting
it and makes the correlated timing boundary explicit.

Canonical research receipts:
[RU-stress](native-eos-corpus-ru-stress-cmp50hx-20261121.json) and
[Base](native-eos-corpus-base-cmp50hx-20261121.json). Neither supersedes older
listening. Release remains blocked. Local Release CTest: **11/11 PASS**,
including the observer and corpus contracts; corpus Python tests: **8/8 PASS**.

Next: keep waveform energy distinct from text recognizability. Include seed72,
the remaining file14 observation and legitimate short answers in discovery,
then freeze a separate evaluation
before choosing an EOS/continuation rule. Do not train and evaluate on these
same listening labels. Investigate serial admission/prefill for acceleration.
Do not install
a live selector based only on frame count or these discovery timings. Keep
frontend/segmentation A/B, actual commit/playback, restart and RTX gates open.
