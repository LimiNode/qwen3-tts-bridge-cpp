#include "WavReader.hpp"

#include <algorithm>
#include <array>
#include <cstdint>
#include <cstring>
#include <cmath>
#include <fstream>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

namespace qwen_tts_bridge::native_worker {
namespace {

std::uint16_t read_u16(const unsigned char* data) {
    return static_cast<std::uint16_t>(data[0]) |
        (static_cast<std::uint16_t>(data[1]) << 8u);
}

std::uint32_t read_u32(const unsigned char* data) {
    return static_cast<std::uint32_t>(data[0]) |
        (static_cast<std::uint32_t>(data[1]) << 8u) |
        (static_cast<std::uint32_t>(data[2]) << 16u) |
        (static_cast<std::uint32_t>(data[3]) << 24u);
}

void read_exact(std::ifstream& input, void* output, std::size_t size, const char* what) {
    input.read(static_cast<char*>(output), static_cast<std::streamsize>(size));
    if (input.gcount() != static_cast<std::streamsize>(size)) {
        throw std::runtime_error(std::string("truncated WAV ") + what);
    }
}

} // namespace

std::vector<float> read_mono_24k_wav(const std::filesystem::path& path) {
    std::ifstream input(path, std::ios::binary);
    if (!input) {
        throw std::runtime_error("unable to open reference WAV: " + path.string());
    }

    std::array<unsigned char, 12> riff{};
    read_exact(input, riff.data(), riff.size(), "header");
    if (std::memcmp(riff.data(), "RIFF", 4) != 0 ||
        std::memcmp(riff.data() + 8, "WAVE", 4) != 0) {
        throw std::runtime_error("reference audio must be a RIFF/WAVE file");
    }

    std::uint16_t format = 0;
    std::uint16_t channels = 0;
    std::uint32_t sample_rate = 0;
    std::uint16_t bits_per_sample = 0;
    bool have_format = false;
    std::vector<unsigned char> data;

    while (input && (!have_format || data.empty())) {
        std::array<unsigned char, 8> chunk_header{};
        input.read(reinterpret_cast<char*>(chunk_header.data()), chunk_header.size());
        if (input.gcount() == 0) {
            break;
        }
        if (input.gcount() != static_cast<std::streamsize>(chunk_header.size())) {
            throw std::runtime_error("truncated WAV chunk header");
        }
        const std::uint32_t chunk_size = read_u32(chunk_header.data() + 4);
        if (chunk_size > 1024u * 1024u * 1024u) {
            throw std::runtime_error("reference WAV chunk is too large");
        }

        if (std::memcmp(chunk_header.data(), "fmt ", 4) == 0) {
            if (chunk_size < 16) {
                throw std::runtime_error("reference WAV fmt chunk is too small");
            }
            std::vector<unsigned char> bytes(chunk_size);
            read_exact(input, bytes.data(), bytes.size(), "fmt chunk");
            format = read_u16(bytes.data());
            channels = read_u16(bytes.data() + 2);
            sample_rate = read_u32(bytes.data() + 4);
            bits_per_sample = read_u16(bytes.data() + 14);
            have_format = true;
        }
        else if (std::memcmp(chunk_header.data(), "data", 4) == 0) {
            data.resize(chunk_size);
            read_exact(input, data.data(), data.size(), "data chunk");
        }
        else {
            input.seekg(chunk_size, std::ios::cur);
            if (!input) {
                throw std::runtime_error("truncated WAV ancillary chunk");
            }
        }
        if ((chunk_size & 1u) != 0u) {
            input.ignore(1);
        }
    }

    if (!have_format || data.empty()) {
        throw std::runtime_error("reference WAV is missing fmt or data");
    }
    if (channels != 1 || sample_rate != 24000) {
        throw std::runtime_error("reference WAV must be mono 24000 Hz");
    }

    std::vector<float> samples;
    if (format == 1 && bits_per_sample == 16) {
        if ((data.size() % 2u) != 0u) {
            throw std::runtime_error("reference WAV contains a partial PCM16 sample");
        }
        samples.reserve(data.size() / 2u);
        for (std::size_t offset = 0; offset < data.size(); offset += 2u) {
            const auto raw = static_cast<std::int16_t>(read_u16(data.data() + offset));
            samples.push_back(static_cast<float>(raw) / 32768.0F);
        }
    }
    else if (format == 3 && bits_per_sample == 32) {
        if ((data.size() % 4u) != 0u) {
            throw std::runtime_error("reference WAV contains a partial float32 sample");
        }
        samples.resize(data.size() / 4u);
        std::memcpy(samples.data(), data.data(), data.size());
        for (float& sample : samples) {
            if (!std::isfinite(sample)) {
                throw std::runtime_error("reference WAV contains a non-finite sample");
            }
            sample = std::clamp(sample, -1.0F, 1.0F);
        }
    }
    else {
        throw std::runtime_error("reference WAV must use PCM16 or IEEE float32 samples");
    }

    return samples;
}

} // namespace qwen_tts_bridge::native_worker
