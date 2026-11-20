# Native early-EOS detector: frozen-prefix and causal gate replay

Date: 2026-11-20. Status: **hypothesis-generating research, not a fix or
acceptance PASS**. No GPU job, retry, live PCM gate, engine change, default
change, or frozen-package modification was performed for this replay.
R1 remains **NO-GO**. See the separate
[latency/source comparison](native-streaming-latency-research-20261120.md).

## Inputs, identity, and reproducibility

The unchanged discovery run is
`.tmp/base-acceptance/native-r1-aa2770ec-20261120/diagnosis/short-eos-seed-sweep-001/scan-000-031/`.
It used bridge `aa2770ec8aeb45d59f42c96c3a1f4f2dc52390d8`, qwentts
`130cb99af9ae12d554962fd0920e08fb4268af01` / ABI 6, RU-stress Base 1.7B
Q8_0, registered Kraftwerk ICL reference, CMP 50HX UUID
`GPU-40361931-6cb5-ac58-a059-5ba3e70986fb`, max 256 tokens, and explicit
seeds 0..31 in order. There was no warmup; seed 0 is first-use/cold.
Every request used this complete, nonempty text:

> МГУ находится в Москве. Инженер проверил USB-порт, GPS и новый процессор.

The read-only analyzer aligns request labels/seeds/text with benchmark request
IDs, serial Talker/predictor traces, first PCM signal, and terminal metadata.
It rejects mismatched counts, seed order, interleaved IDs, missing/malformed
features, inconsistent frame counts, and invalid chunk/terminal order.
Each output row retains the first three Talker samples and all 16 predictor
codes for those frames, first PCM RMS/peak, actual callback arrival timestamps,
and the input text hash. It does not infer missing EOS logits.

| Input file | Bytes | SHA-256 |
| --- | ---: | --- |
| `requests.jsonl` | 8,130 | `5cc501964dbd85f4e0c7922a8aed9463e51b68044bfd4ef49b0002c662615fea` |
| `benchmark.json` | 91,897 | `31739bca62a0ed629c26bad726dc65c45fbdb181a59e39a6f2b609b2b070250a` |
| `stderr.log` | 544,836 | `eb5547a26b526e13f056a2ba5749902122345775b6eca0c24e485a996abbb3ec` |
| `invocation.json` | 3,274 | `98d31f22eadffe5cd01cbe1ed70318f0c5f683b5f720a1c28e78c339b5ec8558` |

Run from a checkout with Python 3.11, replacing the repository prefix if needed:

```powershell
py -3.11 -B scripts/analyze-early-eos-replay.py `
  --run-dir E:\_repoz\qwen3-tts-bridge-cpp\.tmp\base-acceptance\native-r1-aa2770ec-20261120\diagnosis\short-eos-seed-sweep-001\scan-000-031 `
  --output E:\_repoz\qwen3-tts-bridge-cpp\.tmp\base-acceptance\streaming-eos-research-20261120\detector-replay\analysis-v3.json
```

Output creation is exclusive: choose a new filename when repeating the command.
`analysis-v2.json` added the exact analyzer identity to the initial diagnostic
`analysis.json`. The current `analysis-v3.json` separates text-only gate
eligibility from retrospective terminal-dependent labels. A non-natural
terminal must not retroactively bypass a gate. The all-natural discovery
policy and classifier results below are unchanged. All historical outputs
remain preserved; choose a new filename on rerun.

- Analyzer SHA-256:
  `2d9a86d3001ec6e8431ff91de938c84e681d28d7d56c2676d31b209b34a0de31`.
- `analysis-v3.json` SHA-256:
  `4b847f052f8a899621d051458c90da96634ab750b6c163b33acae99e074c46a6`.

## Labels and split: narrow duration proxy, not speech truth

The replay rule labels natural-EOS results of at most 12 codec frames as
duration anomalies only when input has at least six alphabetic words and
24 alphabetic characters. Short legitimate input such as "Да!" is unassessed
and bypasses the replay gate; shortness alone is not a failure label.
The six-word/24-letter rule is a research exclusion, not a qualified semantic
or language-independent detector.

Seeds 0..15 are the training subset; seeds 16..31 are the held-out seed subset.
For each horizon 1/2/3, the candidate is the exact set of Talker c0 prefixes
from training positives, frozen before scoring the held-out subset. The scoring
decision sees only the observed prefix, never the terminal or total duration.
Training positives are seeds **2, 4, 14**; held-out positives **21, 31**.

This is a deterministic split of previously inspected discovery data, not a
blind prospective validation. Every seed uses the same text/reference/model.
There are **no held-out texts, human/ASR coverage labels, independently qualified
negative examples, or semantic quality measurements**. A longer WAV and natural
EOS do not establish complete or correct speech.

