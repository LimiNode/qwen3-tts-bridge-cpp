# Speech-animation integration boundary

`qwen3-tts-bridge-cpp` is the speech backend. It owns text preparation,
Qwen inference, streaming PCM, and the canonical sample timeline. A future
`speech-animation` component consumes that output; it is not implemented in
this repository.

```text
tts-front-cpp
    -> PreparedText / pronunciation context
    -> qwen3-tts-bridge-cpp
       -> PCM + sample-addressed timing
       -> optional Qwen terminal diagnostics
    -> speech-animation
       -> audio analysis / visemes / avatar policy
```

## Downstream inputs

For prepared requests, `TtsCallbacks::on_text_prepared` receives the exact
frontend context once before audio when the worker starts the request:

* original source text;
* normalized frontend text;
* pronunciation text;
* semantic stress decisions;
* warnings and uncertainty.

`TtsCallbacks::on_timing` receives a lightweight sideband event for each PCM
chunk. It is addressed by sample position, not callback arrival time. The
callback carries no viseme decision and no phoneme ground truth.

## Realtime rules

The timing sideband is informational and must remain cheap and non-blocking.
Audio delivery does not wait for animation analysis. Applications that need
heavier DSP should publish the bounded `PcmChunk`/`SpeechTimingChunk` pair to
an owned downstream queue with an explicit overflow policy. Analyzer failure
must not stop PCM delivery unless the application explicitly chooses a
fail-closed policy.

The bridge does not add an intentional playback delay for animation. Physical
playback and avatar scheduling remain outside the core client.

## Dependency direction

The bridge may expose a future optional integration target, but the core build
must not depend on a generic lipsync, Unity, Godot, VRM, SALSA, or viseme
library. A downstream animation package may depend on the bridge's public
client/data headers; the bridge must not know that package's policy or model.
