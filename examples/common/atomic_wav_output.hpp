#pragma once

/// \file atomic_wav_output.hpp
/// \brief Fail-closed temporary WAV output for command-line examples.

#include <qwen_tts_bridge/audio.hpp>

#include <cstdint>
#include <filesystem>
#include <memory>
#include <string>

namespace qwen_tts_examples {

/// \brief Writes a WAV beside its destination and publishes it explicitly.
///
/// The destination must not exist when the object is constructed. Until
/// publish() succeeds, all bytes remain in a unique sibling temporary file.
/// Destruction removes unpublished data and never truncates an existing target.
class AtomicWavOutput final {
public:
    AtomicWavOutput(
        std::string target,
        std::uint32_t sample_rate,
        std::uint16_t channels,
        std::uint16_t bits_per_sample);
    ~AtomicWavOutput() noexcept;

    AtomicWavOutput(const AtomicWavOutput&) = delete;
    AtomicWavOutput& operator=(const AtomicWavOutput&) = delete;

    qwen_tts_bridge::audio::WavWriter& writer() noexcept;
    void publish();
    void rollback() noexcept;

    [[nodiscard]] const std::filesystem::path& target_path() const noexcept {
        return target_;
    }

    [[nodiscard]] const std::filesystem::path& temporary_path() const noexcept {
        return temporary_;
    }

    static bool paths_alias(
        const std::filesystem::path& left,
        const std::filesystem::path& right);
    static std::filesystem::path temporary_sibling(
        const std::filesystem::path& target);
    static void reserve_temporary_path(const std::filesystem::path& path);
    static void publish_temporary_path(
        const std::filesystem::path& temporary,
        const std::filesystem::path& target);

private:
    std::filesystem::path target_;
    std::filesystem::path temporary_;
    std::unique_ptr<qwen_tts_bridge::audio::WavWriter> writer_;
    bool published_ = false;
};

} // namespace qwen_tts_examples