## Prefix-risk candidates fail to generalize

Counts below refer only to the duration proxy. TP/FP/TN/FN have their usual
confusion-matrix meaning; an FP is a non-short proxy result, not proved good
speech. No unassessed examples occur in this original long-text run.

| Observed frames | Frozen training-positive Talker prefixes | Train TP / FP / TN / FN | Held-out TP / FP / TN / FN |
| ---: | --- | --- | --- |
| 1 | `[251]`, `[462]` | 3 / 6 / 7 / 0 | 2 / 9 / 5 / 0 |
| 2 | `[251,1609]`, `[462,462]` | 3 / 1 / 12 / 0 | 0 / 1 / 13 / 2 |
| 3 | `[251,1609,302]`, `[462,462,251]`, `[462,462,619]` | 3 / 0 / 13 / 0 | 0 / 0 / 14 / 2 |

The first-code candidate catches 2/2 held-out anomalies but flags 9/14 controls:
**64.29% false-positive rate**. Two/three-code candidates miss both held-out
anomalies. The apparently perfect training result at three codes is overfit;
it is not evidence for a production selective gate. Full predictor codes are
retained for future independent work, not used to invent another threshold on
the same held-out results.

First PCM energy is not sufficient either:

| Seed | Total codec frames | First three Talker c0 | First-chunk PCM16 RMS |
| ---: | ---: | --- | ---: |
| 2 | 3 | `462,462,619` | 0.158114 |
| 4 | 5 | `462,462,251` | 0.135015 |
| 14 | 3 | `251,1609,302` | **152.147** |
| 21 | 10 | `462,1474,251` | 0.138819 |
| 31 | 4 | `462,1225,1485` | 0.142522 |

Seed 14 is an early-termination anomaly with appreciable first-chunk signal.
Do not label every low-energy start bad, or treat nonquiet audio as proof of
speech coverage. No energy threshold was fitted post hoc.

## Causal startup-gate replay and latency cost

The replay uses **actual chunk arrival timestamps**, with native 1/2/4/8-frame
chunk progression and 1,920 samples per codec frame at 24 kHz. Gate N releases
only once cumulative audio is **strictly greater than N frames**. Reaching
exactly N frames does not reveal the next EOS decision; a three-frame failure
must not be released merely because its third frame has arrived. Withholding
at terminal represents a failed attempt with no committed PCM, not recovery.

This table replays unconditional fixed startup horizons for eligible text,
not the unsuccessful selective prefix classifiers above. Added first-PCM
latency uses the 26 warm non-short results and paired per-request differences;
median averages the middle pair, p95 is nearest rank `ceil(0.95*n)`.

| Horizon N | Proxy anomalies whose PCM already escaped | Attempts still uncommitted at terminal | Added first-PCM p50 / p95, ms |
| ---: | ---: | ---: | ---: |
| 0, immediate | 5 | 0 | 0 / 0 |
| 1 | 5 | 0 | 49.348 / 49.995 |
| 2 | 5 | 0 | 49.348 / 49.995 |
| 3 | 3 | 2 | 139.181 / 141.136 |
| 12 | 0 | 5 | 310.034 / 312.551 |

Horizons 1 and 2 both release at the second chunk; horizon 3 waits until the
third chunk (seven cumulative frames). Horizon 12 hides this <=12-frame proxy
**by construction**, not through independent recognition of defective speech.
The extra ~310 ms would affect every eligible request, so it is not a free
solution compatible with a blanket low-latency claim. No replayed policy was
applied to physical playback or combined with retry/deadline/cancellation.

## Outcome and remaining work

- Retain immediate streaming as the control. Do not install the code-prefix
  candidate or a fixed 12-frame gate as a production default from this study.
- Collect EOS/logit/rank/sampler diagnostics on explicitly recorded seeds and
  expand to independent texts, short legitimate utterances, languages, and
  reference variants. Establish scoped content/coverage labels separately.
- Evaluate any revised candidate without refitting on these held-out failures.
  Report false positives, false negatives, overhead, and physical TTFA rather
  than only training accuracy or WAV length.
- Any retry policy must decide before irreversible playback of an attempt,
  retain one absolute deadline, respect cancellation, and never duplicate
  committed speech. None of those properties is established by this replay.

Validation: **9/9** model-free unit tests pass, covering short-text exclusion,
strict `>N` ordering, missing/malformed features, seed alignment/interleaving,
no held-out-label fit, future-terminal-independent gate decisions, input
immutability, and exclusive output creation.
Ruff check/format and Pyright pass for both script and test module. This report
does not change acceptance receipts or close any mechanical/listening/release
gate; it only records a reproducible read-only analysis of preserved evidence.
