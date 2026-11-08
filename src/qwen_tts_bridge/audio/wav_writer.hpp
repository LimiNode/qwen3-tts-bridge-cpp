#pragma once

/// \file wav_writer.hpp
/// \brief Small RIFF/WAVE PCM writer used by the save-wav example.

#include <cstddef>
#include <cstdint>
#include <fstream>
#include <string>

namespace qwen_tts_bridge::audio {

/// \brief Controls how WavWriter opens its destination.
enum class WavOpenMode {
    /// Create the file or truncate an existing file.
    truncate_existing,
    /// Open an already-created file without truncating it.
    open_existing
};

/// \class WavWriter
/// \brief Writes raw PCM bytes into a RIFF/WAVE file and patches the header on close.
///
/// The writer owns the output file. It is intentionally small and supports the
/// uncompressed PCM formats needed by the bridge examples.
class WavWriter final {
public:
    /// \brief Opens a WAV file and writes a placeholder header.
    /// \param path Output file path.
    /// \param sample_rate PCM sample rate in Hz.
    /// \param channels Number of PCM channels.
    /// \param bits_per_sample Bits per sample, for example 16 for s16le.
    /// \param open_mode Whether to truncate the destination or open an empty
    /// previously reserved file. Reservation is a name-level check; it does
    /// not provide continuous ownership if another process replaces the path.
    WavWriter(
        std::string path,
        std::uint32_t sample_rate,
        std::uint16_t channels,
        std::uint16_t bits_per_sample,
        WavOpenMode open_mode = WavOpenMode::truncate_existing);

    /// \brief Finalizes the file if it is still open.
    ~WavWriter() noexcept;

    WavWriter(const WavWriter&) = delete;
    WavWriter& operator=(const WavWriter&) = delete;

    /// \brief Writes one PCM byte chunk.
    /// \param data PCM bytes.
    /// \param size Byte count.
    void write_pcm(const std::byte* data, std::size_t size);

    /// \brief Patches RIFF sizes and closes the file.
    void close();

    /// \brief Returns the number of PCM bytes written so far.
    [[nodiscard]] std::uint64_t data_size() const noexcept;

private:
    void write_header(std::uint32_t data_size);
    void patch_header();
    void ensure_stream_ok(const char* action);

    std::ofstream file_;
    std::string path_;
    std::uint32_t sample_rate_ = 0;
    std::uint16_t channels_ = 0;
    std::uint16_t bits_per_sample_ = 0;
    std::uint16_t block_align_ = 0;
    std::uint64_t data_size_ = 0;
    WavOpenMode open_mode_ = WavOpenMode::truncate_existing;
    bool closed_ = true;
};

} // namespace qwen_tts_bridge::audio
