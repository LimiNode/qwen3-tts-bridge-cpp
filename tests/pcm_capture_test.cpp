#include "examples/common/pcm_capture.hpp"

#define WIN32_LEAN_AND_MEAN
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>

#include <qwen_tts_bridge/audio.hpp>

#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <initializer_list>
#include <iostream>
#include <iterator>
#include <stdexcept>
#include <string>
#include <vector>

#define CHECK(expr)                                                            \
    do {                                                                       \
        if (!(expr)) {                                                         \
            std::cerr << "CHECK failed: " #expr << " at " << __FILE__ << ':'  \
                      << __LINE__ << '\n';                                    \
            std::exit(EXIT_FAILURE);                                           \
        }                                                                      \
    } while (false)

namespace {

using qwen_tts_bridge::PcmChunk;
using qwen_tts_examples::PcmCapture;

const std::filesystem::path kRoot =
    std::filesystem::temp_directory_path() /
    (std::string("qwen_tts_bridge_pcm_capture_") +
     std::to_string(GetCurrentProcessId()));

PcmChunk chunk(std::initializer_list<std::uint8_t> bytes, std::uint32_t rate = 24000) {
    PcmChunk result;
    result.format.sample_format = "s16le";
    result.format.sample_rate = rate;
    result.format.channels = 1;
    for (const auto value : bytes) {
        result.bytes.push_back(static_cast<std::byte>(value));
    }
    return result;
}

std::filesystem::path metadata_path(const std::filesystem::path& target) {
    return std::filesystem::path(target.native() + L".json");
}

std::filesystem::path temporary_path(const std::filesystem::path& target) {
    return std::filesystem::path(
        target.native() + L".tmp." + std::to_wstring(GetCurrentProcessId()));
}

void remove_capture(const std::filesystem::path& target) {
    std::error_code ignored;
    std::filesystem::remove(target, ignored);
    std::filesystem::remove(metadata_path(target), ignored);
    std::filesystem::remove(temporary_path(target), ignored);
    std::filesystem::remove(temporary_path(metadata_path(target)), ignored);
}

std::vector<std::byte> read_bytes(const std::filesystem::path& path) {
    std::ifstream input(path, std::ios::binary);
    CHECK(input.good());
    const std::vector<char> raw(
        (std::istreambuf_iterator<char>(input)), std::istreambuf_iterator<char>());
    std::vector<std::byte> bytes;
    bytes.reserve(raw.size());
    for (const char value : raw) {
        bytes.push_back(static_cast<std::byte>(static_cast<unsigned char>(value)));
    }
    return bytes;
}

std::string read_text(const std::filesystem::path& path) {
    std::ifstream input(path, std::ios::binary);
    CHECK(input.good());
    return std::string(
        (std::istreambuf_iterator<char>(input)), std::istreambuf_iterator<char>());
}

void test_exact_capture_and_metadata() {
    const auto target = kRoot / std::filesystem::u8path(u8"многочастный capture.pcm");
    remove_capture(target);
    {
        PcmCapture capture(target.u8string());
        capture.append(chunk({0x01, 0x02}));
        capture.append(chunk({0x03, 0x04, 0x05, 0x06}));
        capture.finalize();
        capture.finalize();
        bool rejected = false;
        try {
            capture.append(chunk({0x07, 0x08}));
        }
        catch (const std::runtime_error&) {
            rejected = true;
        }
        CHECK(rejected);
    }
    const std::vector<std::byte> expected_bytes{
        std::byte{0x01}, std::byte{0x02}, std::byte{0x03},
        std::byte{0x04}, std::byte{0x05}, std::byte{0x06}};
    CHECK(read_bytes(target) == expected_bytes);
    CHECK(read_text(metadata_path(target)) ==
        "{\n"
        "  \"schema_version\": 1,\n"
        "  \"measurement\": \"raw_s16le_pcm_capture\",\n"
        "  \"completed\": true,\n"
        "  \"audio_chunk_count\": 2,\n"
        "  \"byte_count\": 6,\n"
        "  \"audio_format\": {\"sample_format\": \"s16le\", \"sample_rate\": 24000, \"channels\": 1}\n"
        "}\n");
    remove_capture(target);
}

void test_rejects_format_mismatch_and_empty_capture() {
    const auto mismatch_target = kRoot / "format-mismatch.pcm";
    remove_capture(mismatch_target);
    {
        PcmCapture capture(mismatch_target.u8string());
        capture.append(chunk({0x01, 0x02}));
        bool rejected = false;
        try {
            capture.append(chunk({0x03, 0x04}, 16000));
        }
        catch (const std::runtime_error&) {
            rejected = true;
        }
        CHECK(rejected);
    }
    CHECK(!std::filesystem::exists(temporary_path(mismatch_target)));

    const auto empty_target = kRoot / "empty.pcm";
    remove_capture(empty_target);
    {
        PcmCapture capture(empty_target.u8string());
        bool rejected = false;
        try {
            capture.finalize();
        }
        catch (const std::runtime_error&) {
            rejected = true;
        }
        CHECK(rejected);
    }
    CHECK(!std::filesystem::exists(temporary_path(empty_target)));
    remove_capture(mismatch_target);
    remove_capture(empty_target);
}

void test_rejects_existing_targets_and_temporary_paths() {
    const auto target = kRoot / "conflict.pcm";
    remove_capture(target);
    {
        std::ofstream(target) << "sentinel";
        bool rejected = false;
        try { PcmCapture capture(target.u8string()); }
        catch (const std::runtime_error&) { rejected = true; }
        CHECK(rejected);
        CHECK(read_text(target) == "sentinel");
        std::filesystem::remove(target);
    }
    {
        std::ofstream(metadata_path(target)) << "sentinel";
        bool rejected = false;
        try { PcmCapture capture(target.u8string()); }
        catch (const std::runtime_error&) { rejected = true; }
        CHECK(rejected);
        CHECK(read_text(metadata_path(target)) == "sentinel");
        std::filesystem::remove(metadata_path(target));
    }
    {
        std::ofstream(temporary_path(target)) << "sentinel";
        bool rejected = false;
        try { PcmCapture capture(target.u8string()); }
        catch (const std::runtime_error&) { rejected = true; }
        CHECK(rejected);
        CHECK(read_text(temporary_path(target)) == "sentinel");
        std::filesystem::remove(temporary_path(target));
    }
    {
        std::ofstream(temporary_path(metadata_path(target))) << "sentinel";
        bool rejected = false;
        try { PcmCapture capture(target.u8string()); }
        catch (const std::runtime_error&) { rejected = true; }
        CHECK(rejected);
        CHECK(read_text(temporary_path(metadata_path(target))) == "sentinel");
        std::filesystem::remove(temporary_path(metadata_path(target)));
    }
    remove_capture(target);
}

void test_rolls_back_pcm_when_metadata_publication_fails() {
    const auto target = kRoot / "rollback.pcm";
    const auto unrelated = kRoot / "unrelated.txt";
    remove_capture(target);
    std::ofstream(unrelated) << "keep me";
    {
        PcmCapture capture(target.u8string());
        capture.append(chunk({0x11, 0x22}));
        std::filesystem::create_directory(metadata_path(target));
        std::ofstream(metadata_path(target) / "sentinel.txt") << "metadata sentinel";
        bool rejected = false;
        try { capture.finalize(); }
        catch (const std::runtime_error&) { rejected = true; }
        CHECK(rejected);
        CHECK(!std::filesystem::exists(target));
        CHECK(std::filesystem::is_directory(metadata_path(target)));
        CHECK(read_text(metadata_path(target) / "sentinel.txt") == "metadata sentinel");
        CHECK(!std::filesystem::exists(temporary_path(metadata_path(target))));
    }
    CHECK(!std::filesystem::exists(temporary_path(target)));
    CHECK(read_text(unrelated) == "keep me");
    std::filesystem::remove(unrelated);
    remove_capture(target);
}

} // namespace

int main() {
    std::error_code ignored;
    std::filesystem::remove_all(kRoot, ignored);
    std::filesystem::create_directories(kRoot);
    test_exact_capture_and_metadata();
    test_rejects_format_mismatch_and_empty_capture();
    test_rejects_existing_targets_and_temporary_paths();
    test_rolls_back_pcm_when_metadata_publication_fails();
    std::filesystem::remove_all(kRoot, ignored);
    return 0;
}
