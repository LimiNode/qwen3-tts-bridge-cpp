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
#include <chrono>
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

std::filesystem::path g_root;
bool g_root_owned = false;

void cleanup_owned_root() noexcept {
    if (!g_root_owned) {
        return;
    }
    std::error_code ignored;
    std::filesystem::remove_all(g_root, ignored);
    g_root_owned = false;
}

std::filesystem::path create_unique_directory(
    const std::filesystem::path& parent,
    const std::string& prefix) {
    for (std::uint32_t attempt = 0; attempt < 100; ++attempt) {
        const auto candidate = parent /
            (prefix + "_" + std::to_string(GetCurrentProcessId()) +
             "_" + std::to_string(attempt));
        std::error_code error;
        if (std::filesystem::create_directory(candidate, error)) {
            return candidate;
        }
        if (!error || error == std::errc::file_exists) {
            continue;
        }
        throw std::runtime_error(
            "failed to create unique PCM capture test directory: " +
            error.message());
    }
    throw std::runtime_error("failed to find a unique PCM capture test directory");
}

const std::filesystem::path& root() {
    return g_root;
}

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
    const auto target = root() / std::filesystem::u8path(u8"многочастный capture.pcm");
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
    const auto mismatch_target = root() / "format-mismatch.pcm";
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

    const auto empty_target = root() / "empty.pcm";
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
    const auto target = root() / "conflict.pcm";
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
    const auto target = root() / "rollback.pcm";
    const auto unrelated = root() / "unrelated.txt";
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

void test_unique_directory_collision_preserves_sentinel() {
    const auto collision_base = root() / "collision-base";
    std::filesystem::create_directory(collision_base);
    const auto collision = collision_base /
        (std::string("capture_") + std::to_string(GetCurrentProcessId()) + "_0");
    CHECK(std::filesystem::create_directory(collision));
    const auto sentinel = collision / "sentinel.txt";
    std::ofstream(sentinel) << "pre-existing data";

    const auto owned = create_unique_directory(collision_base, "capture");
    CHECK(owned != collision);
    CHECK(read_text(sentinel) == "pre-existing data");
    std::error_code ignored;
    std::filesystem::remove_all(owned, ignored);
    std::filesystem::remove_all(collision_base, ignored);
}

} // namespace

int main() {
    try {
        const auto stamp = std::chrono::steady_clock::now().time_since_epoch().count();
        g_root = create_unique_directory(
            std::filesystem::temp_directory_path(),
            "qwen_tts_bridge_pcm_capture_" + std::to_string(stamp));
        g_root_owned = true;
        std::atexit(cleanup_owned_root);

        test_exact_capture_and_metadata();
        test_rejects_format_mismatch_and_empty_capture();
        test_rejects_existing_targets_and_temporary_paths();
        test_rolls_back_pcm_when_metadata_publication_fails();
        test_unique_directory_collision_preserves_sentinel();
        cleanup_owned_root();
        return 0;
    }
    catch (const std::exception& error) {
        std::cerr << "pcm_capture_test failed: " << error.what() << '\n';
        cleanup_owned_root();
        return EXIT_FAILURE;
    }
}
