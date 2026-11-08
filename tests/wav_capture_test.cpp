#include "examples/common/wav_capture.hpp"

#define WIN32_LEAN_AND_MEAN
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>

#include <cstddef>
#include <cstdint>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <initializer_list>
#include <iostream>
#include <iterator>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

using qwen_tts_bridge::PcmChunk;
using qwen_tts_examples::WavCapture;

class TemporaryDirectory final {
public:
    TemporaryDirectory()
        : path_(std::filesystem::temp_directory_path()) {
        const auto stamp = std::chrono::high_resolution_clock::now()
            .time_since_epoch().count();
        for (std::uint32_t attempt = 0; attempt != 100; ++attempt) {
            const auto candidate = path_ /
                ("qwen_tts_bridge_wav_capture_" +
                    std::to_string(GetCurrentProcessId()) + "_" +
                    std::to_string(stamp) + "_" + std::to_string(attempt));
            std::error_code error;
            if (std::filesystem::create_directory(candidate, error)) {
                path_ = candidate;
                return;
            }
            if (error && error != std::errc::file_exists) {
                throw std::runtime_error(
                    "failed to create WAV capture test directory: " + error.message());
            }
        }
        throw std::runtime_error("could not allocate unique WAV capture test directory");
    }

    ~TemporaryDirectory() {
        std::error_code ignored;
        std::filesystem::remove_all(path_, ignored);
    }

    TemporaryDirectory(const TemporaryDirectory&) = delete;
    TemporaryDirectory& operator=(const TemporaryDirectory&) = delete;

    [[nodiscard]] const std::filesystem::path& path() const noexcept {
        return path_;
    }

private:
    std::filesystem::path path_;
};

void expect(bool condition, const char* message) {
    if (!condition) {
        throw std::runtime_error(message);
    }
}

PcmChunk chunk(
    std::initializer_list<std::uint8_t> bytes,
    std::uint32_t sample_rate = 24'000) {
    PcmChunk value;
    value.format.sample_format = "s16le";
    value.format.sample_rate = sample_rate;
    value.format.channels = 1;
    value.bytes.reserve(bytes.size());
    for (const std::uint8_t byte : bytes) {
        value.bytes.push_back(static_cast<std::byte>(byte));
    }
    return value;
}

std::vector<std::byte> read_bytes(const std::filesystem::path& path) {
    std::ifstream input(path, std::ios::binary);
    if (!input) {
        throw std::runtime_error("failed to open generated WAV");
    }
    const std::vector<char> raw{
        std::istreambuf_iterator<char>(input),
        std::istreambuf_iterator<char>()};
    std::vector<std::byte> bytes;
    bytes.reserve(raw.size());
    for (const char value : raw) {
        bytes.push_back(static_cast<std::byte>(
            static_cast<unsigned char>(value)));
    }
    return bytes;
}

std::uint32_t read_u32_le(
    const std::vector<std::byte>& bytes,
    std::size_t offset) {
    expect(offset + 4 <= bytes.size(), "WAV field is truncated");
    return static_cast<std::uint32_t>(std::to_integer<std::uint8_t>(bytes[offset])) |
        (static_cast<std::uint32_t>(std::to_integer<std::uint8_t>(bytes[offset + 1])) << 8u) |
        (static_cast<std::uint32_t>(std::to_integer<std::uint8_t>(bytes[offset + 2])) << 16u) |
        (static_cast<std::uint32_t>(std::to_integer<std::uint8_t>(bytes[offset + 3])) << 24u);
}

std::uint16_t read_u16_le(
    const std::vector<std::byte>& bytes,
    std::size_t offset) {
    expect(offset + 2 <= bytes.size(), "WAV field is truncated");
    return static_cast<std::uint16_t>(
        std::to_integer<std::uint8_t>(bytes[offset])) |
        static_cast<std::uint16_t>(
            std::to_integer<std::uint8_t>(bytes[offset + 1]) << 8u);
}

void expect_ascii(
    const std::vector<std::byte>& bytes,
    std::size_t offset,
    const char* value) {
    for (std::size_t index = 0; value[index] != '\0'; ++index) {
        expect(
            offset + index < bytes.size() &&
                std::to_integer<unsigned char>(bytes[offset + index]) ==
                    static_cast<unsigned char>(value[index]),
            "WAV signature mismatch");
    }
}

