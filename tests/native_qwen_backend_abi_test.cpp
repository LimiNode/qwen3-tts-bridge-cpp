#include <qwen_tts_bridge/native.hpp>

#include <iostream>

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

#define CHECK(expression) \
    do { \
        if (!(expression)) { \
            std::cerr << "CHECK failed: " #expression << " (line " << __LINE__ << ")\n"; \
            return __LINE__; \
        } \
    } while (false)

    // This is an ABI/linkage smoke test, not a model test. Missing GGUF files
    // must fail locally and leave a diagnostic without crashing the process.
    CHECK(!backend.is_ready());
    CHECK(!backend.last_error().empty());
    CHECK(!backend.version().empty());

    const auto capabilities = NativeQwenBackend::capabilities();
    CHECK(capabilities.stream_max_chunk_frames);
    CHECK(!capabilities.codec_window);
    CHECK(!capabilities.sequence_capacity);
    CHECK(!capabilities.playback_prebuffer);
    CHECK(!capabilities.prefix_kv_reuse);
    CHECK(!capabilities.fp32_mlp_island);

    NativeQwenCompletion completion;
    CHECK(completion.finish_reason == NativeQwenFinishReason::Unknown);
#undef CHECK
    return 0;
}
