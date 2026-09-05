#pragma once

#include "QwenDllLoader.hpp"

#include <qwen_tts_bridge/protocol/control.hpp>

#include <atomic>
#include <filesystem>
#include <functional>
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
    int max_new_tokens = 2048;
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
    NativeEngineOptions options_;
    QwenDllLoader loader_;
    qt_context* context_ = nullptr;
};

} // namespace qwen_tts_bridge::native_worker
