#pragma once

/// \file pcm_capture.hpp
/// \brief Raw PCM capture helper shared by Windows examples and tests.

#include <qwen_tts_bridge/client.hpp>

#include <cstddef>
#include <filesystem>
#include <fstream>
#include <mutex>
#include <optional>
#include <string>

namespace qwen_tts_examples {

/// \brief Publishes raw PCM and metadata sequentially after streaming.
///
/// The helper intentionally captures the chunks delivered by the bridge before
/// any example-specific playback post-processing. It is not part of the public
/// SDK and is only used by the example diagnostic path. PCM publication is
/// followed by metadata publication; if the second step fails, the PCM file is
/// rolled back.
class PcmCapture final {
public:
    explicit PcmCapture(const std::string& file_name);
    ~PcmCapture();

    PcmCapture(const PcmCapture&) = delete;
    PcmCapture& operator=(const PcmCapture&) = delete;

    void append(const qwen_tts_bridge::PcmChunk& chunk);
    void finalize();

private:
    static bool formats_match(
        const qwen_tts_bridge::AudioFormat& left,
        const qwen_tts_bridge::AudioFormat& right);
    static std::filesystem::path metadata_path(
        const std::filesystem::path& target);
    static std::filesystem::path temporary_path(
        const std::filesystem::path& target);

    std::mutex mutex_;
    std::filesystem::path target_;
    std::filesystem::path metadata_target_;
    std::filesystem::path temporary_;
    std::filesystem::path metadata_temporary_;
    std::ofstream output_;
    std::optional<qwen_tts_bridge::AudioFormat> format_;
    std::size_t chunk_count_ = 0;
    std::size_t byte_count_ = 0;
    bool finalized_ = false;
};

} // namespace qwen_tts_examples
