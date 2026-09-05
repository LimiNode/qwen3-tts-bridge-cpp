#include <qwen.h>

#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <string>
#include <chrono>
#include <thread>

struct qt_context {
    qt_log_cb log = nullptr;
    void* log_user_data = nullptr;
};

namespace {
thread_local std::string last_error;

void set_error(const char* value) {
    last_error = value != nullptr ? value : "";
}
}

extern "C" {

QT_API const char* qt_version(void) {
    return "fake-qwentts-test (native-worker)";
}

QT_API const char* qt_last_error(void) {
    return last_error.c_str();
}

QT_API void qt_init_default_params(qt_init_params* params) {
    if (params == nullptr) {
        return;
    }
    std::memset(params, 0, sizeof(*params));
    params->abi_version = QT_ABI_VERSION;
    params->use_fa = true;
    params->max_batch = 1;
    params->codec_chunk_sec = 24.0F;
}

QT_API qt_context* qt_init(const qt_init_params* params) {
    if (params == nullptr || params->abi_version != QT_ABI_VERSION) {
        set_error("fake init ABI mismatch");
        return nullptr;
    }
    return new qt_context{};
}

QT_API void qt_free(qt_context* context) {
    delete context;
}

QT_API void qt_tts_default_params(qt_tts_params* params) {
    if (params == nullptr) {
        return;
    }
    std::memset(params, 0, sizeof(*params));
    params->abi_version = QT_ABI_VERSION;
    params->seed = -1;
    params->max_new_tokens = 2048;
    params->do_sample = true;
    params->temperature = 0.9F;
    params->top_k = 50;
    params->top_p = 1.0F;
    params->repetition_penalty = 1.05F;
    params->subtalker_do_sample = true;
    params->subtalker_temperature = 0.9F;
    params->subtalker_top_k = 50;
    params->subtalker_top_p = 1.0F;
}

QT_API qt_status qt_synthesize(
    qt_context* context,
    const qt_tts_params* params,
    qt_audio* out) {
    if (context == nullptr || params == nullptr || params->abi_version != QT_ABI_VERSION ||
        params->text == nullptr || *params->text == '\0') {
        set_error("fake synthesis invalid params");
        return QT_STATUS_INVALID_PARAMS;
    }
    if (params->cancel != nullptr && params->cancel(params->cancel_user_data)) {
        return QT_STATUS_CANCELLED;
    }
    const float chunks[][4] = {
        {-1.2F, -0.5F, 0.0F, 0.5F},
        {0.75F, 1.0F, 0.25F, 0.0F}
    };
    if (params->on_chunk != nullptr) {
        for (const auto& chunk : chunks) {
            if (params->cancel != nullptr && params->cancel(params->cancel_user_data)) {
                return QT_STATUS_CANCELLED;
            }
            if (!params->on_chunk(chunk, 4, params->on_chunk_user_data)) {
                return QT_STATUS_CANCELLED;
            }
            std::this_thread::sleep_for(std::chrono::milliseconds(100));
        }
        return QT_STATUS_OK;
    }
    if (out == nullptr) {
        set_error("fake output is null");
        return QT_STATUS_INVALID_PARAMS;
    }
    out->samples = static_cast<float*>(std::malloc(sizeof(float) * 8));
    if (out->samples == nullptr) {
        set_error("fake allocation failed");
        return QT_STATUS_OOM;
    }
    std::memcpy(out->samples, chunks, sizeof(float) * 8);
    out->n_samples = 8;
    out->sample_rate = 24000;
    out->channels = 1;
    return QT_STATUS_OK;
}

QT_API void qt_audio_free(qt_audio* audio) {
    if (audio == nullptr) {
        return;
    }
    std::free(audio->samples);
    std::memset(audio, 0, sizeof(*audio));
}

QT_API void qt_voice_ref_free(qt_voice_ref*) {}
QT_API qt_status qt_extract_voice_ref(qt_context*, const float*, int, qt_voice_ref*) {
    set_error("fake voice extraction is not implemented");
    return QT_STATUS_MODE_INVALID;
}
QT_API int qt_num_codebooks(const qt_context*) { return 1; }
QT_API int qt_n_speakers(const qt_context*) { return 1; }
QT_API const char* qt_speaker_name(const qt_context*, int index) {
    return index == 0 ? "fake" : nullptr;
}
QT_API int qt_duration_sec_to_tokens(const qt_context*, float seconds) {
    return std::max(1, static_cast<int>(std::ceil(seconds * 12.5F)));
}
QT_API void qt_log_set(qt_log_cb callback, void* user_data) {
    (void)callback;
    (void)user_data;
}

}