void test_publishes_exact_post_processed_pcm() {
    TemporaryDirectory directory;
    const auto target = directory.path() / "processed.wav";
    qwen_tts_bridge::audio::AudioPostProcessorChain processors;
    qwen_tts_bridge::audio::TerminalFadeOptions fade_options;
    fade_options.fade_ms = 2;
    fade_options.completion_silence_ms = 3;
    processors.add(std::make_unique<
        qwen_tts_bridge::audio::TerminalFadePostProcessor>(fade_options));
    std::vector<std::byte> expected;
    {
        WavCapture capture(target.u8string());
        const auto input = chunk(
            {0xe8, 0x03, 0xe8, 0x03, 0xe8, 0x03, 0xe8, 0x03},
            1'000);
        for (const PcmChunk& output : processors.process(input)) {
            expected.insert(expected.end(), output.bytes.begin(), output.bytes.end());
            capture.append(output);
        }
        for (const PcmChunk& output : processors.finish(
                 qwen_tts_bridge::audio::AudioTerminalReason::Completed)) {
            expected.insert(expected.end(), output.bytes.begin(), output.bytes.end());
            capture.append(output);
        }
        capture.finalize();
    }

    const auto bytes = read_bytes(target);
    expect(bytes.size() == 44 + expected.size(), "unexpected WAV size");
    expect_ascii(bytes, 0, "RIFF");
    expect_ascii(bytes, 8, "WAVE");
    expect_ascii(bytes, 12, "fmt ");
    expect_ascii(bytes, 36, "data");
    expect(read_u16_le(bytes, 20) == 1, "unexpected WAV format code");
    expect(read_u16_le(bytes, 22) == 1, "unexpected WAV channel count");
    expect(read_u32_le(bytes, 24) == 1'000, "unexpected WAV sample rate");
    expect(read_u16_le(bytes, 34) == 16, "unexpected WAV bit depth");
    expect(
        read_u32_le(bytes, 4) == 36 + expected.size(),
        "unexpected RIFF size");
    expect(
        read_u32_le(bytes, 40) == expected.size(),
        "unexpected data size");
    expect(
        std::vector<std::byte>(bytes.begin() + 44, bytes.end()) == expected,
        "WAV PCM bytes differ from post-processed input");
}

void test_no_tail_capture_preserves_pcm() {
    TemporaryDirectory directory;
    const auto target = directory.path() / "no-tail.wav";
    const auto input = chunk({0x10, 0x00, 0x08, 0x00});
    {
        WavCapture capture(target.u8string());
        capture.append(input);
        capture.finalize();
    }
    const auto bytes = read_bytes(target);
    expect(
        std::vector<std::byte>(bytes.begin() + 44, bytes.end()) == input.bytes,
        "no-tail WAV changed PCM bytes");
}

void test_incomplete_capture_is_removed() {
    TemporaryDirectory directory;
    const auto target = directory.path() / "incomplete.wav";
    {
        WavCapture capture(target.u8string());
        capture.append(chunk({0x01, 0x00}));
    }
    expect(!std::filesystem::exists(target), "incomplete WAV was published");
}

void test_writer_failure_does_not_publish() {
    TemporaryDirectory directory;
    const auto target = directory.path() / "missing" / "failed.wav";
    WavCapture capture(target.u8string());
    capture.append(chunk({0x01, 0x00}));
    bool failed = false;
    try {
        capture.finalize();
    }
    catch (const std::exception&) {
        failed = true;
    }
    expect(failed, "writer failure was not reported");
    expect(!std::filesystem::exists(target), "failed WAV was published");
}

void test_rejects_existing_target_and_format_mismatch() {
    TemporaryDirectory directory;
    const auto target = directory.path() / "existing.wav";
    {
        std::ofstream output(target, std::ios::binary);
        output << "sentinel";
    }
    bool existing_failed = false;
    try {
        WavCapture capture(target.u8string());
    }
    catch (const std::exception&) {
        existing_failed = true;
    }
    expect(existing_failed, "existing target was not rejected");
    expect(
        std::filesystem::file_size(target) == std::string("sentinel").size(),
        "existing target was modified");

    const auto mismatch_target = directory.path() / "mismatch.wav";
    WavCapture capture(mismatch_target.u8string());
    capture.append(chunk({0x01, 0x00}));
    auto mismatch = chunk({0x02, 0x00});
    mismatch.format.sample_rate = 16'000;
    bool mismatch_failed = false;
    try {
        capture.append(mismatch);
    }
    catch (const std::exception&) {
        mismatch_failed = true;
    }
    expect(mismatch_failed, "format mismatch was not rejected");
}

} // namespace

int main() {
    try {
        test_publishes_exact_post_processed_pcm();
        test_no_tail_capture_preserves_pcm();
        test_incomplete_capture_is_removed();
        test_writer_failure_does_not_publish();
        test_rejects_existing_target_and_format_mismatch();
        return 0;
    }
    catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
