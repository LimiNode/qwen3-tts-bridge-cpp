# Example Voice-Clone Asset

`kraftwerk_robot_3_ru.wav` is a user-provided, restored, and processed Russian
robot-voice recording. The repository owner confirmed permission to include it
as a voice-cloning demonstration asset. It is not presented as an official
recording, endorsement, or affiliation with any artist or rights holder.

The matching profiles are in
[`config/voice-profiles.example.json`](../../config/voice-profiles.example.json):

- `kraftwerk_robot_ru` uses ICL conditioning, which most closely follows both
  the timbre and delivery of the recording.
- `kraftwerk_robot_ru_xvector` uses the same recording's speaker embedding only.
  It is useful when the ICL profile repeats or blends words from the reference
  transcript into a new utterance.
- `kraftwerk_robot_ru_bootstrap_fidelity` uses the selected 17.600-second
  synthetic ICL candidate in
  `voice-profiles/kraftwerk_robot_ru_fidelity.wav`. It is an experimental
  source-like character profile, not a claim of identity equality.
- `kraftwerk_robot_ru_bootstrap_warm` uses the selected 17.120-second
  synthetic ICL candidate in `voice-profiles/kraftwerk_robot_ru_warm.wav`.
  It is a separate warmer robotic character profile.
- `kraftwerk_robot_ru_source_like` uses the processed 12.731-second reference
  in `voice-profiles/kraftwerk_robot_ru_source_like.wav`. Local live listening
  accepted it as a stable source-like character profile, without claiming an
  identical source voice.
- `kraftwerk_robot_ru_warm_metal` uses the processed 13.022-second reference
  in `voice-profiles/kraftwerk_robot_ru_warm_metal.wav`. Local live listening
  accepted it as a stable warm metallic robotic character profile.

The clone launcher warms the selected profile before it accepts a text request;
it does not preload every registered profile. Its conservative default
temperature is `0.45`; use `-StyleExperiment` to enable interactive sampling
experiments.
Its verified SHA-256 is:

```text
baba7f26a9eb8de1df53a51c4b33ac6cb3625fe70509d7c1a281b64d4827000b
```

The bootstrap assets have these SHA-256 values:

```text
kraftwerk_robot_ru_fidelity.wav  90e5f7576991ea5b9f0a85e9109f7bd31ff667c4a12d58783a06c650796c3ca1
kraftwerk_robot_ru_warm.wav      b8285c5925d89d90435afa2f084a197a9e428dec41fff09c74969e6624a4b147
kraftwerk_robot_ru_source_like.wav b2480523e3dae70f2267260e3d60dce0c04dbe19f332f3fae6b031a54ab640f3
kraftwerk_robot_ru_warm_metal.wav  9c96c277ffb61709a511a01ee715bd4c15b1ccc669c9c55ca900f2229bb2799a
```

The bootstrap assets remain synthesized output derived from the authorized
example workflow. Do not use any example to claim an authentic source recording
or to impersonate a real person.
