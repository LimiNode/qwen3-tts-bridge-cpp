# B2-4 Base 1.7B and registered-voice preflight

Status: **PASS for manifest and voice preflight; initial bounded real Base smoke PASS**.

This receipt follows merged Stage A C++/relocation evidence and freezes the
inputs needed for a separate Base acceptance run. It intentionally does not
claim model quality, corpus-level EOS reliability, playback stability, or
listening acceptance. The single initial smoke below did reach natural EOS;
that result is not a substitute for repeated B1/B2 EOS evidence.

## Frozen inputs

```text
bridge main: ebe928bf144486ec5debeb5f46910524cb340c81
portable runtime: sealed package from B2-4 Stage A
runtime build manifest: EEAB721B426813545CC82D6624BBE8D432050366266B67BF68463FE2BD514F88
runtime tree manifest: 40C9B1431CA5F8903A23C97D89A3CB0CDAB04AF9B12EE646562C5397493E9BBC
GPU: NVIDIA CMP 50HX, capability 7.5, driver 581.94, CUDA 12.8
```

### Base checkpoint

The external candidate is:

```text
E:\_repoz\qwen3-tts-bridge-cpp\tmp\cmp50hx-r3-external-models\Qwen3-TTS-12Hz-1.7B-Base
repository: Qwen/Qwen3-TTS-12Hz-1.7B-Base
revision: not present in the local export; no revision was invented
```

A complete doctor-schema-v2 manifest was generated outside Git at:

```text
E:\stage-a-base-evidence\qwen3-tts-12hz-1.7b-base-manifest.json
files: 13 (the model's transient .cache directory is excluded by the doctor contract)
directory_manifest_sha256: d47209b486d4e6929a554e09f5be87803309be68387ac075c0b1f7e62a1f7d66
```

The required files and hashes are:

| Relative path | Bytes | SHA-256 |
| --- | ---: | --- |
| `.gitattributes` | 1,519 | `11ad7efa24975ee4b0c3c3a38ed18737f0658a5f75a0a96787b576a78a023361` |
| `README.md` | 57,817 | `621b7e88f1867bc03d817176fc1f7f55f4b5a70654b2a07fdcda1e169efb024b` |
| `config.json` | 4,494 | `b4f01752d15a488abde3e1ab44723ae4f4b9e68a4037257b098b3737893cc1f9` |
| `generation_config.json` | 245 | `f1b90b4513f3b34c62851049e2492d7b4c5940daf1276f89c82b8ef04127f3aa` |
| `merges.txt` | 1,671,839 | `599bab54075088774b1733fde865d5bd747cbcc7a547c5bc12610e874e26f5e3` |
| `model.safetensors` | 3,857,413,744 | `38fc7fc51c5e776e840414b6fd443962e9411b9654888fd7913e4da643cb857c` |
| `preprocessor_config.json` | 127 | `efdde1022ea9d76928bf7a9cd53139138f5ba2e466e837f08f6105ab1af1c119` |
| `speech_tokenizer/config.json` | 2,336 | `ee65bb901c876664ab8707c487157aa1a6ee57c65969b28fb5ec9dc211e68167` |
| `speech_tokenizer/configuration.json` | 76 | `6bc26d64eb5024b4d1dab5a52371958b429256d6c9d59787f1f5294a54e0cebd` |
| `speech_tokenizer/model.safetensors` | 682,293,092 | `836b7b357f5ea43e889936a3709af68dfe3751881acefe4ecf0dbd30ba571258` |
| `speech_tokenizer/preprocessor_config.json` | 234 | `fcb3805e597e786d4067706e602f6688524640f8d3396790e2e09b5942fcbdfb` |
| `tokenizer_config.json` | 7,344 | `dc3c31c3bdaedd5016382bb3cbe07323026775ad51a5f4fb564505992ae4a670` |
| `vocab.json` | 2,776,833 | `ca10d7e9fb3ed18575dd1e277a2579c16d108e32f27439684afa0e10b1440910` |

The sealed portable doctor was run with `--model-path`, this manifest and
`--require-cuda`. It returned exit code `0`, `acceptance_pass=true`, and the
same CMP 50HX/CUDA identity.

### Registered voice

Deployment-local registry and copied reference asset are outside Git:

```text
E:\stage-a-base-evidence\voice-registry\voice-profiles.local.json
E:\stage-a-base-evidence\voice-registry\kraftwerk_robot_ru_fidelity.wav
voice_id: kraftwerk_robot_ru_bootstrap_fidelity
reference WAV: 844,844 bytes
reference WAV SHA-256: 90E5F7576991EA5B9F0A85E9109F7BD31FF667C4A12D58783A06C650796C3CA1
reference duration: 17.6 s at 24 kHz
preserve_reference_text_whitespace: true
```

