#pragma once

#include "QwenDllLoader.hpp"

#include <qwen_tts_bridge/protocol/control.hpp>

#include <atomic>
#include <filesystem>
#include <functional>
#include <memory>
#include <unordered_map>
#include <string>
#include <vector>

namespace qwen_tts_bridge::native_worker {

struct NativeEngineOptions {
    std::filesystem::path dll_path;
    std::filesystem::path manifest_path;
    std::filesystem::path talker_model;
    std::filesystem::path codec_model;
    /// Optional registered Base voice profile registry loaded at startup.
    std::filesystem::path voice_registry_path;
    /// Optional directory for qwentts tensor dumps and bounded AR traces.
    /// Diagnostic only; enabling it adds host work and filesystem I/O.
    std::filesystem::path diagnostic_dump_dir;
    bool use_flash_attention = true;
    bool clamp_fp16 = false;
    int max_batch = 1;
    float codec_chunk_seconds = 24.0F;
    int stream_max_chunk_frames = 8;
    int max_new_tokens = 2048;
    int max_text_bytes = 0; ///< Optional preflight bound; 0 disables length routing.
    /// Cache qt_voice_ref values for repeated reference WAV requests.
    /// The option is deliberately opt-in because it must preserve PCM and
    /// voice-identity parity with the uncached raw-WAV path first.
    bool precompute_voice_refs = false;
    /// Run one discarded synthesis before the worker announces `ready`.
    bool warmup_synthesis = false;
    std::string warmup_text = "Warmup.";
    std::string warmup_language = "auto";
    std::string warmup_voice_id;
};

enum class SynthesisOutcome {
    Completed,
    Cancelled,
    Failed
};

struct SynthesisResult {
    SynthesisOutcome outcome = SynthesisOutcome::Failed;
    std::string category;
    std::string code;
    std::string message;
    std::string execution_outcome;
    /// True when reusable voice conditioning came from the native cache.
    bool voice_reference_cache_hit = false;
    /// Time spent extracting reusable speaker/RVQ reference data.
    double voice_reference_extract_ms = 0.0;
    /// Time spent decoding the request's reference WAV.
    double reference_audio_decode_ms = 0.0;
    /// Wall time spent inside qt_synthesize.
    double synthesis_ms = 0.0;
    /// Time from qt_synthesize entry to the first non-empty PCM callback.
    double first_chunk_callback_ms = 0.0;
    /// qwentts internal prompt-build phase, when exposed by the runtime ABI.
    double qwen_prompt_build_ms = 0.0;
    /// qwentts internal Talker prefill phase, when exposed by the runtime ABI.
    double qwen_prefill_ms = 0.0;
    /// qwentts time to first generated codec frame, when exposed by the ABI.
    double qwen_ttfa_ms = 0.0;
    /// qwentts Talker autoregressive phase, when exposed by the runtime ABI.
    double qwen_talker_ms = 0.0;
    /// qwentts code-predictor phase, when exposed by the runtime ABI.
    double qwen_predictor_ms = 0.0;
    /// qwentts host-side composition phase, when exposed by the runtime ABI.
    double qwen_host_ms = 0.0;
    /// qwentts codec-decode phase, when exposed by the runtime ABI.
    double qwen_codec_ms = 0.0;
    /// qwentts internal total phase span, when exposed by the runtime ABI.
    double qwen_total_ms = 0.0;
    /// Number of generated codec frames reported by qwentts.
    int qwen_n_frames = 0;
};

using AudioChunkHandler = std::function<bool(const float*, int)>;

class NativeEngine final {
public:
    explicit NativeEngine(NativeEngineOptions options);
    ~NativeEngine();

    NativeEngine(const NativeEngine&) = delete;
    NativeEngine& operator=(const NativeEngine&) = delete;

    void load();
    /// Run the optional discarded synthesis warmup and mark the engine ready.
    void warmup();
    void close() noexcept;
    void validate_request(const SynthesizeMessage& request) const;
    SynthesisResult synthesize(
        const SynthesizeMessage& request,
        const std::atomic<bool>& cancelled,
        const AudioChunkHandler& on_chunk);

    WorkerCapabilities capabilities() const;
    std::vector<std::string> speaker_names() const;
    /// Return the registered Base voice identifiers advertised in `ready`.
    std::vector<std::string> voice_ids() const;
    bool warmed_up() const noexcept { return warmed_up_; }
    const RuntimeManifest& manifest() const;
    const std::string& engine_version() const;

private:
    struct CachedVoiceReference {
        qt_voice_ref value{};
    };

    struct VoiceProfile {
        std::filesystem::path reference_audio_path;
        std::string reference_text;
        bool preserve_reference_text_whitespace = false;
        bool x_vector_only = false;
        std::vector<float> reference_audio;
        std::string reference_cache_key;
    };

    void clear_voice_reference_cache() noexcept;
    void load_voice_registry();
    void preload_voice_registry();

    NativeEngineOptions options_;
    QwenDllLoader loader_;
    qt_context* context_ = nullptr;
    std::unordered_map<std::string, VoiceProfile> voice_profiles_;
    std::unordered_map<std::string, std::unique_ptr<CachedVoiceReference>> voice_reference_cache_;
    bool warmed_up_ = false;
};

} // namespace qwen_tts_bridge::native_worker
