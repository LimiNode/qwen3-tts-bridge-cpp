#include <qwen_tts_bridge/native.hpp>

#include <cassert>

int main() {
    using qwen_tts_bridge::native::NativeQwenBackend;
    using qwen_tts_bridge::native::NativeQwenBackendOptions;
    using qwen_tts_bridge::native::NativeQwenCompletion;
    using qwen_tts_bridge::native::NativeQwenFinishReason;

    NativeQwenBackendOptions options;
    options.talker_path = "missing-talker.gguf";
    options.codec_path = "missing-codec.gguf";
    options.stream_max_chunk_frames = 4;
    NativeQwenBackend backend(options);

    // This is an ABI/linkage smoke test, not a model test. Missing GGUF files
    // must fail locally and leave a diagnostic without crashing the process.
    assert(!backend.is_ready());
    assert(!backend.last_error().empty());
    assert(!backend.version().empty());

    const auto capabilities = NativeQwenBackend::capabilities();
    assert(capabilities.stream_max_chunk_frames);
    assert(!capabilities.codec_window);
    assert(!capabilities.sequence_capacity);
    assert(!capabilities.playback_prebuffer);
    assert(!capabilities.prefix_kv_reuse);
    assert(!capabilities.fp32_mlp_island);

    NativeQwenCompletion completion;
    assert(completion.finish_reason == NativeQwenFinishReason::Unknown);
    return 0;
}
