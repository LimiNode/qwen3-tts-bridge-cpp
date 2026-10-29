# Example Voice Profiles

This directory is a self-contained collection of opt-in voice-cloning examples.
The profiles are not installed, imported into the managed user Voice Library, or
loaded by default. Pass `registry.example.json` explicitly when using them, or
add a selected recording to the managed library with `qwen-tts voices add`.

No model weights or generated native `.spk`/`.rvq` artifacts are included.
`native-prepared.example.json` is an illustrative template: provide a matching
`reference.wav`, exact transcript, and generated manifest before using it.

## Profile status

| Profiles | Status | Intended use |
| --- | --- | --- |
| `kraftwerk_robot_ru_source_like`, `kraftwerk_robot_ru_warm_metal` | Recommended examples | Stable character profiles accepted by local live listening; no identity-equality claim |
| `kraftwerk_robot_ru_bootstrap_fidelity`, `kraftwerk_robot_ru_bootstrap_warm` | Experimental | Synthetic bootstrap candidates retained for reproducible experiments |
| `kraftwerk_robot_ru`, `kraftwerk_robot_ru_icl_period*` | Historical/diagnostic | Short-reference and transcript-whitespace experiments; not recommended as general cloning defaults |
| `kraftwerk_robot_ru_xvector` | Diagnostic fallback | Speaker-embedding-only profile for cases where ICL repeats or blends reference words |

"Recommended" applies only within this opt-in example collection; it does not
promote a profile into the default beta support contract.

The short ICL transcript, `Я твой слуга, я твой работник`, can contaminate a
new utterance by repeating or blending reference words. The x-vector-only
variant avoids transcript conditioning but may preserve less delivery detail.
Reference quality, phonetic coverage, and exact transcription matter more than
recording length alone.

## Provenance and constraints

`kraftwerk/kraftwerk_robot_3_ru.wav` is a user-provided, restored, and
processed Russian robot-voice recording. The repository owner confirmed
permission to include it as a voice-cloning demonstration asset. It is not
presented as an official recording, endorsement, or affiliation with any
artist or rights holder.

The four longer assets are synthesized or processed character references
derived from the authorized demonstration workflow. Do not use these examples
to claim an authentic source recording, identity equality, or to impersonate a
real person. Additional evidence and status metadata live in
[`docs/voice-assets-provenance.json`](../../docs/voice-assets-provenance.json).

The registry preserves the exact accepted transcript text, whitespace flags,
and ICL versus x-vector-only modes. Do not normalize those fields when
reproducing historical acceptance results.

## SHA-256

```text
kraftwerk_robot_3_ru.wav            baba7f26a9eb8de1df53a51c4b33ac6cb3625fe70509d7c1a281b64d4827000b
kraftwerk_robot_ru_fidelity.wav     90e5f7576991ea5b9f0a85e9109f7bd31ff667c4a12d58783a06c650796c3ca1
kraftwerk_robot_ru_warm.wav         b8285c5925d89d90435afa2f084a197a9e428dec41fff09c74969e6624a4b147
kraftwerk_robot_ru_source_like.wav  b2480523e3dae70f2267260e3d60dce0c04dbe19f332f3fae6b031a54ab640f3
kraftwerk_robot_ru_warm_metal.wav   9c96c277ffb61709a511a01ee715bd4c15b1ccc669c9c55ca900f2229bb2799a
```

## Usage

Copy the directory before editing it. Relative audio paths resolve from the
registry file's directory, so the registry and `kraftwerk` directory must stay
together unless you deliberately update the paths.

```powershell
New-Item -ItemType Directory -Force .tmp | Out-Null
Copy-Item examples/voice-profiles .tmp/example-voice-profiles -Recurse
```

The playback launcher warms only the selected profile; it does not preload all
registered voices. Pass
`.tmp/example-voice-profiles/registry.example.json` as the registry path. The
launcher's conservative default temperature is `0.45`; use
`-StyleExperiment` only for explicit sampling experiments.

For a reproducible smoke test, select the bundled
`kraftwerk_robot_ru_source_like` voice. The Python runtime, model directory,
built player and CUDA dependencies are external prerequisites. A custom
`my_voice` requires a separate registry entry containing your own WAV and exact
transcript; pass that registry explicitly instead of changing this example
registry.
