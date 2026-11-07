#pragma once

/// \file wav_capture.hpp
/// \brief Streaming WAV capture helper for the playback example.

#include <qwen_tts_bridge/audio/wav_writer.hpp>
#include <qwen_tts_bridge/client.hpp>

#include <filesystem>
#include <memory>
#include <optional>
#include <string>

namespace qwen_tts_examples {

/// \brief Captures post-processed PCM chunks into an atomically published WAV.
///
/// The helper is deliberately separate from PcmCapture: PcmCapture preserves
/// raw bridge PCM for diagnostics, while this class writes the chunks handed to
/// the playback sink, including terminal fade and padding. The destination is
/// published only after a complete RIFF/WAVE file has been closed.
class WavCapture final {
public:
    explicit WavCapture(const std::string& file_name);
    ~WavCapture();

    WavCapture(const WavCapture&) = delete;
    WavCapture& operator=(const WavCapture&) = delete;

    void append(const qwen_tts_bridge::PcmChunk& chunk);
    void finalize();
    void discard() noexcept;

private:
    static bool formats_match(
        const qwen_tts_bridge::AudioFormat& left,
        const qwen_tts_bridge::AudioFormat& right);
    static std::filesystem::path temporary_path(
        const std::filesystem::path& target);

    std::filesystem::path target_;
    std::filesystem::path temporary_;
    std::unique_ptr<qwen_tts_bridge::audio::WavWriter> writer_;
    std::optional<qwen_tts_bridge::AudioFormat> format_;
    bool finalized_ = false;
};

} // namespace qwen_tts_examples
