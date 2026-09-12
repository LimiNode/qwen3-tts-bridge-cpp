#include "NativeEngine.hpp"
#include "WavReader.hpp"

#include <cstdint>
#include <chrono>
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

std::string voice_reference_cache_key(
    const std::filesystem::path& path,
    const std::vector<float>& samples) {
    // The decoded sample fingerprint invalidates the entry if a WAV is
    // replaced in place while keeping the same path.  FNV-1a is sufficient
    // here because the key selects a cache entry, not a security boundary.
    std::uint64_t hash = 1469598103934665603ULL;
    for (const auto byte : path_utf8(path)) {
        hash ^= static_cast<unsigned char>(byte);
        hash *= 1099511628211ULL;
    }
    if (!samples.empty()) {
        const auto* begin = reinterpret_cast<const unsigned char*>(samples.data());
        const auto* end = begin + samples.size() * sizeof(float);
        for (const auto* byte = begin; byte != end; ++byte) {
            hash ^= *byte;
            hash *= 1099511628211ULL;
        }
    }
    return path_utf8(path) + ":" + std::to_string(samples.size()) + ":" + std::to_string(hash);
}

struct CallbackContext {
    const std::atomic<bool>* cancelled = nullptr;
    const AudioChunkHandler* on_chunk = nullptr;
    bool emitted_audio = false;
    std::chrono::steady_clock::time_point synthesis_started_at;
    double first_chunk_callback_ms = 0.0;
};

bool cancel_callback(void* user_data) {
    const auto* context = static_cast<const CallbackContext*>(user_data);
    return context == nullptr || context->cancelled->load(std::memory_order_relaxed);
}

