#include "qwen_tts_bridge/native/NativeQwenBackend.hpp"

#include <qwen.h>

#include <cstdlib>
#include <cstring>
#include <iostream>
#include <string>

struct qt_context {};

namespace {
thread_local qt_finish_reason g_finish_reason = QT_FINISH_UNKNOWN;
int g_stream_max_chunk_frames = 0;
}

extern "C" {

const char* qt_version() {
    return "fake-native-adapter";
}

const char* qt_last_error() {
    return "";
}

qt_finish_reason qt_last_finish_reason() {
    return g_finish_reason;
}

void qt_audio_free(qt_audio* audio) {
    if (audio != nullptr) {
        std::free(audio->samples);
        *audio = {};
    }
}

void qt_init_default_params(qt_init_params* params) {
    std::memset(params, 0, sizeof(*params));
    params->abi_version = QT_ABI_VERSION;
}

qt_context* qt_init(const qt_init_params* params) {
    g_stream_max_chunk_frames = params != nullptr ? params->stream_max_chunk_frames : 0;
    return params != nullptr && params->abi_version == QT_ABI_VERSION
        ? new qt_context{}
        : nullptr;
}

void qt_free(qt_context* context) {
    delete context;
}

void qt_tts_default_params(qt_tts_params* params) {
    std::memset(params, 0, sizeof(*params));
    params->abi_version = QT_ABI_VERSION;
}

qt_status qt_synthesize(qt_context*, const qt_tts_params* params, qt_audio* audio) {
    const std::string text = params != nullptr && params->text != nullptr ? params->text : "";
    if (text == "unknown") {
        g_finish_reason = QT_FINISH_UNKNOWN;
    } else if (text == "max") {
        g_finish_reason = QT_FINISH_MAX_TOKENS;
    } else {
        g_finish_reason = QT_FINISH_EOS;
    }
    audio->samples = static_cast<float*>(std::malloc(sizeof(float)));
    audio->samples[0] = 0.0F;
    audio->n_samples = 1;
    audio->sample_rate = 24000;
    audio->channels = 1;
    return QT_STATUS_OK;
}

} // extern "C"

int main() {
    using namespace qwen_tts_bridge::native;

    NativeQwenBackendOptions options;
    options.talker_path = "fake-talker.gguf";
    options.codec_path = "fake-codec.gguf";
    options.stream_max_chunk_frames = 4;
    NativeQwenBackend backend(options);
#define CHECK(expression) \
    do { \
        if (!(expression)) { \
            std::cerr << "CHECK failed: " #expression << " (line " << __LINE__ << ")\n"; \
            return __LINE__; \
        } \
    } while (false)

    CHECK(backend.is_ready());
    CHECK(g_stream_max_chunk_frames == 4);

    NativeQwenCompletion completion;
    NativeQwenSynthesisRequest request;
    request.text = "eos";
    CHECK(backend.synthesize(request, {}, {}, nullptr, &completion));
    CHECK(completion.finish_reason == NativeQwenFinishReason::NaturalEos);

    request.text = "max";
    completion.finish_reason = NativeQwenFinishReason::NaturalEos;
    CHECK(backend.synthesize(request, {}, {}, nullptr, &completion));
    CHECK(completion.finish_reason == NativeQwenFinishReason::MaxTokens);

    request.text = "unknown";
    completion.finish_reason = NativeQwenFinishReason::NaturalEos;
    CHECK(!backend.synthesize(request, {}, {}, nullptr, &completion));
    CHECK(completion.finish_reason == NativeQwenFinishReason::Unknown);
    CHECK(backend.last_error().find("unknown finish reason") != std::string::npos);
#undef CHECK
    return 0;
}
