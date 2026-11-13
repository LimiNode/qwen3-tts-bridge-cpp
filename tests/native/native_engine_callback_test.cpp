#include "native_engine.hpp"

#include <atomic>
#include <cstdlib>
#include <filesystem>
#include <iostream>
#include <new>
#include <stdexcept>

#define CHECK(expression) \
    do { \
        if (!(expression)) { \
            std::cerr << "CHECK failed: " #expression " at " << __FILE__ << ':' << __LINE__ << '\n'; \
            return EXIT_FAILURE; \
        } \
    } while (false)

namespace {

using qwen_tts_bridge::native_worker::NativeEngine;
using qwen_tts_bridge::native_worker::NativeEngineOptions;
using qwen_tts_bridge::native_worker::SynthesisOutcome;
using qwen_tts_bridge::SynthesizeMessage;

NativeEngineOptions make_options() {
    const std::filesystem::path runtime = QWEN_TTS_FAKE_RUNTIME_DIR;
    NativeEngineOptions options;
    options.dll_path = runtime / "qwen.dll";
    options.manifest_path = runtime / "manifest.json";
    options.talker_model = runtime / "talker.gguf";
    options.codec_model = runtime / "codec.gguf";
    return options;
}

int run_callback_failure_test(bool bad_alloc) {
    NativeEngine engine(make_options());
    engine.load();

    SynthesizeMessage request;
    request.text = "callback failure";
    std::atomic<bool> cancelled{false};
    bool callback_called = false;
    const auto result = engine.synthesize(
        request,
        cancelled,
        [&](const float*, int) -> bool {
            callback_called = true;
            if (bad_alloc) {
                throw std::bad_alloc{};
            }
            throw std::runtime_error("injected audio callback failure");
            return true;
        });

    CHECK(callback_called);
    CHECK(result.outcome == SynthesisOutcome::Failed);
    CHECK(result.category == "internal_error");
    CHECK(result.code == (bad_alloc ? "audio_callback_bad_alloc" : "audio_callback_exception"));
    CHECK(result.execution_outcome.empty());
    engine.close();
    return EXIT_SUCCESS;
}

} // namespace

int main() {
    CHECK(run_callback_failure_test(false) == EXIT_SUCCESS);
    CHECK(run_callback_failure_test(true) == EXIT_SUCCESS);
    return EXIT_SUCCESS;
}
