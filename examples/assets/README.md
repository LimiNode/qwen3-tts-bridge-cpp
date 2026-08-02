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

The clone launcher preloads registered profiles and primes the selected profile
before it accepts a text request. Its conservative default temperature is `0.45`;
pass `-Temperature` to tune the amount of sampling variation.
Its verified SHA-256 is:

```text
baba7f26a9eb8de1df53a51c4b33ac6cb3625fe70509d7c1a281b64d4827000b
```

Generated audio remains synthesized output. Do not use the example to claim an
authentic source recording or to impersonate a real person.
