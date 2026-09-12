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
    bool use_flash_attention = true;
    bool clamp_fp16 = false;
    int max_batch = 1;
    float codec_chunk_seconds = 24.0F;
    int stream_max_chunk_frames = 8;
    int max_new_tokens = 2048;
    int max_text_bytes = 0; ///< Optional preflight bound; 0 disables length routing.
    bool precompute_voice_refs = false; ///< Cache qt_voice_ref values for repeated reference WAV requests.
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
    bool voice_reference_cache_hit = false;
    double voice_reference_extract_ms = 0.0;
};

using AudioChunkHandler = std::function<bool(const float*, int)>;

class NativeEngine final {
public:
    explicit NativeEngine(NativeEngineOptions options);
    ~NativeEngine();

    NativeEngine(const NativeEngine&) = delete;
    NativeEngine& operator=(const NativeEngine&) = delete;

    void load();
    void close() noexcept;
    void validate_request(const SynthesizeMessage& request) const;
    SynthesisResult synthesize(
        const SynthesizeMessage& request,
        const std::atomic<bool>& cancelled,
        const AudioChunkHandler& on_chunk);

    WorkerCapabilities capabilities() const;
    std::vector<std::string> speaker_names() const;
    const RuntimeManifest& manifest() const;
    const std::string& engine_version() const;

private:
    struct CachedVoiceReference {
        qt_voice_ref value{};
    };

    void clear_voice_reference_cache() noexcept;

    NativeEngineOptions options_;
    QwenDllLoader loader_;
    qt_context* context_ = nullptr;
    std::unordered_map<std::string, std::unique_ptr<CachedVoiceReference>> voice_reference_cache_;
};

} // namespace qwen_tts_bridge::native_worker
