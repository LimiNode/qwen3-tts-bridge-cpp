#include "atomic_wav_output.hpp"

#include <algorithm>
#include <atomic>
#include <cctype>
#include <stdexcept>

namespace qwen_tts_examples {
namespace {

std::string normalized_path_string(const std::filesystem::path& value) {
    auto result = std::filesystem::absolute(value).lexically_normal().generic_u8string();
#ifdef _WIN32
    std::transform(result.begin(), result.end(), result.begin(), [](char character) {
        return static_cast<char>(std::tolower(static_cast<unsigned char>(character)));
    });
#endif
    return result;
}

} // namespace

AtomicWavOutput::AtomicWavOutput(
    std::string target,
    std::uint32_t sample_rate,
    std::uint16_t channels,
    std::uint16_t bits_per_sample)
    : target_(std::filesystem::u8path(std::move(target))),
      temporary_(temporary_sibling(target_)) {
    if (target_.empty()) {
        throw std::runtime_error("output WAV path is empty");
    }
    if (std::filesystem::exists(target_)) {
        throw std::runtime_error(
            "refusing to overwrite existing WAV output: " + target_.u8string());
    }
    if (std::filesystem::exists(temporary_)) {
        throw std::runtime_error(
            "WAV output temporary path already exists: " + temporary_.u8string());
    }
    try {
        writer_ = std::make_unique<qwen_tts_bridge::audio::WavWriter>(
            temporary_.u8string(), sample_rate, channels, bits_per_sample);
    }
    catch (...) {
        std::error_code ignored;
        std::filesystem::remove(temporary_, ignored);
        throw;
    }
}

AtomicWavOutput::~AtomicWavOutput() noexcept {
    if (writer_ != nullptr) {
        writer_.reset();
    }
    if (!published_) {
        std::error_code ignored;
        std::filesystem::remove(temporary_, ignored);
    }
}

qwen_tts_bridge::audio::WavWriter& AtomicWavOutput::writer() noexcept {
    return *writer_;
}

void AtomicWavOutput::publish() {
    if (published_) {
        return;
    }
    if (writer_ == nullptr) {
        throw std::runtime_error("WAV output writer is not available");
    }
    writer_->close();
    writer_.reset();
    std::filesystem::rename(temporary_, target_);
    published_ = true;
}

void AtomicWavOutput::rollback() noexcept {
    if (writer_ != nullptr) {
        writer_.reset();
    }
    std::error_code ignored;
    if (published_) {
        std::filesystem::remove(target_, ignored);
        published_ = false;
    }
    std::filesystem::remove(temporary_, ignored);
}

bool AtomicWavOutput::paths_alias(
    const std::filesystem::path& left,
    const std::filesystem::path& right) {
    if (normalized_path_string(left) == normalized_path_string(right)) {
        return true;
    }
    std::error_code error;
    if (std::filesystem::exists(left, error) && !error) {
        error.clear();
        if (std::filesystem::exists(right, error) && !error) {
            error.clear();
            return std::filesystem::equivalent(left, right, error) && !error;
        }
    }
    return false;
}

std::filesystem::path AtomicWavOutput::temporary_sibling(
    const std::filesystem::path& target) {
    static std::atomic<std::uint64_t> sequence{0};
    const auto suffix = std::string(".tmp.qwen-wav.") +
        std::to_string(sequence.fetch_add(1, std::memory_order_relaxed));
    return std::filesystem::u8path(target.u8string() + suffix);
}

} // namespace qwen_tts_examples