The registry was validated both through `VoiceProfileRegistry` and through the
sealed portable doctor (`--voice-registry`, `--require-cuda`). Doctor reported
one registered voice with the expected ID. The profile remains an experimental
character profile, not a production identity claim.

## Initial real Base synthesis smoke

After the manifest and registry gates passed, one bounded real-model synthesis
was run against the relocated portable worker. This is an initial B1/B2 smoke,
not the complete acceptance run.

```text
worker: E:\stage-a-relocated\QwenTTSBridge\worker-python\qwen_tts_worker.cmd
model: Qwen3-TTS-12Hz-1.7B-Base
voice_id: kraftwerk_robot_ru_bootstrap_fidelity
text: Сегодня проверяем реальный русский голос.
runtime: faster / CUDA / bfloat16 / SDPA / eager prefill
compile: disabled
CUDA graphs: disabled
max_seq_len: 768
emit_every_frames: 8
elapsed: 56.248 s
```

Reproduction details for this bounded smoke were:

```text
harness: PackagedWorkerHarness from tests/python/verify_packaged_worker.py
invocation: E:\stage-a-relocated\QwenTTSBridge\worker-python\python\python.exe .tmp\base_utf8_smoke.py
worker command: qwen_tts_worker.cmd qwen --model-path <frozen-model> --runtime-backend faster --device cuda --dtype bfloat16 --attn-implementation sdpa --max-seq-len 768 --emit-every-frames 8 --decode-window-frames 80 --overlap-samples 0 --no-compile --no-cuda-graphs --prefill-backend eager --collect-generation-trace --voice-registry-path <frozen-registry> --engine-startup-mode auto
request: id=1, language=auto, registered voice_id, s16le/24000 Hz/mono
seed: not set (worker default request_id seed mode)
timeout: 600 s
portable environment: PYTHONHOME=<worker-root>python, PYTHONPATH=<worker-root>python\Lib\site-packages, PYTHONNOUSERSITE=1, `-B -P -s`
```

The temporary harness was not committed; the raw UTF-8 receipt and sealed
runtime manifests remain outside Git.

The run returned exit code `0` and produced five non-empty audio frames
(`140,940` PCM bytes). The worker reported `completed`, `termination_reason=eos`,
and `natural_eos=true`; it did not hit `max_new_tokens` or `max_seq_len`.
The generation trace contained 37 codec frames. The authoritative UTF-8 receipt
is retained outside Git at
`E:\stage-a-base-evidence\b1-real-base-smoke-utf8.json`.

This smoke proves that the frozen Base checkpoint, registered voice, relocated
worker, and CUDA runtime can complete one real synthesis and clean EOS. It does
not establish corpus-level EOS reliability, listening quality, a persistent multi-request sequence,
restart, cancellation/recovery, physical playback, or the full B1/B2 gates.

## Relocated C++ cross-check

The existing Release client (SHA-256
`DBD264613E432FEDD3D942B15C7DD40CC032A8A8F0E9D38B6B39373E79242B9D`) was run
directly against the relocated package at
`E:\stage-a-relocated\QwenTTSBridge\worker-python`.

Result: **PASS**, exit code `0`.

The client received two 100 ms mock chunks and wrote a validated 9,600-byte
WAV (24 kHz, mono, 16-bit PCM). Worker termination was `completed` with
`termination_reason=eos` and `hit_eos=true`.

## B1/B2 execution matrix

| Gate | Artifact/runtime | Model and voice | Required result | Status |
| --- | --- | --- | --- | --- |
| B1/B2 initial real smoke | relocated portable worker | external Base manifest + registered voice | one real PCM synthesis and natural EOS | **PASS** (initial smoke only) |
| B1 functional | sealed portable package + C++ client | external Base manifest + registered voice | real PCM, natural EOS, persistent sequence, restart, cancellation/recovery, playback/listening | **pending** |
| B2 clean portable | relocated package + same C++ client | same manifest and `voice_id`; no source paths | repeated real PCM and lifecycle from isolated artifact set | **pending** |
| C++ model-free regression | relocated package + Release client | mock engine | non-empty WAV and clean EOS | **PASS** |

The generic packaged-worker smoke is intentionally not being misclassified as
Base B2 acceptance. Real synthesis will start only from this frozen manifest,
registry, and explicit corpus. RTX 4090 validation remains a separate
post-freeze gate.
