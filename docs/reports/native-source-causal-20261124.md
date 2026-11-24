# Native/source causal comparison: verified preflight

- Status: preparation verified; native and source model execution **not run**.
- Date: 2026-11-24.
- [Frozen experiment plan](native-source-causal-plan-20261124.md).
- Branch: `research/native-source-causal`, based on Bridge `8ccdc515`.

## Confirmed local source and provenance

The exact merged source checkpoint is available locally. Its existing legacy
cache file `.models/ru-stress-20261006/merged3/model.safetensors` was read and
hashed, not copied or replaced. Its SHA-256 is
`9742ba7f6ca86732875c4a910f8f60988183c525c84e99dd724f02424ee88fe0`.
This matches [the conversion receipt](russian-stress-native-conversion.json)
and local merge receipt: official Base revision
`fd4b254389122332181a7c3db7f27e918eec64e3`, RU-stress LoRA revision
`e644ae00257fdd4db0e51b11057370dff6be8bc2`, rank16/alpha32/scale2;
196 modified LoRA pairs among480 source tensors. The existing checkpoint
remains a legacy input; no new `.models` content was added.

The installed source environment is Torch2.8.0+cpu, transformers4.57.3 and
safetensors0.8.0. CUDA is unavailable in that Torch installation. The installed
`modeling_qwen3_tts.py` has SHA-256
`9c5b54d9435604c6cbfda0fbbaeb77d4c959b0f95592b00f40c507f5364ede38`.
The repository upstream copy has a different hash and is **not** substituted
for the installed code or described as the code actually executed.

The pinned cossim helper hash is
`ac6c7de23cacab75c7c7a5317eda9994e3c19336832e56be3da9d0915852dca4`.
Only its historical upstream path literal is adapted in memory. An offline
CPU-only readiness check successfully loads its model/processor classes and
tokenizes all four frozen texts. Configuration confirms28 Talker layers,
hidden size2048, vocabulary3072 and16 codebooks. That check loads **no model
weights**, initializes no GPU and establishes no numerical or speech result.

The earlier source probe at
`.tmp/base-acceptance/streaming-eos-research-20261120/parity/probe.py` is
preserved unchanged. Its forced-history results concern another text/seeds,
not the four cases in the new plan. They do not establish why a bad native
history arose.

## Prepared implementation and checks

New local tools are under
`.tmp/pr-metadata/native-source-causal-20261124/`:
`run_source_causal.py`, `test_source_causal.py` and `check_helper.py`.
The runner uses the existing native dump/probe surface rather than changing
production code. It prepares exactly four capped native requests, compares
their complete code prefixes with corrected geometry run002, reconstructs
the source prompt, forces complete16-code histories, adds an exact-native-
embedding forward control, and separately retains bounded free trajectories.
Raw logits and the explicitly named allowed-vocabulary temperature1 probability
are not conflated with post-penalty/top-k sampler probabilities.

Four model-free runner tests pass: fixed case/seed selection, raw-distribution
semantics/finiteness, exact metrics/shape guards and explicit resource/scope
guards. The separate offline helper readiness check passes for all four texts.
These are preparation checks, not a passing matched-history experiment.

The frozen payload directory is
`.tmp/base-acceptance/native-source-causal-cmp50hx-20261124/run-001/`.
It currently contains plan, native manifest, pre-execution identity addendum
and CPU-helper readiness evidence. The machine plan records input/probe/
runtime/source hashes, including the complete source checkpoint identity.
Its frozen runner SHA-256 is
`ea13b66f43cbda5d531dda0e91e6355c080b1ae0cc00761b1cb269e241088a27`.
The native manifest SHA-256 is
`7adc621388aaba2a6a19727dfd13da436a9767c20fc946d376deb658df61520f`.
Do not overwrite the prepared files or earlier geometry payloads.

## Remaining execution and interpretation boundary

No native process was started: the shared batch deadline3170194.937
(2026-11-24T06:45:20Z) expired before an exclusive lease was available
for this child. The deadline was not reset. Consequently source model
execution, which requires the new exact native dumps, was not started either.
The native stage has a300s owned-process watchdog, source600s, a512MiB disk
reserve, and400/200MiB respective payload caps. These local watchdogs do not
extend or replace the coordinator's aggregate GPU deadline.

The earliest significant native/source divergence is **not checked** in the
new cases. Free source trajectory behavior and quantization sensitivity are
also **not checked**. An FP32 source/Q8 native difference alone could not
distinguish quantization from native arithmetic or conversion; an equal-
weight/high-precision native control remains separate work.

No new WAV listening assessment, acceptance gate or release qualification is
claimed. Existing canonical receipts retain their own exact scope. No engine
pin, sampler default, ABI, QTB, package, merge or publication changes. R1
remains **NO-GO**.
