# Native voice registry acceptance — CMP 50HX

Date: 2026-10-28
Scope: native process worker, Base Q8_0, registry-selected Kraftwerk profile

This bounded probe validates the existing `--voice-registry-path` plus
`synthesize.voice_id` path. It is not the direct `--ref-wav` path and does not
claim Python/native acoustic identity.

## Frozen inputs

| Artifact | SHA-256 |
| --- | --- |
| `qwen_tts_native_worker.exe` | `c75367abbb5557da5333a4bd2dae607ee6461314ed3ca6ef2e478868a423b925` |
| `qwen.dll` | `bca91de322186dd15bdf4bb1a1b4ee00b246aa6bacf61d8c53439bbf496efae9` |
| Base Q8_0 Talker | `4b9a33a236908dd9435a42f7a396e38038329d053b704342a6413c08544c4fda` |
| Q8_0 codec | `1883beeed99348fc35e23dd225e9082f93f6f8c109330a33d935baa8acdbfd94` |
| Runtime manifest | `864750ebaf1a91db67b8a6849844f550a40546b3a45c94759e35b049cccdd2b4` |
| Voice registry | `ca0e44e3f08332514e9c5cf847fbeed88b018df94edb3a4621401f3d24316c1e` |
| Kraftwerk reference WAV | `b8285c5925d89d90435afa2f084a197a9e428dec41fff09c74969e6624a4b147` |

The worker reported `0.2.0-native-qwentts/ed3c665 (2026-09-14)`.
The hardware identity was NVIDIA CMP 50HX, 20,480 MiB, driver 581.94. The
registry advertised exactly `kraftwerk_robot_ru_warm` in `ready.voice_ids`.

## Persistent-session result

Two requests selected the same `voice_id` in one worker process:

| Request | First PCM | PCM bytes | Terminal | Registry cache | Decode | Extract |
| --- | ---: | ---: | --- | --- | ---: | ---: |
| 1 | 1,366.36 ms | 192,000 | `completed`, `natural_eos` | hit | 0 ms | 0 ms |
| 2 | 188.25 ms | 215,040 | `completed`, `natural_eos` | hit | 0 ms | 0 ms |

The process exited with code zero. Both `request_finished` metrics reported
`voice_reference_cache_hit: true`, `reference_audio_decode_ms: 0`, and
`voice_reference_extract_ms: 0`. The profile was decoded and extracted before
`ready`; neither request repeated that work on its critical path.

The complete local receipt is intentionally outside the source tree at:

```text
.tmp/cross-backend-audit/native-registry-repeat.json
```

Model weights, binaries, PCM, and local absolute paths are not committed.
