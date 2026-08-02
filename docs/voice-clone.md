# Local Voice Clone

Base Qwen3-TTS models can synthesize speech from a local reference WAV. This
is separate from the `0.6B-CustomVoice` preset-speaker model used by the normal
playback CLI. A reusable Base voice profile stores its reference metadata on
disk and creates the model-ready prompt once per persistent worker process.

The local `kraftwerk_robot_3_ru.wav` reference is 4.344 seconds long and has
been smoke-tested through the C++ CLI with the cached `1.7B-Base` model. A few
seconds of clear reference speech can be enough, but quality remains sensitive
to recording quality, transcript accuracy, and the target text.

## Create, Test, and Save a Profile

Use the dedicated creation command to preflight a reference WAV, run a short
test synthesis, and then explicitly save or discard the profile. Creating a
profile is separate from normal playback; it does not turn every future request
into a fresh clone operation.

```powershell
.\scripts\new-qwen-tts-voice-profile.ps1 `
  -VoiceId kraftwerk_robot_ru `
  -ReferenceAudioPath .\examples\assets\kraftwerk_robot_3_ru.wav `
  -ReferenceText 'Я твой слуга, я твой работник' `
  -TestText 'Я твой робот. Я твой работник.'
```

Pass `-Save` to skip the final confirmation. The default output is the ignored
`config/voice-profiles.local.json`. You can also begin from the checked-in
example:

```powershell
Copy-Item config\voice-profiles.example.json config\voice-profiles.local.json
```

The script uses the locally cached `Qwen/Qwen3-TTS-12Hz-1.7B-Base` model when
available and the repository's vendored `Qwen3-TTS-streaming` source. Pass
`-ModelPath` to select another local snapshot or Hugging Face model ID.

## Use a Saved Profile

Select a registered voice when starting the Base-model playback example:

```powershell
.\scripts\start-qwen-tts-clone-play.ps1 `
  -VoiceRegistryPath .\config\voice-profiles.local.json `
  -VoiceId kraftwerk_robot_ru
```

In the interactive CLI, use `/voices` to list the profile IDs advertised by the
worker and `/voice kraftwerk_robot_ru` to select one for future requests. A
new line of spoken text cancels the prior generation as usual.

Registry JSON is durable metadata, not a serialized GPU prompt. In a running
worker, the selected profile is converted into a Base-model voice prompt once
and retained in a bounded LRU cache. Restarting the worker re-creates that
in-memory prompt on the first use, but it does not require reauthoring or
re-entering the profile.

The preflight accepts local uncompressed PCM WAV files only: mono or stereo,
8--96 kHz, 8/16/24/32-bit, 2--15 seconds, non-silent, and at most 16 MiB. ICL
profiles require an accurate transcript; `-XVectorOnly` is an explicit fallback
that omits it.

The repository's example asset is user-provided, restored, and processed; the
owner confirmed permission to publish it. Its provenance and SHA-256 are in
[`examples/assets/README.md`](../examples/assets/README.md). Generated audio
is still synthesized. Use only references you are permitted to process, label
generated output as synthesized, and do not use any profile to impersonate a
real person.
