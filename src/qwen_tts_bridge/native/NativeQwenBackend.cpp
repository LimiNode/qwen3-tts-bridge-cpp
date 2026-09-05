#include "qwen_tts_bridge/native/NativeQwenBackend.hpp"

#include <qwen.h>

#include <utility>

namespace qwen_tts_bridge::native {
namespace {

std::string qwen_error_or(const char* fallback) {
    const char* message = qt_last_error();
    return message == nullptr || *message == '\0' ? std::string(fallback)
                                                   : std::string(message);
}

struct CallbackState {
    const NativeQwenBackend::AudioChunkCallback* on_chunk = nullptr;
    const NativeQwenBackend::CancelCallback* cancel = nullptr;
};

bool emit_chunk(const float* samples, int count, void* user_data) noexcept {
    auto* state = static_cast<CallbackState*>(user_data);
    if (state == nullptr || state->on_chunk == nullptr || !*state->on_chunk) {
        return true;
    }
    try {
        return (*state->on_chunk)(samples, static_cast<std::size_t>(count));
    } catch (...) {
        return false;
    }
}

bool should_cancel(void* user_data) noexcept {
    auto* state = static_cast<CallbackState*>(user_data);
    if (state == nullptr || state->cancel == nullptr || !*state->cancel) {
        return false;
    }
    try {
        return (*state->cancel)();
    } catch (...) {
        return true;
    }
}

} // namespace

struct NativeQwenBackend::Impl {
    qt_context* context = nullptr;
    std::string error;
};

NativeQwenBackend::NativeQwenBackend(const NativeQwenBackendOptions& options)
    : impl_(new Impl()) {
    qt_init_params params{};
    qt_init_default_params(&params);
    params.talker_path = options.talker_path.c_str();
    params.codec_path = options.codec_path.c_str();
    params.use_fa = options.use_flash_attention;
    params.clamp_fp16 = options.clamp_fp16;
    impl_->context = qt_init(&params);
    if (impl_->context == nullptr) {
        impl_->error = qwen_error_or("qwentts.cpp initialization failed");
    }
}

NativeQwenBackend::~NativeQwenBackend() {
    if (impl_ != nullptr) {
        qt_free(impl_->context);
        delete impl_;
    }
}

bool NativeQwenBackend::is_ready() const noexcept {
    return impl_ != nullptr && impl_->context != nullptr;
}

const std::string& NativeQwenBackend::last_error() const noexcept {
    static const std::string empty;
    return impl_ == nullptr ? empty : impl_->error;
}

std::string NativeQwenBackend::version() const {
    const char* value = qt_version();
    return value == nullptr ? std::string() : std::string(value);
}

bool NativeQwenBackend::synthesize(
    const NativeQwenSynthesisRequest& request,
    AudioChunkCallback on_chunk,
    CancelCallback cancel,
    NativeQwenAudio* output) {
    if (!is_ready()) {
        return false;
    }
    if (request.text.empty()) {
        impl_->error = "native synthesis text must not be empty";
        return false;
    }

    qt_tts_params params{};
    qt_tts_default_params(&params);
    params.text = request.text.c_str();
    params.lang = request.language.c_str();
    params.instruct = request.instruction.empty() ? nullptr : request.instruction.c_str();
    params.speaker = request.speaker.empty() ? nullptr : request.speaker.c_str();
    params.ref_audio_24k = request.reference_audio_24k;
    params.ref_n_samples = request.reference_audio_samples;
    params.ref_text = request.reference_text.empty() ? nullptr : request.reference_text.c_str();
    params.seed = request.seed;
    params.max_new_tokens = request.max_new_tokens;

    CallbackState callbacks{&on_chunk, &cancel};
    if (on_chunk) {
        params.on_chunk = emit_chunk;
        params.on_chunk_user_data = &callbacks;
    }
    if (cancel) {
        params.cancel = should_cancel;
        params.cancel_user_data = &callbacks;
    }

    qt_audio audio{};
    const qt_status status = qt_synthesize(impl_->context, &params, &audio);
    if (status != QT_STATUS_OK) {
        impl_->error = qwen_error_or("qwentts.cpp synthesis failed");
        qt_audio_free(&audio);
        return false;
    }
    if (output != nullptr && !on_chunk) {
        if (audio.samples != nullptr && audio.n_samples > 0) {
            output->samples.assign(audio.samples, audio.samples + audio.n_samples);
        }
        output->sample_rate = audio.sample_rate;
        output->channels = audio.channels;
    }
    qt_audio_free(&audio);
    impl_->error.clear();
    return true;
}

} // namespace qwen_tts_bridge::native
