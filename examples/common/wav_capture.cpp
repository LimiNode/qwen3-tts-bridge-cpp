#include "wav_capture.hpp"

#define WIN32_LEAN_AND_MEAN
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>

#include <exception>
#include <limits>
#include <stdexcept>
#include <utility>

namespace qwen_tts_examples {

WavCapture::WavCapture(const std::string& file_name)
    : target_(std::filesystem::u8path(file_name)),
      temporary_(temporary_path(target_)) {
    if (std::filesystem::exists(target_)) {
        throw std::runtime_error("refusing to overwrite existing WAV capture file: " + file_name);
    }
    if (std::filesystem::exists(temporary_)) {
        throw std::runtime_error(
            "WAV capture temporary path already exists; remove it before retrying");
    }
    writer_thread_ = std::thread(&WavCapture::writer_loop, this);
}

WavCapture::~WavCapture() {
    discard();
}

void WavCapture::append(const qwen_tts_bridge::PcmChunk& chunk) {
    if (chunk.bytes.empty()) {
        return;
    }
    if (chunk.format.sample_format != "s16le" ||
        chunk.format.sample_rate == 0 || chunk.format.channels == 0) {
        throw std::runtime_error(
            "WAV capture requires non-empty s16le audio format metadata");
    }

    PendingChunk pending{chunk.format, chunk.bytes};
    std::unique_lock<std::mutex> lock(mutex_);
    if (!accepting_ || finalized_) {
        throw std::runtime_error(
            failure_message_.empty()
                ? "cannot append WAV capture after capture shutdown"
                : failure_message_);
    }
    if (!failure_message_.empty()) {
        throw std::runtime_error(failure_message_);
    }
    if (!format_.has_value()) {
        format_ = pending.format;
    }
    else if (!formats_match(format_.value(), pending.format)) {
        throw std::runtime_error(
            "WAV capture cannot combine chunks with different audio formats");
    }
    const std::size_t available_bytes = queued_bytes_ < kMaxQueuedBytes
        ? kMaxQueuedBytes - queued_bytes_
        : 0;
    if (queue_.size() >= kMaxQueuedChunks || pending.bytes.size() > available_bytes) {
        fail_locked(
            "WAV capture queue overflow; capture failed closed without publishing");
        throw std::runtime_error(failure_message_);
    }
    queued_bytes_ += pending.bytes.size();
    queue_.push_back(std::move(pending));
    lock.unlock();
    condition_.notify_one();
}

void WavCapture::finalize() {
    request_stop();
    join_writer();

    {
        std::lock_guard<std::mutex> lock(mutex_);
        if (finalized_) {
            return;
        }
        if (!failure_message_.empty()) {
            throw std::runtime_error(failure_message_);
        }
    }
    if (writer_ == nullptr || writer_->data_size() == 0) {
        throw std::runtime_error("cannot finalize WAV capture without audio");
    }
    writer_->close();
    writer_.reset();
    try {
        std::filesystem::rename(temporary_, target_);
        std::lock_guard<std::mutex> lock(mutex_);
        finalized_ = true;
    }
    catch (...) {
        std::error_code ignored;
        std::filesystem::remove(temporary_, ignored);
        throw;
    }
}

void WavCapture::discard() noexcept {
    request_stop();
    join_writer();
    if (writer_ != nullptr) {
        try {
            writer_->close();
        }
        catch (...) {
        }
        writer_.reset();
    }
    bool finalized = false;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        finalized = finalized_;
    }
    if (!finalized) {
        std::error_code ignored;
        std::filesystem::remove(temporary_, ignored);
    }
}

void WavCapture::writer_loop() noexcept {
    try {
        for (;;) {
            PendingChunk pending;
            {
                std::unique_lock<std::mutex> lock(mutex_);
                condition_.wait(lock, [this] {
                    return stop_requested_ || !queue_.empty();
                });
                if (queue_.empty()) {
                    if (stop_requested_) {
                        break;
                    }
                    continue;
                }
                pending = std::move(queue_.front());
                queue_.pop_front();
                queued_bytes_ -= pending.bytes.size();
            }

            if (writer_ == nullptr) {
                if (pending.format.channels >
                    std::numeric_limits<std::uint16_t>::max() / 2u) {
                    throw std::runtime_error(
                        "WAV capture channel count exceeds PCM16 block alignment");
                }
                writer_ = std::make_unique<qwen_tts_bridge::audio::WavWriter>(
                    temporary_.u8string(),
                    pending.format.sample_rate,
                    static_cast<std::uint16_t>(pending.format.channels),
                    16);
            }
            writer_->write_pcm(pending.bytes.data(), pending.bytes.size());
        }
    }
    catch (const std::exception& error) {
        std::lock_guard<std::mutex> lock(mutex_);
        fail_locked(std::string("WAV capture writer failed: ") + error.what());
    }
    catch (...) {
        std::lock_guard<std::mutex> lock(mutex_);
        fail_locked("WAV capture writer failed");
    }
}

void WavCapture::request_stop() noexcept {
    {
        std::lock_guard<std::mutex> lock(mutex_);
        accepting_ = false;
        stop_requested_ = true;
    }
    condition_.notify_one();
}

void WavCapture::join_writer() noexcept {
    if (writer_thread_.joinable()) {
        writer_thread_.join();
    }
}

void WavCapture::fail_locked(std::string message) noexcept {
    if (failure_message_.empty()) {
        failure_message_ = std::move(message);
    }
    accepting_ = false;
    stop_requested_ = true;
    queue_.clear();
    queued_bytes_ = 0;
    condition_.notify_all();
}

bool WavCapture::formats_match(
    const qwen_tts_bridge::AudioFormat& left,
    const qwen_tts_bridge::AudioFormat& right) {
    return left.sample_format == right.sample_format &&
        left.sample_rate == right.sample_rate &&
        left.channels == right.channels;
}

std::filesystem::path WavCapture::temporary_path(
    const std::filesystem::path& target) {
    return std::filesystem::path(
        target.native() + L".tmp." + std::to_wstring(GetCurrentProcessId()));
}

} // namespace qwen_tts_examples
