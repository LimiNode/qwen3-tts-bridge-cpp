#include "NativeEngine.hpp"
#include "WavReader.hpp"

#include <cstdint>
#include <iostream>
#include <limits>
#include <mutex>
#include <stdexcept>
#include <utility>

namespace qwen_tts_bridge::native_worker {
namespace {

std::mutex log_mutex;

void qwen_log_callback(qt_log_level level, const char* message, void*) {
    static constexpr const char* names[] = {"debug", "info", "warn", "error"};
    const int index = static_cast<int>(level);
    const char* name = index >= 0 && index < 4 ? names[index] : "unknown";
    std::lock_guard<std::mutex> lock(log_mutex);
    std::cerr << "[qwentts:" << name << "] " << (message != nullptr ? message : "") << '\n';
}

std::string path_utf8(const std::filesystem::path& path) {
    return path.u8string();
}

struct CallbackContext {
    const std::atomic<bool>* cancelled = nullptr;
    const AudioChunkHandler* on_chunk = nullptr;
};

bool cancel_callback(void* user_data) {
    const auto* context = static_cast<const CallbackContext*>(user_data);
    return context == nullptr || context->cancelled->load(std::memory_order_relaxed);
}

bool audio_callback(const float* samples, int count, void* user_data) {
    const auto* context = static_cast<const CallbackContext*>(user_data);
    if (context == nullptr || context->cancelled->load(std::memory_order_relaxed)) {
        return false;
    }
    return (*context->on_chunk)(samples, count);
}

std::string last_error(const QwenApi& api, const char* fallback) {
    const char* message = api.last_error();
    return message != nullptr && *message != '\0' ? message : fallback;
}

} // namespace

NativeEngine::NativeEngine(NativeEngineOptions options)
    : options_(std::move(options)) {}

NativeEngine::~NativeEngine() {
    close();
}

void NativeEngine::load() {
    if (context_ != nullptr) {
        throw std::logic_error("native engine is already loaded");
    }
    loader_.load(options_.dll_path, options_.manifest_path);
    const QwenApi& api = loader_.api();
    api.log_set(&qwen_log_callback, nullptr);

    qt_init_params params{};
    api.init_default_params(&params);
    if (params.abi_version != QT_ABI_VERSION) {
        throw std::runtime_error("qwen.dll default init params report an incompatible ABI");
    }
    const std::string talker_path = path_utf8(options_.talker_model);
    const std::string codec_path = path_utf8(options_.codec_model);
    params.talker_path = talker_path.c_str();
    params.codec_path = codec_path.c_str();
    params.use_fa = options_.use_flash_attention;
    params.clamp_fp16 = options_.clamp_fp16;
    params.max_batch = options_.max_batch;
    params.codec_chunk_sec = options_.codec_chunk_seconds;
    params.stream_max_chunk_frames = options_.stream_max_chunk_frames;
    context_ = api.init(&params);
    if (context_ == nullptr) {
        throw std::runtime_error(last_error(api, "qt_init failed"));
    }
}

void NativeEngine::close() noexcept {
    if (context_ != nullptr) {
        loader_.api().free(context_);
        context_ = nullptr;
    }
    loader_.unload();
}

void NativeEngine::validate_request(const SynthesizeMessage& request) const {
    if (context_ == nullptr) {
        throw std::runtime_error("native engine is not loaded");
    }
    if (request.text.empty()) {
        throw std::invalid_argument("text must not be empty");
    }
    if (request.output.sample_format != "s16le" ||
        request.output.sample_rate != 24000 ||
        request.output.channels != 1) {
        throw std::invalid_argument("native qwentts worker supports only mono 24000 Hz s16le output");
    }
    if (!request.voice_id.empty()) {
        throw std::invalid_argument("registered voice_id profiles are not configured for the native worker");
    }
    if (request.x_vector_only && request.reference_audio_path.empty()) {
        throw std::invalid_argument("x_vector_only requires reference_audio_path");
    }
    if (!request.reference_text.empty() && request.reference_audio_path.empty()) {
        throw std::invalid_argument("reference_text requires reference_audio_path");
    }
    if (!request.reference_audio_path.empty() && !request.speaker.empty()) {
        throw std::invalid_argument("reference_audio_path and speaker are mutually exclusive");
    }
    if (request.has_seed && request.seed > static_cast<std::uint64_t>(std::numeric_limits<std::int64_t>::max())) {
        throw std::invalid_argument("seed exceeds the qwentts signed 64-bit range");
    }
}

SynthesisResult NativeEngine::synthesize(
    const SynthesizeMessage& request,
    const std::atomic<bool>& cancelled,
    const AudioChunkHandler& on_chunk) {
    try {
        validate_request(request);
    }
    catch (const std::invalid_argument& error) {
        return {SynthesisOutcome::Failed, "request_error", "invalid_native_request", error.what()};
    }
    catch (const std::exception& error) {
        return {SynthesisOutcome::Failed, "worker_error", "worker_not_ready", error.what()};
    }

    const QwenApi& api = loader_.api();
    qt_tts_params params{};
    api.tts_default_params(&params);
    if (params.abi_version != QT_ABI_VERSION) {
        return {SynthesisOutcome::Failed, "worker_error", "abi_mismatch", "qwen.dll returned incompatible TTS params"};
    }

    std::vector<float> reference_audio;
    try {
        if (!request.reference_audio_path.empty()) {
            reference_audio = read_mono_24k_wav(std::filesystem::u8path(request.reference_audio_path));
        }
    }
    catch (const std::exception& error) {
        return {SynthesisOutcome::Failed, "request_error", "invalid_reference_audio", error.what()};
    }

    params.text = request.text.c_str();
    params.lang = request.language.empty() || request.language == "auto"
        ? nullptr
        : request.language.c_str();
    params.instruct = request.instruction.empty() ? nullptr : request.instruction.c_str();
    params.speaker = request.speaker.empty() ? nullptr : request.speaker.c_str();
    params.ref_audio_24k = reference_audio.empty() ? nullptr : reference_audio.data();
    params.ref_n_samples = static_cast<int>(reference_audio.size());
    params.ref_text = request.x_vector_only || request.reference_text.empty()
        ? nullptr
        : request.reference_text.c_str();
    params.max_new_tokens = options_.max_new_tokens;
    if (request.has_seed) {
        params.seed = static_cast<std::int64_t>(request.seed);
    }
    if (request.sampling.temperature) {
        params.temperature = static_cast<float>(*request.sampling.temperature);
        params.subtalker_temperature = params.temperature;
    }
    if (request.sampling.top_k) {
        params.top_k = static_cast<int>(*request.sampling.top_k);
        params.subtalker_top_k = params.top_k;
    }
    if (request.sampling.top_p) {
        params.top_p = static_cast<float>(*request.sampling.top_p);
        params.subtalker_top_p = params.top_p;
    }
    if (request.sampling.repetition_penalty) {
        params.repetition_penalty = static_cast<float>(*request.sampling.repetition_penalty);
    }
    if (request.sampling.do_sample) {
        params.do_sample = *request.sampling.do_sample;
        params.subtalker_do_sample = params.do_sample;
    }

    CallbackContext callbacks{&cancelled, &on_chunk};
    params.cancel = &cancel_callback;
    params.cancel_user_data = &callbacks;
    params.on_chunk = &audio_callback;
    params.on_chunk_user_data = &callbacks;

    qt_audio output{};
    const qt_status status = api.synthesize(context_, &params, &output);
    api.audio_free(&output);
    if (status == QT_STATUS_OK) {
        return {SynthesisOutcome::Completed, {}, {}, {}};
    }
    if (status == QT_STATUS_CANCELLED || cancelled.load(std::memory_order_relaxed)) {
        return {SynthesisOutcome::Cancelled, {}, {}, {}};
    }
    if (status == QT_STATUS_OOM) {
        return {SynthesisOutcome::Failed, "resource_error", "resource_exhausted", last_error(api, "qwentts ran out of memory")};
    }
    if (status == QT_STATUS_INVALID_PARAMS || status == QT_STATUS_MODE_INVALID) {
        return {SynthesisOutcome::Failed, "request_error", "invalid_native_request", last_error(api, "qwentts rejected the request")};
    }
    return {SynthesisOutcome::Failed, "model_error", "synthesis_failed", last_error(api, "qwentts synthesis failed")};
}

WorkerCapabilities NativeEngine::capabilities() const {
    WorkerCapabilities value;
    value.streaming = true;
    value.cancellation = true;
    value.instructions = true;
    value.voice_clone = true;
    value.sampling_overrides = true;
    value.deterministic_seed = true;
    value.voice_clone_streaming = true;
    value.voice_profiles = false;
    return value;
}

std::vector<std::string> NativeEngine::speaker_names() const {
    std::vector<std::string> names;
    if (context_ == nullptr) {
        return names;
    }
    const QwenApi& api = loader_.api();
    const int count = api.n_speakers(context_);
    for (int index = 0; index < count; ++index) {
        const char* name = api.speaker_name(context_, index);
        if (name != nullptr && *name != '\0') {
            names.emplace_back(name);
        }
    }
    return names;
}

const RuntimeManifest& NativeEngine::manifest() const {
    return loader_.manifest();
}

const std::string& NativeEngine::engine_version() const {
    return loader_.engine_version();
}

} // namespace qwen_tts_bridge::native_worker
