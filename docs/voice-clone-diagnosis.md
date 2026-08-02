# Voice Clone ICL Diagnosis

This note records the investigation of two reported Base-model voice-clone
symptoms for `kraftwerk_robot_ru`:

- a reference-text fragment at the start of a new utterance, for example
  `nik nik` or a prior `rabotnik` fragment;
- apparent timbre or gender drift between utterances.

It is a diagnostic record, not a claim that Base ICL is suitable as the default
real-time profile.

## Environment

The evidence was collected on 2026-08-02 with the 1.7B Base model and the
repository example reference WAV.

| Field | Value |
| --- | --- |
| GPU | NVIDIA GeForce RTX 4090, 48 GiB |
| Driver | 591.86 |
| Python | 3.12.10 |
| Torch / CUDA runtime | 2.10.0+cu128 / 12.8 |
| Triton import version | 3.6.0 |
| FasterQwen source | `e4ac767277aad59095122cada01b174fbbb4f429` |
| FasterQwen source tree | `cfdb839c1b45b70ac5e8ade79650f31494b8d49c` |
| FasterQwen module SHA-256 | `0fb5cad8df298892562bcdbebb8dd0ab8069c954d1782da05b5d21bc60533287` |
| Reference WAV SHA-256 | `baba7f26a9eb8de1df53a51c4b33ac6cb3625fe70509d7c1a281b64d4827000b` |
| Reference WAV | 4.344 s, mono PCM, 44.1 kHz |
| Sampling | seed 4242, temperature 0.45, top-k 50, top-p 1.0, repetition penalty 1.05 |

The Faster source was clean and is available from the project fork at
[`prefill-compile-exact-shape`](https://github.com/LimiNode/faster-qwen3-tts/tree/prefill-compile-exact-shape).

## Method

`scripts/run-voice-clone-diagnosis.py` performs the same request sequences for
both profiles:

| Profile | Mode |
| --- | --- |
| `kraftwerk_robot_ru` | ICL reference-audio plus reference text |
| `kraftwerk_robot_ru_xvector` | x-vector-only speaker embedding |

Each profile was tested through four paths:

1. `raw_direct`: FasterQwen receives the WAV and reference text directly.
2. `cached_direct`: FasterQwen receives one precomputed voice-clone prompt.
3. `bridge_shared`: the persistent worker reuses its normal cached prompt.
4. `bridge_rebuild`: the worker rebuilds a prompt per request.

For every path the runner uses `A`, `A -> A -> A`, and `A -> B -> A`. It saves
the generated WAV outside the repository and records PCM SHA-256, codec SHA,
prompt SHA before/after generation, and post-generation graph-reset metadata.

## Results

The warm matrix completed 56 requests: 2 profiles x 4 paths x 7 requests.

| Check | ICL | x-vector |
| --- | --- | --- |
| `A -> A -> A` is bit-identical in all four paths | PASS | PASS |
| final `A` in `A -> B -> A` matches the preceding `A` | PASS | PASS |
| raw/cached/bridge `A` PCM is identical | PASS | PASS |
| prompt hash changes during a request | no | no |
| post-reset talker/predictor StaticCache length | 0 / 0, 0 | 0 / 0, 0 |

For the ICL profile, the warm `A` PCM SHA-256 was
`a81222b52498b7a2b02a89043ffa28bec0bb93a880958f06f479778dd04376d3`
for all four paths. The x-vector equivalent was
`7d41f30342079b09a4b98243ba9089f17ab9b324340e8409c76566897917bf81`.

The first cold request is different from a warmed request even with the same
seed. Its ICL PCM SHA-256 was
`f7fac5953dbbc524e61bd29553a4ef50141143802e25cd5fa78e3be5bea0d5eb`,
while subsequent requests converge to the warm hash above. The cold direct and
cold bridge paths matched each other, so this is a FasterQwen warmup/runtime
effect rather than a C++ transport or worker-profile-cache effect.

## Interpretation

The bridge does not account for the reported reference-text leak:

- the issue reproduces through `raw_direct`, before C++ transport, worker PCM
  conversion, profile cache reuse, or playback callbacks participate;
- rebuilding the prompt and sharing the prompt produce the same PCM under a
  fixed seed;
- traces show no prompt mutation and reset caches are empty after every
  completed request;
- the pattern is consistent with the known upstream Base ICL report
  [Qwen3-TTS issue #341](https://github.com/QwenLM/Qwen3-TTS/issues/341),
  which describes generated audio reproducing a reference-text suffix in a
  fresh official-process reproduction.

Fixed seed eliminates ordinary sampling variation after warmup. The observed
timbre changes in interactive use can therefore combine two distinct causes:
the cold first-request difference and stochastic sampling when no fixed seed is
selected. They should not be attributed to stale bridge PCM.

`do_sample=false` was also checked with a 4-second direct safety cap. It was
deterministic, but Base ICL did not reach a useful terminal result before the
cap, so greedy decoding is not adopted as a real-time default.

## Product Policy

- `kraftwerk_robot_ru_xvector` is the reliable low-latency profile. It avoids
  reference-code continuation and is the appropriate default for real-time
  applications that prioritize clean request boundaries.
- `kraftwerk_robot_ru` is an experimental, higher-fidelity ICL profile. It can
  sound closer to the reference, but callers must expect a possible
  reference-tail echo from the underlying Base model.
- A profile should be prepared during worker warmup or explicitly after voice
  selection. It must not first be prepared only when a time-critical text
  request is submitted.

## Reproduction

Use the pinned Faster source and the normal worker environment. This writes
diagnostic PCM outside version control by default:

```powershell
$env:PYTHONPATH = "C:\_repoz\faster-qwen3-tts-v032-stack112-clean;worker\src"
& C:\_repoz\qwen3-tts-bridge-cpp\.venv-faster-qwen\Scripts\python.exe `
  scripts\run-voice-clone-diagnosis.py `
  --model-path "$env:USERPROFILE\.cache\huggingface\hub\models--Qwen--Qwen3-TTS-12Hz-1.7B-Base\snapshots\fd4b254389122332181a7c3db7f27e918eec64e3" `
  --faster-source C:\_repoz\faster-qwen3-tts-v032-stack112-clean `
  --voice-registry config\voice-profiles.example.json `
  --output-dir tmp\voice-clone-diagnosis `
  --warmup
```

Use `--no-warmup` to inspect the cold-first-request effect and `--profile-id`
or repeated `--method` options to reduce the matrix during development.
