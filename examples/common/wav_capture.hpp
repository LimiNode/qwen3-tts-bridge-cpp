#pragma once

/// \file wav_capture.hpp
/// \brief Streaming WAV capture helper for the playback example.

#include <qwen_tts_bridge/audio.hpp>

#include <condition_variable>
#include <cstddef>
#include <deque>
#include <filesystem>
#include <functional>
#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <thread>
#include <vector>

namespace qwen_tts_examples {

/// \brief Captures post-processed PCM chunks into an atomically published WAV.
///
/// The helper is deliberately separate from PcmCapture: PcmCapture preserves
/// raw bridge PCM for diagnostics, while this class writes the chunks handed to
/// the playback sink, including terminal fade and padding. Appending only
/// copies into a bounded queue; a dedicated writer thread performs all disk
/// I/O so optional capture cannot delay playback submission. The destination
/// is published only after a complete RIFF/WAVE file has been closed. Queue
/// overflow and writer I/O failures fail closed: subsequent appends and
/// finalization report an error and no WAV is published. Destruction or
/// discard cancels pending capture and removes its temporary file. The result
/// represents post-processed PCM submitted to the sink, not physical DAC
/// output or an unbiased playback-performance measurement.
class WavCapture final {
public:
    explicit WavCapture(
        const std::string& file_name,
        std::function<void()> before_write_hook = {});
    ~WavCapture();

    WavCapture(const WavCapture&) = delete;
    WavCapture& operator=(const WavCapture&) = delete;

    void append(const qwen_tts_bridge::PcmChunk& chunk);
    void finalize();
    void discard() noexcept;
    [[nodiscard]] bool has_failed() const noexcept;

private:
    struct PendingChunk {
        qwen_tts_bridge::AudioFormat format;
        std::vector<std::byte> bytes;
    };

    static bool formats_match(
        const qwen_tts_bridge::AudioFormat& left,
        const qwen_tts_bridge::AudioFormat& right);
    static std::filesystem::path temporary_path(
        const std::filesystem::path& target);
    void writer_loop() noexcept;
    void request_stop() noexcept;
    void join_writer() noexcept;
    void fail_locked(std::string message) noexcept;

    static constexpr std::size_t kMaxQueuedChunks = 32;
    static constexpr std::size_t kMaxQueuedBytes = 8 * 1024 * 1024;

    mutable std::mutex mutex_;
    std::condition_variable condition_;
    std::deque<PendingChunk> queue_;
    std::size_t queued_bytes_ = 0;
    std::filesystem::path target_;
    std::filesystem::path temporary_;
    std::function<void()> before_write_hook_;
    std::unique_ptr<qwen_tts_bridge::audio::WavWriter> writer_;
    std::optional<qwen_tts_bridge::AudioFormat> format_;
    std::string failure_message_;
    std::thread writer_thread_;
    bool accepting_ = true;
    bool stop_requested_ = false;
    bool finalized_ = false;
};

} // namespace qwen_tts_examples
