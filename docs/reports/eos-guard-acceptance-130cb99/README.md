# EOS guard acceptance — qwentts 130cb99

This report records a reproducible supplementary semantic matrix for the native
1.7B Base Q8_0 runtime. It is deliberately separate from the earlier
mechanical 16-run smoke package: the texts are committed in `texts.json`, and
the run metadata is in `matrix.json`.

## Result

Sixteen fresh CLI runs completed successfully on a CMP 50HX: four explicit
English/Russian texts, two seeds, and guard off/on pairs. There were no
`max_tokens` or `eos_forced` outcomes in this supplementary set. Guard-assisted
termination occurred for `ru_short` at both seeds and `en_long_punct` at both
seeds; all other rows reached `natural_eos`. The paired WAV hashes show that
the guard did not alter these trajectories where it did not need to intervene.

This is evidence that the guard is mechanically bounded on this sample, not a
claim that assisted termination is always perceptually safe. The paired WAV
files in the external artifact directory still need human listening review for
clipped endings, missing words, and unnatural prosody before enabling the guard
in Bridge.

## Reproduction contract

- Runtime: qwentts `130cb99af9ae12d554962fd0920e08fb4268af01`.
- Binary, model, codec, and reference hashes: `hashes.json`.
- GPU: NVIDIA CMP 50HX, CC 7.5, 20,479 MiB.
- Model: 1.7B Base Q8_0; reference speaker embedding only.
- Each run used a new CLI process, no startup synthesis warmup, and
  `--max-new 256`; therefore TTFA values are not persistent-worker latency
  measurements.
- Raw logs and WAV files are retained at the path in `hashes.json`; their
  hashes are recorded in `matrix.json` and `texts.json`.

The historical 16-run guard smoke remains useful for runaway detection, but
its original text payload was not recorded. This report does not silently
reconstruct that missing provenance; the new matrix is the canonical
text-addressable follow-up.

## Gate status

Mechanical EOS behavior: **pass for this bounded sample**.

Listening/semantic acceptance: **open** until paired WAVs are reviewed. Keep
the guard opt-in and do not repin or enable it in Bridge solely from this
report.
