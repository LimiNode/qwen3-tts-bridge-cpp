# CMP 50HX dump-off/dump-on transparency probe

This is a bounded seed-1002 smoke on the canonical qwentts.cpp runtime
`114f7732e832ec7df1a474d8160aedbeda5bca43`, repinned by Bridge merge
`b2992eda74b79192fcf82903c98c9cd2cffeccb8`. Both invocations used the same
F32 models, `.spk/.rvq`, prompt, seed, sampling parameters, and
`max_new_tokens=3`; the only intended difference was diagnostics OFF versus
`--dump <directory>`.

## Observed result

Both processes exited successfully and both reported `Generation done : 3
frames`. The decoded WAV files are byte-identical:

```text
off/on audio SHA-256 = C984763E6CFDB19345A2B58427689E755A8265166DF8B189DA269EB7294BAE9D
```

The OFF log contains only Talker steps 0 and 1:

```text
step=0 c0=1445 subseq=0
step=1 c0=1332 subseq=16
```

This is expected from the current compact trace condition: it logs only
`subsequence < 32`. Frame 2 starts at subsequence 32, while the dump-enabled
path opts into the bounded full-frame trace and records:

```text
step=2 c0=845 subseq=32
```

Therefore the missing OFF line is not evidence of EOS or a changed frame
count. It is a logging-bound difference.

## Evidence boundary

The run establishes completion and audio-level transparency, but it does **not**
establish byte-identical token trajectories: diagnostics OFF did not emit
`codes-full.bin` or predictor-code lines for frame 2. The report deliberately
does not promote the ON dump into proof of OFF/ON token equality.

The next gate is a canonical no-diagnostic-graph trace that records all c0 and
predictor codes while leaving graph construction unchanged. Only after that
comparison should the component tensors from the dump-enabled run be used as
authoritative parity evidence.

Machine-readable details and SHA-256 fingerprints are in [`evidence.json`](evidence.json).
Raw logs are [`native-off.raw.log`](native-off.raw.log) and
[`native-on.raw.log`](native-on.raw.log).
