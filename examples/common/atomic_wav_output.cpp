#include "atomic_wav_output.hpp"

#include <algorithm>
#include <array>
#include <cctype>
#include <chrono>
#include <iomanip>
#include <random>
#include <sstream>
#include <stdexcept>
#include <thread>

#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#else
#include <fcntl.h>
#include <unistd.h>
#endif

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
    if (std::filesystem::symlink_status(target_).type() !=
        std::filesystem::file_type::not_found) {
        throw std::runtime_error(
            "refusing to overwrite existing WAV output: " + target_.u8string());
    }
    try {
        reserve_temporary_path(temporary_);
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
#ifdef _WIN32
    if (!MoveFileExW(
            temporary_.c_str(),
            target_.c_str(),
            MOVEFILE_WRITE_THROUGH)) {
        throw std::runtime_error(
            "failed to publish WAV without replacing an existing target: " +
            target_.u8string());
    }
#else
    if (std::filesystem::symlink_status(target_).type() !=
        std::filesystem::file_type::not_found) {
        throw std::runtime_error(
            "refusing to replace target created during WAV publication: " +
            target_.u8string());
    }
    std::filesystem::rename(temporary_, target_);
#endif
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
    std::random_device random;
    const auto now = std::chrono::steady_clock::now().time_since_epoch().count();
    const auto thread_id = std::hash<std::thread::id>{}(std::this_thread::get_id());
    const std::array<unsigned int, 4> values{
        random(), random(), static_cast<unsigned int>(now),
        static_cast<unsigned int>(thread_id)};
    std::ostringstream suffix;
    suffix << ".tmp.qwen-wav." << std::hex << std::setfill('0');
    for (const auto value : values) {
        suffix << std::setw(8) << value;
    }
    suffix << ".wav";
    return std::filesystem::u8path(target.u8string() + suffix.str());
}

void AtomicWavOutput::reserve_temporary_path(
    const std::filesystem::path& path) {
#ifdef _WIN32
    const auto handle = CreateFileW(
        path.c_str(),
        GENERIC_WRITE,
        0,
        nullptr,
        CREATE_NEW,
        FILE_ATTRIBUTE_TEMPORARY,
        nullptr);
    if (handle == INVALID_HANDLE_VALUE) {
        throw std::runtime_error(
            "failed to reserve temporary output: " + path.u8string());
    }
    CloseHandle(handle);
#else
    const int descriptor = ::open(path.c_str(), O_WRONLY | O_CREAT | O_EXCL, 0600);
    if (descriptor == -1) {
        throw std::runtime_error(
            "failed to reserve temporary output: " + path.u8string());
    }
    ::close(descriptor);
#endif
}

void AtomicWavOutput::publish_temporary_path(
    const std::filesystem::path& temporary,
    const std::filesystem::path& target) {
#ifdef _WIN32
    if (!MoveFileExW(
            temporary.c_str(),
            target.c_str(),
            MOVEFILE_WRITE_THROUGH)) {
        throw std::runtime_error(
            "failed to publish temporary output without replacement: " +
            target.u8string());
    }
#else
    if (std::filesystem::symlink_status(target).type() !=
        std::filesystem::file_type::not_found) {
        throw std::runtime_error(
            "refusing to replace target created during publication: " +
            target.u8string());
    }
    std::filesystem::rename(temporary, target);
#endif
}

} // namespace qwen_tts_examples
