#include "wav_capture.hpp"

#define WIN32_LEAN_AND_MEAN
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>

#include <stdexcept>

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
    if (!format_.has_value()) {
        format_ = chunk.format;
        writer_ = std::make_unique<qwen_tts_bridge::audio::WavWriter>(
            temporary_.u8string(),
            format_->sample_rate,
            format_->channels,
            16);
    }
    else if (!formats_match(format_.value(), chunk.format)) {
        throw std::runtime_error(
            "WAV capture cannot combine chunks with different audio formats");
    }
    writer_->write_pcm(chunk.bytes.data(), chunk.bytes.size());
}

void WavCapture::finalize() {
    if (finalized_) {
        return;
    }
    if (writer_ == nullptr || writer_->data_size() == 0) {
        throw std::runtime_error("cannot finalize WAV capture without audio");
    }
    writer_->close();
    writer_.reset();
    try {
        std::filesystem::rename(temporary_, target_);
        finalized_ = true;
    }
    catch (...) {
        std::error_code ignored;
        std::filesystem::remove(temporary_, ignored);
        throw;
    }
}

void WavCapture::discard() noexcept {
    if (writer_ != nullptr) {
        try {
            writer_->close();
        }
        catch (...) {
        }
        writer_.reset();
    }
    if (!finalized_) {
        std::error_code ignored;
        std::filesystem::remove(temporary_, ignored);
    }
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
