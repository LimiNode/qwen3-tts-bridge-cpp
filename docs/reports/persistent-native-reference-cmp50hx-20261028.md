# Persistent native reference acceptance — CMP 50HX

Date: 2026-10-28
Scope: pinned `qwentts.cpp` ABI 6, Base Q8_0, Kraftwerk reference

This is a bounded equivalence and restart probe for PR-B. It does not claim a
real-time playback acceptance: the selected ABI-6 runtime produced RTF above
1 on this machine, so the generic probe correctly reported PCM starvation.

## Frozen inputs

| Artifact | SHA-256 |
| --- | --- |
| PR-B native worker | `f0ae86f73060af3d09908b3363eb91e0d563a2fc8c1ba2acf41546f14475823d` |
| `qwen.dll` | `4d7c1c653d88177037c915839df3f987a2a980f118ed74b91e6a8a9da0c816` |
| Base Q8_0 Talker | `4b9a33a236908dd9435a42f7a396e38038329d053b704342a6413c08544c4fda` |
| Q8_0 codec | `1883beeed99348fc35e23dd225e9082f93f6f8c109330a33d935baa8acdbfd94` |
| Runtime manifest | `f5a92008e4e9ad986fb5c0fb9ca1df65f71a30c132cb91e848c4565fd374c49b` |
| Kraftwerk reference WAV | `b8285c5925d89d90435afa2f084a197a9e428dec41fff09c74969e6624a4b147` |

Runtime: `qwentts.cpp/130cb99`, ABI 6, NVIDIA CMP 50HX, driver 581.94.
The synthesis text, transcript, seed (`1002`), model weights and codec were
fixed across all runs.

## Equivalence matrix

| Path | Startup/model preload | Profile preparation | Request → first PCM | Synthesis duration | Whole operation | EOS | WAV SHA-256 |
| --- | --- | --- | ---: | --- | ---: | --- | --- |
| A — direct raw WAV | model ready before request | decode + extract per request | ~3,927 ms | not isolated | ~7,182 ms | `natural_eos` | `7e824af59705f3de2addd19b30b96176936442e3aeedcfcc4232efb468cfd38d` |
| B — prepared first run | model ready before request | extract, persist, then use vectors | ~1,558 ms | not isolated | ~5,036 ms | `natural_eos` | same |
| C — prepared restart | model ready before request | load persisted manifest/artifacts | ~1,731 ms | not isolated | ~5,110 ms | `natural_eos` | same |

All three WAV hashes are identical. The first prepared run emitted
`native_voice_reference_ready source=extracted_and_persisted`; the restart
emitted `source=persisted` with a 5.5 ms load duration. Both prepared and raw
requests reported non-empty PCM, `completed`, and `natural_eos`.

The table intentionally does not present startup/model preload as a
request-path improvement: the prepared worker performs preparation before
`ready`, while the raw path performs it after admission. The available receipt
does not isolate synthesis duration from the whole-operation timings, so that
column remains explicitly marked as not separately measured rather than being
used to claim a persistence-only speedup.

The complete receipts remain local under:

```text
.tmp/persistent-native/raw.json
.tmp/persistent-native/prepared-first.json
.tmp/persistent-native/prepared-restart.json
```

The generic probe returned exit 1 for these runs solely because PCM arrival
gaps exceeded the preceding audio buffer. This is expected for the measured
RTF and remains a separate native streaming/performance gate. It does not
invalidate the persisted-reference equivalence or restart result.

Human listening: NOT RUN for this PR-B probe.
