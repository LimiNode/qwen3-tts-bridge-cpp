#include "pcm_capture.hpp"

#define WIN32_LEAN_AND_MEAN
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>

#include <sstream>
#include <stdexcept>

namespace qwen_tts_examples {

PcmCapture::PcmCapture(const std::string& file_name)
    : target_(std::filesystem::u8path(file_name)),
      metadata_target_(metadata_path(target_)),
      temporary_(temporary_path(target_)),
      metadata_temporary_(temporary_path(metadata_target_)) {
    if (std::filesystem::exists(target_)) {
        throw std::runtime_error("refusing to overwrite existing PCM capture file: " + file_name);
    }
    if (std::filesystem::exists(metadata_target_)) {
        throw std::runtime_error(
            "refusing to overwrite existing PCM capture metadata file: " +
            metadata_target_.string());
    }
    if (std::filesystem::exists(temporary_) || std::filesystem::exists(metadata_temporary_)) {
        throw std::runtime_error("PCM capture temporary path already exists; remove it before retrying");
    }
    output_.open(temporary_, std::ios::binary | std::ios::trunc);
    if (!output_) {
        throw std::runtime_error("failed to open PCM capture file: " + temporary_.string());
    }
}

PcmCapture::~PcmCapture() {
    output_.close();
    if (!finalized_) {
        std::error_code ignored;
        std::filesystem::remove(temporary_, ignored);
        std::filesystem::remove(metadata_temporary_, ignored);
    }
}

void PcmCapture::append(const qwen_tts_bridge::PcmChunk& chunk) {
    if (chunk.bytes.empty()) {
        return;
    }

    std::lock_guard<std::mutex> lock(mutex_);
    if (finalized_) {
        throw std::runtime_error("cannot append PCM after capture finalization");
    }
    if (!format_.has_value()) {
        format_ = chunk.format;
    }
    else if (!formats_match(format_.value(), chunk.format)) {
        throw std::runtime_error("PCM capture cannot combine chunks with different audio formats");
    }
    output_.write(
        reinterpret_cast<const char*>(chunk.bytes.data()),
        static_cast<std::streamsize>(chunk.bytes.size()));
    if (!output_) {
        throw std::runtime_error("failed to write PCM capture file: " + temporary_.string());
    }
    byte_count_ += chunk.bytes.size();
    ++chunk_count_;
}

void PcmCapture::finalize() {
    std::lock_guard<std::mutex> lock(mutex_);
    if (finalized_) {
        return;
    }
    if (!format_.has_value() || byte_count_ == 0) {
        throw std::runtime_error("cannot finalize PCM capture without audio");
    }
    output_.close();
    if (!output_) {
        throw std::runtime_error("failed to close PCM capture file: " + temporary_.string());
    }

    std::ostringstream metadata;
    metadata << "{\n"
             << "  \"schema_version\": 1,\n"
             << "  \"measurement\": \"raw_s16le_pcm_capture\",\n"
             << "  \"completed\": true,\n"
             << "  \"audio_chunk_count\": " << chunk_count_ << ",\n"
             << "  \"byte_count\": " << byte_count_ << ",\n"
             << "  \"audio_format\": {\"sample_format\": \""
             << format_.value().sample_format << "\", \"sample_rate\": "
             << format_.value().sample_rate << ", \"channels\": "
             << format_.value().channels << "}\n"
             << "}\n";
    bool pcm_promoted = false;
    try {
        std::ofstream metadata_output(metadata_temporary_, std::ios::binary | std::ios::trunc);
        if (!metadata_output) {
            throw std::runtime_error(
                "failed to open PCM capture metadata file: " + metadata_temporary_.string());
        }
        metadata_output << metadata.str();
        metadata_output.close();
        if (!metadata_output) {
            throw std::runtime_error(
                "failed to write PCM capture metadata file: " + metadata_temporary_.string());
        }
        std::filesystem::rename(temporary_, target_);
        pcm_promoted = true;
        std::filesystem::rename(metadata_temporary_, metadata_target_);
        finalized_ = true;
    }
    catch (...) {
        if (pcm_promoted) {
            std::error_code rollback_error;
            std::filesystem::rename(target_, temporary_, rollback_error);
            if (rollback_error) {
                throw std::runtime_error(
                    "failed to roll back incomplete PCM capture finalization: " +
                    rollback_error.message());
            }
        }
        std::error_code ignored;
        std::filesystem::remove(metadata_temporary_, ignored);
        throw;
    }
}

bool PcmCapture::formats_match(
    const qwen_tts_bridge::AudioFormat& left,
    const qwen_tts_bridge::AudioFormat& right) {
    return left.sample_format == right.sample_format &&
        left.sample_rate == right.sample_rate &&
        left.channels == right.channels;
}

std::filesystem::path PcmCapture::metadata_path(const std::filesystem::path& target) {
    return std::filesystem::path(target.native() + L".json");
}

std::filesystem::path PcmCapture::temporary_path(const std::filesystem::path& target) {
    return std::filesystem::path(
        target.native() + L".tmp." + std::to_wstring(GetCurrentProcessId()));
}

} // namespace qwen_tts_examples
