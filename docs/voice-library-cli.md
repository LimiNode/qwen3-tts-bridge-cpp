# Voice Library CLI

[Русская версия](voice-library-cli-ru.md)

The release-facing `qwen-tts` CLI keeps reusable Base voice-clone profiles in a
user-owned schema-1 registry. The library is separate from the sealed
installation and does not modify or remove the source WAV supplied by the user.

The default registry is:

```text
%LOCALAPPDATA%\QwenTTSBridge\voices\registry.json
```

Set `voice_library.registry_path` (or the legacy-compatible
`voice_registry_path`) in the schema-1 user config to use another location.
Relative paths are resolved next to that config file.

## Commands

Register a reference recording:

```powershell
qwen-tts voices add --id kraftwerk-ru --wav .\kraftwerk.wav `
  --text "Точный текст записи."
```

Use `--x-vector-only` when the native profile intentionally has no transcript.
Use `--preserve-reference-text-whitespace` only when the exact whitespace is
part of the profile contract; otherwise text is trimmed before it is stored.

Inspect the library:

```powershell
qwen-tts voices list --json
qwen-tts voices show kraftwerk-ru --json
qwen-tts voices verify kraftwerk-ru --backend python
```

Prepare a model-bound native reference through the authoritative native worker:

```powershell
qwen-tts voices prepare kraftwerk-ru --backend native `
  --native-profile q8-base-17b --json
qwen-tts voices verify kraftwerk-ru --backend native `
  --native-profile q8-base-17b
```

Preparation uses the existing native worker and its persistent-reference
implementation. Python does not duplicate `.spk`/`.rvq` extraction or
serialization. A successful preparation publishes the manifest last and then
records `prepare_if_missing: false` in the authoritative registry row. Each
exact runtime/model binding gets a separate digest-keyed entry under
`native_references`; changing a configured model cannot silently reuse the old
artifacts. A manually authored singular `native_reference` remains supported.

## Filesystem and failure policy

Voice IDs are display identifiers, not filesystem paths. Managed copies are
stored below a SHA-256-derived directory under the registry directory. Registry
writes are atomic and guarded by an OS-backed exclusive lock. The lock is
released automatically when its owning process exits, including abnormal
termination; the lock file itself may remain as a reusable coordination
handle. Existing managed WAVs and native manifests are never silently replaced.
A stale or corrupt native manifest fails closed and must be explicitly removed
before a new preparation.

Native manifests are bounded and validated against the native loader contract:
speaker data is finite little-endian float32 within the native dimension and
size limits, while ICL RVQ data uses the fixed 11-bit codebook-major layout and
bounded dimensions. Native preparation accepts only structured `qtb_metric`
evidence for the exact voice and an acknowledged graceful shutdown. Native
manifests are bound to the source WAV hash, transcript, x-vector mode,
talker/codec model hashes, and artifact hashes. `voices verify --backend native`
reports `prepared_valid`, `prepared_stale`, `prepared_corrupt`, `unprepared`, or
`model_unavailable` without regenerating anything. A `prepared_valid` result is
explicitly a `static_manifest` validation; the runtime-dependent RVQ codebook
count is authoritative only after the native worker loads the selected DLL and
codec context during preparation or synthesis.

This command family does not download models, create VoiceDesign voices, or
promise that a native profile is interchangeable with a Python prompt. Backend
compatibility remains explicit and model/runtime bound.

To back up or move the library, copy the whole `voices` directory while no CLI
mutation is running. The managed WAV is portable Python reference material;
native artifacts remain valid only with the runtime and exact model hashes
recorded in their manifests. The original user-owned recording is never part of
an automatic delete or migration operation.
