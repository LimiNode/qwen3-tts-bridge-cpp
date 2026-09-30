# Examples

The examples are intentionally small and model-agnostic. They use the same
async client API as an application; pass the worker executable as the first
argument after building the project.

1. `basic_synthesis <worker.exe> [text]` starts a persistent worker and prints
   the size of each streamed PCM chunk.
2. `async_cancel <worker.exe>` demonstrates request-ID cancellation without
   restarting the worker.
3. `post_processing` shows the backend-neutral audio post-processing chain.

The Windows `qwen_tts_play` example is the interactive player and accepts the
native worker's runtime arguments. The production release bundle should put
`qwen_tts_play.exe`, `qwen_tts_native_worker.exe`, the CUDA runtime, and a
user-managed `models/` directory beside one another; model weights are never
part of this repository.
