#include "NativeEngine.hpp"
#include "runtime_manifest.hpp"
#include "wav_reader.hpp"

#include <nlohmann/json.hpp>

#include <cstdint>
#include <algorithm>
#include <chrono>
#include <cctype>
#include <fstream>
#include <iostream>
#include <limits>
#include <mutex>
#include <stdexcept>
#include <utility>

namespace qwen_tts_bridge::native_worker {
namespace {

using Json = nlohmann::json;

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

void log_prepared_reference_metric(
    const std::string& voice_id,
    const char* source,
    std::chrono::steady_clock::time_point started) {
    const double duration_ms = std::chrono::duration<double, std::milli>(
        std::chrono::steady_clock::now() - started).count();
    std::cerr << "qtb_metric " << Json{
        {"event", "native_voice_reference_ready"},
        {"voice_id", voice_id},
        {"source", source},
        {"duration_ms", duration_ms},
    }.dump() << '\n';
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

std::string required_string(const Json& object, const char* name, const std::string& voice_id) {
    const auto it = object.find(name);
    if (it == object.end() || !it->is_string() || it->get<std::string>().empty()) {
        throw std::runtime_error("voice profile '" + voice_id + "' requires a non-empty " + name);
    }
    return it->get<std::string>();
}

std::string trim_reference_text(std::string value) {
    const auto is_space = [](char character) {
        return std::isspace(static_cast<unsigned char>(character)) != 0;
    };
    const auto first = std::find_if_not(value.begin(), value.end(), is_space);
    const auto last = std::find_if_not(value.rbegin(), value.rend(), is_space).base();
    if (first >= last) {
        return {};
    }
    return std::string(first, last);
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

void NativeEngine::load_voice_registry() {
    voice_profiles_.clear();
    if (options_.voice_registry_path.empty()) {
        return;
    }

    std::ifstream input(options_.voice_registry_path, std::ios::binary);
    if (!input) {
        throw std::runtime_error("unable to open native voice registry: " +
                                 options_.voice_registry_path.u8string());
    }
    const Json document = Json::parse(input, nullptr, true, true);
    if (!document.is_object() || document.value("schema_version", 0) != 1) {
        throw std::runtime_error("native voice registry schema_version must be 1");
    }
    const auto voices = document.find("voices");
    if (voices == document.end() || !voices->is_array()) {
        throw std::runtime_error("native voice registry voices must be an array");
    }
    const auto registry_dir = options_.voice_registry_path.parent_path();
    for (const auto& item : *voices) {
        if (!item.is_object()) {
            throw std::runtime_error("native voice registry entries must be objects");
        }
        const std::string voice_id = required_string(item, "voice_id", "<unknown>");
        if (voice_profiles_.find(voice_id) != voice_profiles_.end()) {
            throw std::runtime_error("duplicate native voice profile: " + voice_id);
        }
        const auto reference = required_string(item, "reference_audio_path", voice_id);
        auto reference_path = std::filesystem::u8path(reference);
        if (reference_path.is_relative()) {
            reference_path = registry_dir / reference_path;
        }
        reference_path = std::filesystem::weakly_canonical(reference_path);
        if (!std::filesystem::is_regular_file(reference_path)) {
            throw std::runtime_error("native voice profile reference audio is missing: " +
                                     reference_path.u8string());
        }
        VoiceProfile profile;
        profile.reference_audio_path = std::move(reference_path);
        if (const auto text = item.find("reference_text"); text != item.end()) {
            if (!text->is_string()) {
                throw std::runtime_error("native voice profile reference_text must be a string: " + voice_id);
            }
            profile.reference_text = text->get<std::string>();
        }
        if (const auto preserve = item.find("preserve_reference_text_whitespace"); preserve != item.end()) {
            if (!preserve->is_boolean()) {
                throw std::runtime_error(
                    "native voice profile preserve_reference_text_whitespace must be a boolean: " + voice_id);
            }
            profile.preserve_reference_text_whitespace = preserve->get<bool>();
        }
        profile.x_vector_only = item.value("x_vector_only", false);
        if (!profile.x_vector_only) {
            if (!profile.preserve_reference_text_whitespace) {
                profile.reference_text = trim_reference_text(std::move(profile.reference_text));
            }
            if (profile.reference_text.empty()) {
                throw std::runtime_error(
                    "native voice profile '" + voice_id +
                    "' requires a non-empty reference_text unless x_vector_only is true");
            }
        }
        if (const auto prepared = item.find("native_reference"); prepared != item.end()) {
            if (!prepared->is_object()) {
                throw std::runtime_error("native voice profile native_reference must be an object: " + voice_id);
            }
            const auto manifest_path = prepared->find("manifest_path");
            if (manifest_path == prepared->end() || !manifest_path->is_string() ||
                manifest_path->get_ref<const std::string&>().empty()) {
                throw std::runtime_error(
                    "native voice profile native_reference requires manifest_path: " + voice_id);
            }
            profile.prepared_manifest_path = resolve_prepared_manifest_path(
                registry_dir, manifest_path->get<std::string>());
            if (const auto prepare = prepared->find("prepare_if_missing");
                prepare != prepared->end() && !prepare->is_boolean()) {
                throw std::runtime_error(
                    "native voice profile prepare_if_missing must be a boolean: " + voice_id);
            }
            profile.prepare_if_missing = prepared->value("prepare_if_missing", false);
        }
        voice_profiles_.emplace(voice_id, std::move(profile));
    }
}

PreparedVoiceReferenceContext NativeEngine::prepared_context(const VoiceProfile& profile) const {
    PreparedVoiceReferenceContext result;
    result.manifest_path = profile.prepared_manifest_path;
    result.source_audio_path = profile.reference_audio_path;
    result.reference_text = profile.reference_text;
    result.x_vector_only = profile.x_vector_only;
    result.source_audio_sha256 = sha256_file(profile.reference_audio_path);
    result.talker_sha256 = talker_sha256_;
    result.codec_sha256 = codec_sha256_;
    result.engine_commit = loader_.manifest().engine_commit;
    result.abi_version = loader_.manifest().qt_abi_version;
    result.num_codebooks = loader_.api().num_codebooks(context_);
    return result;
}

std::unique_ptr<NativeEngine::CachedVoiceReference> NativeEngine::make_persisted_reference(
    PreparedVoiceReferenceData data) {
    auto entry = std::make_unique<CachedVoiceReference>();
    entry->persisted_speaker = std::move(data.speaker_embedding);
    entry->persisted_codes = std::move(data.codes);
    entry->value.ref_spk_emb = entry->persisted_speaker.data();
    entry->value.ref_spk_dim = static_cast<int>(entry->persisted_speaker.size());
    entry->value.ref_codes = entry->persisted_codes.empty() ? nullptr : entry->persisted_codes.data();
    entry->value.ref_T = data.frames;
    entry->value.num_codebooks = data.num_codebooks;
    return entry;
}

void NativeEngine::preload_voice_registry() {
    if (voice_profiles_.empty()) {
        return;
    }
    const QwenApi& api = loader_.api();
    const bool requires_extraction = std::any_of(
        voice_profiles_.begin(), voice_profiles_.end(),
        [](const auto& item) {
            const auto& profile = item.second;
            return profile.prepared_manifest_path.empty() ||
                !std::filesystem::is_regular_file(profile.prepared_manifest_path);
        });
    if (requires_extraction && !loader_.supports_voice_reference()) {
        throw std::runtime_error(
            "native voice registry requires qt_extract_voice_ref and qt_voice_ref_free exports "
            "unless every profile has a validated prepared reference");
    }
    const bool has_prepared_profiles = std::any_of(
        voice_profiles_.begin(), voice_profiles_.end(),
        [](const auto& item) { return !item.second.prepared_manifest_path.empty(); });
    if (has_prepared_profiles) {
        talker_sha256_ = sha256_file(options_.talker_model);
        codec_sha256_ = sha256_file(options_.codec_model);
    }
    for (auto& [voice_id, profile] : voice_profiles_) {
        const auto profile_started = std::chrono::steady_clock::now();
        PreparedVoiceReferenceContext prepared_profile_context;
        if (!profile.prepared_manifest_path.empty()) {
            prepared_profile_context = prepared_context(profile);
            reconcile_prepared_publication(prepared_profile_context);
        }
        if (!profile.prepared_manifest_path.empty() &&
            std::filesystem::is_regular_file(profile.prepared_manifest_path)) {
            auto prepared = load_prepared_voice_reference(prepared_profile_context);
            finalize_prepared_publication(prepared_profile_context);
            profile.reference_cache_key = prepared.cache_key;
            if (voice_reference_cache_.find(profile.reference_cache_key) == voice_reference_cache_.end()) {
                voice_reference_cache_.emplace(
                    profile.reference_cache_key, make_persisted_reference(std::move(prepared)));
            }
            log_prepared_reference_metric(voice_id, "persisted", profile_started);
            continue;
        }
        if (!profile.prepared_manifest_path.empty() && !profile.prepare_if_missing) {
            throw std::runtime_error(
                "prepared native voice manifest is missing for profile '" + voice_id + "'");
        }
        profile.reference_audio = read_mono_24k_wav(profile.reference_audio_path);
        if (!profile.x_vector_only) {
            append_reference_trailing_silence(profile.reference_audio);
        }
        profile.reference_cache_key = voice_reference_cache_key(
            profile.reference_audio_path, profile.reference_audio);
        const auto cached = voice_reference_cache_.find(profile.reference_cache_key);
        if (cached != voice_reference_cache_.end()) {
            profile.reference_audio.clear();
            continue;
        }
        auto entry = std::make_unique<CachedVoiceReference>();
        const auto status = api.extract_voice_ref(
            context_,
            profile.reference_audio.data(),
            static_cast<int>(profile.reference_audio.size()),
            &entry->value);
        if (status != QT_STATUS_OK) {
            api.voice_ref_free(&entry->value);
            throw std::runtime_error(
                "failed to preload native voice profile '" + voice_id + "': " +
                last_error(api, "qwentts voice reference extraction failed"));
        }
        entry->owner_api = &api;
        if (!profile.prepared_manifest_path.empty()) {
            const auto context = prepared_context(profile);
            const auto prepared = persist_prepared_voice_reference(context, entry->value);
            api.voice_ref_free(&entry->value);
            entry->owner_api = nullptr;
            entry = make_persisted_reference(prepared);
            profile.reference_cache_key = prepared.cache_key;
            log_prepared_reference_metric(voice_id, "extracted_and_persisted", profile_started);
            // The persisted vectors are worker-owned and are never passed back
            // to the DLL deallocator. The extracted DLL-owned buffers were
            // freed before replacing the temporary cache entry.
        }
        voice_reference_cache_.emplace(profile.reference_cache_key, std::move(entry));
        profile.reference_audio.clear();
    }
}

void NativeEngine::clear_voice_reference_cache() noexcept {
    if (context_ == nullptr || voice_reference_cache_.empty()) {
        voice_reference_cache_.clear();
        return;
    }
    voice_reference_cache_.clear();
    talker_sha256_.clear();
    codec_sha256_.clear();
}

void NativeEngine::load() {
    if (context_ != nullptr) {
        throw std::logic_error("native engine is already loaded");
    }
    if (!options_.diagnostic_dump_dir.empty()) {
        std::filesystem::create_directories(options_.diagnostic_dump_dir);
        if (!std::filesystem::is_directory(options_.diagnostic_dump_dir)) {
            throw std::runtime_error("native diagnostic dump path is not a directory: " +
                                     options_.diagnostic_dump_dir.u8string());
        }
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
    load_voice_registry();
    preload_voice_registry();
}

void NativeEngine::warmup() {
    if (!options_.warmup_synthesis) {
        warmed_up_ = false;
        return;
    }
    SynthesizeMessage request;
    request.text = options_.warmup_text;
    request.language = options_.warmup_language;
    request.voice_id = options_.warmup_voice_id;
    request.output.sample_format = "s16le";
    request.output.sample_rate = 24000;
    request.output.channels = 1;
    const std::atomic<bool> cancelled{false};
    const auto result = synthesize(request, cancelled, [](const float*, int) {
        return true;
    });
    if (result.outcome != SynthesisOutcome::Completed) {
        throw std::runtime_error(
            "native synthesis warmup failed: " +
            (result.message.empty() ? result.code : result.message));
    }
    warmed_up_ = true;
}

void NativeEngine::close() noexcept {
    warmed_up_ = false;
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
        if (voice_profiles_.find(request.voice_id) == voice_profiles_.end()) {
            throw std::invalid_argument("unknown native voice_id profile: " + request.voice_id);
        }
        if (!request.reference_audio_path.empty() || !request.reference_text.empty() ||
            request.x_vector_only || !request.speaker.empty()) {
            throw std::invalid_argument("voice_id cannot be combined with direct reference or speaker fields");
        }
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
    if (api.tts_default_params_ex(&params, sizeof(params)) != QT_STATUS_OK ||
        params.abi_version != QT_ABI_VERSION) {
        return {SynthesisOutcome::Failed, "worker_error", "abi_mismatch", "qwen.dll returned incompatible TTS params"};
    }
    params.eos_guard_enabled = options_.eos_guard_enabled;
    params.eos_guard_start_ratio = options_.eos_guard_start_ratio;
    params.eos_guard_max_ratio = options_.eos_guard_max_ratio;
    params.eos_guard_force_ratio = options_.eos_guard_force_ratio;
    params.eos_guard_max_boost = options_.eos_guard_max_boost;
    params.eos_guard_voice_multiplier = options_.eos_guard_voice_multiplier;
    params.eos_guard_min_expected_frames = options_.eos_guard_min_expected_frames;
    params.eos_guard_frames_per_text_token = options_.eos_guard_frames_per_text_token;

    const VoiceProfile* voice_profile = nullptr;
    if (!request.voice_id.empty()) {
        voice_profile = &voice_profiles_.at(request.voice_id);
    }
    const std::filesystem::path effective_reference_path = voice_profile != nullptr
        ? voice_profile->reference_audio_path
        : std::filesystem::u8path(request.reference_audio_path);
    const std::string& effective_reference_text = voice_profile != nullptr
        ? voice_profile->reference_text
        : request.reference_text;
    const bool effective_x_vector_only = voice_profile != nullptr
        ? voice_profile->x_vector_only
        : request.x_vector_only;

    std::vector<float> reference_audio;
    std::string reference_cache_key;
    const qt_voice_ref* cached_reference = nullptr;
    bool voice_reference_cache_hit = false;
    double voice_reference_extract_ms = 0.0;
    double reference_audio_decode_ms = 0.0;
    try {
        if (voice_profile != nullptr) {
            reference_cache_key = voice_profile->reference_cache_key;
            const auto cached = voice_reference_cache_.find(reference_cache_key);
            if (cached == voice_reference_cache_.end()) {
                return {SynthesisOutcome::Failed, "worker_error", "voice_profile_not_ready",
                        "native voice profile was not preloaded"};
            }
            cached_reference = &cached->second->value;
            voice_reference_cache_hit = true;
        }
        else if (!request.reference_audio_path.empty()) {
            const auto reference_decode_start = std::chrono::steady_clock::now();
            reference_audio = read_mono_24k_wav(std::filesystem::u8path(request.reference_audio_path));
            const bool is_icl = !effective_x_vector_only && !effective_reference_text.empty();
            if (is_icl) {
                append_reference_trailing_silence(reference_audio);
            }
            reference_audio_decode_ms = std::chrono::duration<double, std::milli>(
                std::chrono::steady_clock::now() - reference_decode_start).count();
            if (options_.precompute_voice_refs) {
                reference_cache_key = voice_reference_cache_key(
                    effective_reference_path, reference_audio);
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
                    entry->owner_api = &api;
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
    params.ref_text = effective_x_vector_only || effective_reference_text.empty()
        ? nullptr
        : effective_reference_text.c_str();
    const std::string diagnostic_dump_dir = options_.diagnostic_dump_dir.empty()
        ? std::string{}
        : options_.diagnostic_dump_dir.u8string();
    params.dump_dir = diagnostic_dump_dir.empty() ? nullptr : diagnostic_dump_dir.c_str();
    if (cached_reference != nullptr) {
        params.ref_spk_emb = cached_reference->ref_spk_emb;
        params.ref_spk_dim = cached_reference->ref_spk_dim;
        // A raw reference without a transcript is x-vector mode. Supplying
        // RVQ codes in that mode changes the qwentts prompt semantics and is
        // not equivalent to the uncached path. Reuse codes only for ICL.
        const bool use_cached_codes = !effective_x_vector_only && !effective_reference_text.empty();
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
            result.qwen_total_ms = qwen_metrics.pipeline_total_ms;
            result.qwen_n_frames = qwen_metrics.n_frames;
        }
        return result;
    };
    if (status == QT_STATUS_OK) {
        const auto finish_reason = api.last_finish_reason();
        if (finish_reason == QT_FINISH_EOS ||
            finish_reason == QT_FINISH_EOS_ASSISTED ||
            finish_reason == QT_FINISH_EOS_FORCED) {
            if (!callbacks.emitted_audio) {
                return apply_qwen_metrics({SynthesisOutcome::Failed, "model_error", "empty_audio",
                        "qwentts reported EOS without emitting PCM", {}, voice_reference_cache_hit,
                        voice_reference_extract_ms, reference_audio_decode_ms, synthesis_ms,
                        callbacks.first_chunk_callback_ms});
            }
            const char* execution_outcome = finish_reason == QT_FINISH_EOS_ASSISTED
                ? "eos_assisted"
                : finish_reason == QT_FINISH_EOS_FORCED ? "eos_forced" : "natural_eos";
            return apply_qwen_metrics({SynthesisOutcome::Completed, {}, {}, {}, execution_outcome, voice_reference_cache_hit,
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
    value.voice_profiles = !voice_profiles_.empty();
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

std::vector<std::string> NativeEngine::voice_ids() const {
    std::vector<std::string> ids;
    ids.reserve(voice_profiles_.size());
    for (const auto& [voice_id, profile] : voice_profiles_) {
        (void)profile;
        ids.push_back(voice_id);
    }
    std::sort(ids.begin(), ids.end());
    return ids;
}

const RuntimeManifest& NativeEngine::manifest() const {
    return loader_.manifest();
}

const std::string& NativeEngine::engine_version() const {
    return loader_.engine_version();
}

} // namespace qwen_tts_bridge::native_worker