bool audio_callback(const float* samples, int count, void* user_data) {
    auto* context = static_cast<CallbackContext*>(user_data);
    if (context == nullptr || context->cancelled->load(std::memory_order_relaxed)) {
        return false;
    }
    if (samples != nullptr && count > 0) {
        context->emitted_audio = true;
        if (context->first_chunk_callback_ms == 0.0) {
            context->first_chunk_callback_ms = std::chrono::duration<double, std::milli>(
                std::chrono::steady_clock::now() - context->synthesis_started_at).count();
        }
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

void NativeEngine::clear_voice_reference_cache() noexcept {
    if (context_ == nullptr || voice_reference_cache_.empty()) {
        voice_reference_cache_.clear();
        return;
    }
    const QwenApi& api = loader_.api();
    for (auto& entry : voice_reference_cache_) {
        api.voice_ref_free(&entry.second->value);
    }
    voice_reference_cache_.clear();
}

void NativeEngine::load() {
    if (context_ != nullptr) {
        throw std::logic_error("native engine is already loaded");
    }
    loader_.load(options_.dll_path, options_.manifest_path);
    const QwenApi& api = loader_.api();
    if (options_.precompute_voice_refs && !loader_.supports_voice_reference()) {
        loader_.unload();
        throw std::runtime_error(
            "--precompute-voice-ref requires qt_extract_voice_ref and qt_voice_ref_free exports");
    }
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
    clear_voice_reference_cache();
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
    if (options_.max_text_bytes > 0 &&
        request.text.size() > static_cast<std::size_t>(options_.max_text_bytes)) {
        return {SynthesisOutcome::Failed, "resource_error", "sequence_capacity_exceeded",
                "native text preflight exceeds configured max-text-bytes; route to the safe/Python backend", {}};
    }

    const QwenApi& api = loader_.api();
    qt_tts_params params{};
    api.tts_default_params(&params);
    if (params.abi_version != QT_ABI_VERSION) {
        return {SynthesisOutcome::Failed, "worker_error", "abi_mismatch", "qwen.dll returned incompatible TTS params"};
    }

    std::vector<float> reference_audio;
    std::string reference_cache_key;
    const qt_voice_ref* cached_reference = nullptr;
    bool voice_reference_cache_hit = false;
    double voice_reference_extract_ms = 0.0;
    double reference_audio_decode_ms = 0.0;
    try {
        if (!request.reference_audio_path.empty()) {
            const auto reference_decode_start = std::chrono::steady_clock::now();
            reference_audio = read_mono_24k_wav(std::filesystem::u8path(request.reference_audio_path));
            reference_audio_decode_ms = std::chrono::duration<double, std::milli>(
                std::chrono::steady_clock::now() - reference_decode_start).count();
            if (options_.precompute_voice_refs) {
                reference_cache_key = voice_reference_cache_key(
                    std::filesystem::u8path(request.reference_audio_path), reference_audio);
                const auto cached = voice_reference_cache_.find(reference_cache_key);
                if (cached != voice_reference_cache_.end()) {
                    cached_reference = &cached->second->value;
                    voice_reference_cache_hit = true;
                }
                else {
                    auto entry = std::make_unique<CachedVoiceReference>();
                    const auto extraction_start = std::chrono::steady_clock::now();
                    const qt_status extraction_status = api.extract_voice_ref(
                        context_,
                        reference_audio.data(),
                        static_cast<int>(reference_audio.size()),
                        &entry->value);
                    voice_reference_extract_ms = std::chrono::duration<double, std::milli>(
                        std::chrono::steady_clock::now() - extraction_start).count();
                    if (extraction_status != QT_STATUS_OK) {
                        api.voice_ref_free(&entry->value);
                        return {SynthesisOutcome::Failed, "model_error", "voice_reference_extract_failed",
                                last_error(api, "qwentts voice reference extraction failed"), {}, false,
                                voice_reference_extract_ms, reference_audio_decode_ms};
                    }
                    cached_reference = &entry->value;
                    auto [inserted, was_inserted] = voice_reference_cache_.emplace(
                        std::move(reference_cache_key), std::move(entry));
                    (void)was_inserted;
                    cached_reference = &inserted->second->value;
                }
            }
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
    params.ref_audio_24k = cached_reference == nullptr && !reference_audio.empty()
        ? reference_audio.data()
        : nullptr;
    params.ref_n_samples = cached_reference == nullptr
        ? static_cast<int>(reference_audio.size())
        : 0;
    params.ref_text = request.x_vector_only || request.reference_text.empty()
        ? nullptr
        : request.reference_text.c_str();
    if (cached_reference != nullptr) {
        params.ref_spk_emb = cached_reference->ref_spk_emb;
        params.ref_spk_dim = cached_reference->ref_spk_dim;
        // A raw reference without a transcript is x-vector mode. Supplying
        // RVQ codes in that mode changes the qwentts prompt semantics and is
        // not equivalent to the uncached path. Reuse codes only for ICL.
        const bool use_cached_codes = !request.x_vector_only && !request.reference_text.empty();
        params.ref_codes = use_cached_codes ? cached_reference->ref_codes : nullptr;
        params.ref_T = use_cached_codes ? cached_reference->ref_T : 0;
    }
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
    callbacks.synthesis_started_at = std::chrono::steady_clock::now();
    params.cancel = &cancel_callback;
    params.cancel_user_data = &callbacks;
    params.on_chunk = &audio_callback;
    params.on_chunk_user_data = &callbacks;

    qt_audio output{};
    const auto synthesis_start = callbacks.synthesis_started_at;
    const qt_status status = api.synthesize(context_, &params, &output);
    const double synthesis_ms = std::chrono::duration<double, std::milli>(
        std::chrono::steady_clock::now() - synthesis_start).count();
    api.audio_free(&output);
    qt_synthesis_metrics qwen_metrics{};
    if (api.last_synthesis_metrics != nullptr) {
        api.last_synthesis_metrics(&qwen_metrics, sizeof(qwen_metrics));
    }
    const auto apply_qwen_metrics = [&qwen_metrics](SynthesisResult result) {
        if (qwen_metrics.abi_version == QT_ABI_VERSION) {
            result.qwen_prompt_build_ms = qwen_metrics.prompt_build_ms;
            result.qwen_prefill_ms = qwen_metrics.prefill_ms;
            result.qwen_ttfa_ms = qwen_metrics.ttfa_ms;
            result.qwen_talker_ms = qwen_metrics.talker_ms;
            result.qwen_predictor_ms = qwen_metrics.predictor_ms;
            result.qwen_host_ms = qwen_metrics.host_ms;
            result.qwen_codec_ms = qwen_metrics.codec_ms;
            result.qwen_n_frames = qwen_metrics.n_frames;
        }
        return result;
    };
    if (status == QT_STATUS_OK) {
        const auto finish_reason = api.last_finish_reason();
        if (finish_reason == QT_FINISH_EOS) {
            if (!callbacks.emitted_audio) {
                return apply_qwen_metrics({SynthesisOutcome::Failed, "model_error", "empty_audio",
                        "qwentts reported natural EOS without emitting PCM", {}, voice_reference_cache_hit,
                        voice_reference_extract_ms, reference_audio_decode_ms, synthesis_ms,
                        callbacks.first_chunk_callback_ms});
            }
            return apply_qwen_metrics({SynthesisOutcome::Completed, {}, {}, {}, "natural_eos", voice_reference_cache_hit,
                    voice_reference_extract_ms, reference_audio_decode_ms, synthesis_ms,
                    callbacks.first_chunk_callback_ms});
        }
        if (finish_reason == QT_FINISH_MAX_TOKENS) {
            return apply_qwen_metrics({SynthesisOutcome::Completed, {}, {}, {}, "max_tokens", voice_reference_cache_hit,
                    voice_reference_extract_ms, reference_audio_decode_ms, synthesis_ms,
                    callbacks.first_chunk_callback_ms});
        }
        return apply_qwen_metrics({SynthesisOutcome::Failed, "model_error", "invalid_finish_reason",
                "qwentts reported successful synthesis without EOS or MAX_TOKENS", {},
                voice_reference_cache_hit, voice_reference_extract_ms,
                reference_audio_decode_ms, synthesis_ms, callbacks.first_chunk_callback_ms});
    }
    if (status == QT_STATUS_CANCELLED || cancelled.load(std::memory_order_relaxed)) {
        return apply_qwen_metrics({SynthesisOutcome::Cancelled, {}, {}, {}, {}, voice_reference_cache_hit,
                voice_reference_extract_ms, reference_audio_decode_ms, synthesis_ms,
                callbacks.first_chunk_callback_ms});
    }
    if (status == QT_STATUS_OOM) {
        return apply_qwen_metrics({SynthesisOutcome::Failed, "resource_error", "resource_exhausted",
                last_error(api, "qwentts ran out of memory"), {}, voice_reference_cache_hit,
                voice_reference_extract_ms, reference_audio_decode_ms, synthesis_ms,
                callbacks.first_chunk_callback_ms});
    }
    if (status == QT_STATUS_INVALID_PARAMS || status == QT_STATUS_MODE_INVALID) {
        return apply_qwen_metrics({SynthesisOutcome::Failed, "request_error", "invalid_native_request",
                last_error(api, "qwentts rejected the request"), {}, voice_reference_cache_hit,
                voice_reference_extract_ms, reference_audio_decode_ms, synthesis_ms,
                callbacks.first_chunk_callback_ms});
    }
    return apply_qwen_metrics({SynthesisOutcome::Failed, "model_error", "synthesis_failed",
            last_error(api, "qwentts synthesis failed"), {}, voice_reference_cache_hit,
            voice_reference_extract_ms, reference_audio_decode_ms, synthesis_ms,
            callbacks.first_chunk_callback_ms});
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
