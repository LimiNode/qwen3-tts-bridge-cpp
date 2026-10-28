# Voice registry compatibility

This document records the compatibility boundary for the `schema_version: 1`
voice registry used by the Python Base worker and the native process worker.
It is deliberately a metadata contract. A `voice_id` identifies a user voice;
the prepared prompt is owned by the selected model/backend and is not a shared
binary object.

## Shared metadata contract

Both process workers consume these fields:

```json
{
  "schema_version": 1,
  "voices": [
    {
      "voice_id": "my_voice",
      "reference_audio_path": "reference.wav",
      "reference_text": "Exact transcript.",
      "x_vector_only": false
    }
  ]
}
```

`preserve_reference_text_whitespace` is also supported by both workers. Relative
audio paths are resolved relative to the registry file. Duplicate IDs and
unknown IDs are errors. A valid profile is advertised through `ready.voice_ids`
and selected by `synthesize.voice_id`.

An explicitly supplied empty `voices` array is equivalent to a registry with no
profiles. Both workers accept it and report an empty `voice_ids` list. This is
the non-breaking policy for applications that pass a registry path before any
profiles have been created.

## Backend-specific preparation

The registry fields are shared, but the prepared data is not:

| Boundary | Python Base worker | Native process worker |
| --- | --- | --- |
| Model input | FasterQwen/model-owned prompt | `qt_voice_ref` from `qwentts.cpp` |
| Cache | bounded model prompt LRU | preloaded native reference cache |
| Preload | optional and bounded by configured cache size | all registered profiles before `ready` |
| Reference WAV | uncompressed PCM, mono or stereo, 8–96 kHz, 2–20 s | mono 24 kHz PCM16 or float32 |
| ICL preparation | Python adds its model-side reference boundary | native adds the same 0.5 s ICL silence before extraction |

The intersection above is the portable profile subset. A WAV that is valid for
the Python worker is not necessarily valid for the native worker. Native
selection must fail explicitly for an incompatible profile; it must not fall
back to Python silently.

The low-level in-process `NativeQwenBackend` remains a direct-reference adapter.
It accepts 24 kHz PCM buffers and transcript data, but does not load a registry
or expose `voice_id` lookup. This is intentional and is not evidence that the
two prompt representations are interchangeable.

## Audit coverage

The focused audit covers:

- the same registry and Kraftwerk profile in both process-worker paths;
- `ready.voice_ids`, repeated requests and native cache reuse;
- unknown and duplicate IDs;
- missing and malformed references;
- empty-registry behavior;
- Python-compatible but native-incompatible WAV formats;
- restart, cancellation and failed preload behavior where a real worker is
  available.

The native fake-runtime test remains deterministic and runs in CI. Hardware
acceptance uses the existing native probe and stores its receipt outside the
source tree under `.tmp/`. Audio quality and cross-backend speaker similarity
remain separate human-listening gates; identical PCM is not a requirement.

## Evidence

The first real native registry probe on CMP 50HX used:

- Q8_0 Base talker and 12 Hz codec;
- `kraftwerk_robot_ru_warm` with its exact transcript;
- `ready.voice_ids = ["kraftwerk_robot_ru_warm"]`;
- one registered-voice request reaching `natural_eos`;
- non-empty 24 kHz mono PCM output and worker exit code zero.

The probe receipt is local evidence and is not part of the release package:

`.tmp/cross-backend-audit/native-registry.json`

It does not claim Python/native acoustic identity. That requires a separate
fixed-seed comparison and human listening.
