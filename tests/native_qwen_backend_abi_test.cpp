#include <qwen_tts_bridge/native.hpp>

#include <cassert>

int main() {
    using qwen_tts_bridge::native::NativeQwenBackend;
    using qwen_tts_bridge::native::NativeQwenBackendOptions;

    NativeQwenBackendOptions options;
    options.talker_path = "missing-talker.gguf";
    options.codec_path = "missing-codec.gguf";
    NativeQwenBackend backend(options);

    // This is an ABI/linkage smoke test, not a model test. Missing GGUF files
    // must fail locally and leave a diagnostic without crashing the process.
    assert(!backend.is_ready());
    assert(!backend.last_error().empty());
    assert(!backend.version().empty());
    return 0;
}
