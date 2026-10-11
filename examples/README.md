# Examples

The examples are intentionally small and model-agnostic. They use the same
async client API as an application; pass the worker executable as the first
argument after building the project. Native worker options are forwarded with
repeated `--worker-arg` switches.

1. `basic_synthesis <worker.exe> [--worker-arg <arg>]... [--text <text>]`
   starts a persistent worker and prints the size of each streamed PCM chunk.
2. `async_cancel <worker.exe> [--worker-arg <arg>]...` demonstrates request-ID
   cancellation without restarting the worker.
3. `post_processing` shows the backend-neutral audio post-processing chain.

The Windows `qwen_tts_play` example is the interactive player and accepts the
native worker's runtime arguments. The production release bundle should put
`qwen_tts_play.exe`, `qwen_tts_native_worker.exe`, the CUDA runtime, and a
user-managed `models/` directory beside one another; model weights are never
part of this repository.

When configured with `-DQWEN_TTS_BRIDGE_BUILD_SPEECH_ANIMATION=ON`, the player
can also emit playback-locked presentation selections without changing the
audio path:

```text
qwen_tts_play.exe --worker ... \
  --playback-animation-receipts-file animation.jsonl \
  --playback-animation-fps 60
```

The JSONL records are driven by the physical WaveOut cursor (or the deterministic
mock sink), translated to the utterance sample clock, and are intended for a
presentation consumer. They do not claim display latency or replace the audio
callback/playback sink.
