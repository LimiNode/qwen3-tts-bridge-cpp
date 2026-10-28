# Persistent native voice references

The native process worker can persist Base-model voice conditioning as a
model-bound `.spk` / `.rvq` pair. This avoids WAV decoding, speaker extraction,
and codec encoding after a worker restart while preserving the existing
registry and `synthesize.voice_id` protocol contract.

This is an additive native optimization. A registry row without
`native_reference` continues to use the legacy WAV preload path.

## ABI feasibility

The pinned `qwentts.cpp` revision is `130cb99af9ae12d554962fd0920e08fb4268af01`.
Its existing ABI already provides everything required:

- `qt_extract_voice_ref` produces a malloc-owned `qt_voice_ref`;
- `qt_tts_params.ref_spk_emb`, `ref_spk_dim`, `ref_codes`, and `ref_T` accept
  decoded persisted data directly;
- `qt_num_codebooks` supplies the runtime codec layout;
- `.spk` is raw little-endian float32 data;
- `.rvq` is an 11-bit packed `[codebook, frame]` stream with frames fastest.

No new C ABI export is required. References extracted by the DLL are released
with `qt_voice_ref_free`. References loaded by the worker remain owned by
worker-side vectors and are never passed to the DLL allocator's free function.

## Registry contract

Add a `native_reference` object to a normal schema-1 voice row:

```json
{
  "voice_id": "my_voice",
  "reference_audio_path": "voices/my_voice/source.wav",
  "reference_text": "Exact reference transcript.",
  "x_vector_only": false,
  "native_reference": {
    "manifest_path": "voices/my_voice/native/manifest.json",
    "prepare_if_missing": true
  }
}
```

`manifest_path` must be relative to the registry directory and may not contain
`.` or `..` components. Reparse points are rejected. `prepare_if_missing` is an
explicit one-time preparation request: an absent manifest is generated from the
source WAV. An existing but stale, corrupt, or incompatible publication is
rejected and is never silently regenerated.

After preparation, deployments should normally set `prepare_if_missing` to
false or omit it. The source WAV remains the identity anchor and is not removed.

## Persisted manifest

The manifest format is `qwen3-tts-native-voice-reference`, schema version 1.
It records:

- source WAV SHA-256 and exact reference transcript;
- x-vector-only or ICL mode;
- qwentts engine commit and ABI version;
- Talker and codec SHA-256 identities;
- preprocessing version, 24 kHz mono input, float32 decode, and the 12,000
  sample ICL trailing-silence rule;
- speaker dimension, byte size, scalar layout, filename, and SHA-256;
- RVQ codebook count, frame count, 11-bit packing, layout, byte size,
  filename, and SHA-256.

An x-vector-only profile contains `reference.spk` and a null `rvq` manifest
entry. An ICL profile contains both `reference.spk` and `reference.rvq`.

Loading verifies the current source, transcript, mode, engine, ABI, models,
preprocessing, artifact sizes, hashes, speaker finiteness, and RVQ layout. A
source replacement at the same path, transcript edit, model change, truncated
artifact, invalid dimensions, or incompatible codec layout fails before
`ready`.

## Transaction and filesystem policy

Preparation writes temporary artifacts, reads them back, verifies the RVQ
round trip and manifest, publishes `.spk` and `.rvq`, and publishes the manifest
last. A profile is visible only when the manifest is present. Existing files
are never overwritten by `prepare_if_missing`; partial or ambiguous output is
rejected. Owned temporary and partially published files are removed on failure.

Startup emits a `native_voice_reference_ready` metric whose `source` is either
`persisted` or `extracted_and_persisted`, together with the bounded preparation
or load duration.

The first CMP 50HX ABI-6 equivalence probe produced identical raw-WAV and
persisted-restart PCM, but did not pass the separate real-time streaming gate
(RTF was above 1 and the probe detected starvation). See
[`reports/persistent-native-reference-cmp50hx-20261028.md`](reports/persistent-native-reference-cmp50hx-20261028.md).

## Future CLI boundary

This change deliberately does not add the complete Voice Library CLI. The
planned command remains:

```text
qwen-tts voices prepare <voice_id> --backend native --native-profile <profile>
```

That command can create or update the registry row and invoke this bounded
preparation contract. It must not duplicate native extraction, serialization,
validation, or synthesis logic.
