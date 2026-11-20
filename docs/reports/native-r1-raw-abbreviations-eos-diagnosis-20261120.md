# RU-stress raw abbreviations: short-EOS diagnosis, 2026-11-20

Scope: exact frozen bridge candidate `aa2770ec8aeb45d59f42c96c3a1f4f2dc52390d8`,
qwentts `130cb99af9ae12d554962fd0920e08fb4268af01`, ABI6, CMP50HX UUID
`GPU-40361931-6cb5-ac58-a059-5ba3e70986fb`. Runtime, models and reference are
unchanged from the [canonical RU-stress receipt](native-r1-ru-stress-cmp50hx-20261120.json).
No production fix, sampling-default change or acceptance promotion was made.

## Input is not empty

The full input and logged effective text are identical:

> МГУ находится в Москве. Инженер проверил USB-порт, GPS и новый процессор.

This is 73 Unicode codepoints / 126 UTF-8 bytes, no embedded NUL. The original
engine log reports `N_text=22`. A model-free check using the exact talker GGUF
vocabulary/merges and native tokenizer regex independently produced 22 BPE
body tokens and roundtripped every original UTF-8 byte. This corroborates the
logged token count, but is not a retained historical runtime token dump.

Read-only source tracing found the complete string passed through launcher
`--text`, saver, client effective text, QTB JSON and native `request.text`
to `qt_params.text` and the prompt builder. Both native preflight and the
qwentts C ABI reject empty text. In raw mode, empty `normalized/pronunciation`
diagnostic fields mean the frontend was disabled, not that its empty result
was sent to TTS; `effective` remains the original string.

## Mechanism and reproduction bounds

The original engine itself logged `EOS at step 3`, `Generation done : 3 frames`.
The worker delivered 3 frames × 1920 samples, exactly 11520 PCM bytes / 0.24 s,
and the saver wrote all of them. This is not a WAV truncation, transport loss
or a request timeout. The WAV hash remains
`0411d394523849e46624cfa278a1e1e0d5ee66bdc7d785f33deafbafcd36566f`.
It contains 5760 samples, 972 nonzero, peak 949 and RMS 136.806 PCM16 units
(-47.587 dBFS); nonzero PCM is not proof of a delivered sentence.

A separate cold invocation of the unchanged packaged launcher with the exact
same raw text produced 93 frames / 7.44 s, natural EOS. The new WAV hash is
`803ab81ac592af9b500f82e181274183adfdba95142b51a644d618cc74ea223d`;
its content/pronunciation has not been listened to or accepted.

A bounded, prespecified six-request diagnostic used the existing nonshipping
benchmark with the exact packaged worker/runtime, no warmup and explicit seeds:

| Seed | Two repeat frame counts | Two repeat durations |
| --- | --- | --- |
| 42 | 101 / 101 | 8.08 / 8.08 s |
| 43 | 87 / 87 | 6.96 / 6.96 s |
| 44 | 83 / 83 | 6.64 / 6.64 s |

Each tested seed repeated its generated frame/byte length. None reproduced
the three-frame outlier; this is not a failure-rate estimate or an assertion
of PCM identity. The same-matrix front run also kept the exact same effective
text and produced 89 frames, so its result cannot establish a frontend fix.

At the pinned source, sampling is stochastic by default (temperature 0.9,
top-k 50, top-p 1, repetition penalty 1.05). Default seed `-1` resolves through
`std::random_device`. `suppress_initial_eos` masks EOS only for `step<2`;
from step 2 onwards, sampled codec EOS terminates the slot, including step 3.
The original resolved seed and per-step logits were not retained. Therefore
the premature-EOS mechanism is established, but why that exact trajectory
selected EOS—model probabilities, sampler policy or numerical effects—is
**not determined**. No unsupported attribution to one of them is made.

## Evidence and next boundary

Payload root: `.tmp/base-acceptance/native-r1-aa2770ec-20261120/`.
The canonical receipt hashes `diagnosis/short-eos-001/diagnosis.json`, source
stderr, fixed-seed manifest/results/logs/script and the separate cold-repeat
receipt/WAV. Originals, frozen corpus and package are preserved.

R1 remains NO-GO. Successful diagnostic repeats do not replace the original
outlier or supply a human-listening verdict. A corrective investigation needs
a reproducible short-EOS seed with resolved seed/token-probability tracing;
a duration floor, EOS suppression extension, retry or acceptance PASS is not
introduced by this diagnosis.
