#pragma once

#include "RuntimeManifest.hpp"

#include <qwen.h>

#include <filesystem>
#include <string>

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

namespace qwen_tts_bridge::native_worker {

struct QwenApi {
    decltype(&qt_version) version = nullptr;
    decltype(&qt_last_error) last_error = nullptr;
    decltype(&qt_init_default_params) init_default_params = nullptr;
    decltype(&qt_init) init = nullptr;
    decltype(&qt_free) free = nullptr;
    decltype(&qt_tts_default_params) tts_default_params = nullptr;
    decltype(&qt_synthesize) synthesize = nullptr;
    decltype(&qt_audio_free) audio_free = nullptr;
    decltype(&qt_num_codebooks) num_codebooks = nullptr;
    decltype(&qt_n_speakers) n_speakers = nullptr;
    decltype(&qt_speaker_name) speaker_name = nullptr;
    decltype(&qt_duration_sec_to_tokens) duration_sec_to_tokens = nullptr;
    decltype(&qt_log_set) log_set = nullptr;
};

class QwenDllLoader final {
public:
    QwenDllLoader() = default;
    ~QwenDllLoader();

    QwenDllLoader(const QwenDllLoader&) = delete;
    QwenDllLoader& operator=(const QwenDllLoader&) = delete;

    void load(
        const std::filesystem::path& dll_path,
        const std::filesystem::path& manifest_path);
    void unload() noexcept;

    const QwenApi& api() const;
    const RuntimeManifest& manifest() const;
    const std::string& engine_version() const;

private:
    HMODULE module_ = nullptr;
    QwenApi api_;
    RuntimeManifest manifest_;
    std::string engine_version_;
};

} // namespace qwen_tts_bridge::native_worker
