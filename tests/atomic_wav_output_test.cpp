#include "examples/common/atomic_wav_output.hpp"

#include <cstddef>
#include <atomic>
#include <chrono>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <stdexcept>
#include <string>

namespace {

void expect(bool condition, const char* message) {
    if (!condition) {
        throw std::runtime_error(message);
    }
}

std::filesystem::path test_directory() {
    static std::atomic<unsigned long long> sequence{0};
    const auto stamp = std::chrono::steady_clock::now().time_since_epoch().count();
    const auto path = std::filesystem::temp_directory_path() /
        ("qwen_tts_bridge_atomic_wav_output_" +
         std::to_string(stamp) + "_" +
         std::to_string(sequence.fetch_add(1, std::memory_order_relaxed)));
    std::error_code error;
    std::filesystem::create_directories(path, error);
    if (error) {
        throw std::runtime_error("failed to create output test directory");
    }
    return path;
}

struct DirectoryCleanup {
    std::filesystem::path path;
    ~DirectoryCleanup() {
        std::error_code ignored;
        std::filesystem::remove_all(path, ignored);
    }
};

void test_existing_target_is_preserved() {
    DirectoryCleanup cleanup{test_directory()};
    const auto target = cleanup.path / "existing.wav";
    {
        std::ofstream output(target, std::ios::binary | std::ios::trunc);
        output << "sentinel";
    }
    bool rejected = false;
    try {
        qwen_tts_examples::AtomicWavOutput output(target.u8string(), 24'000, 1, 16);
    }
    catch (const std::exception&) {
        rejected = true;
    }
    expect(rejected, "existing WAV target was accepted");
    std::ifstream input(target, std::ios::binary);
    const std::string contents(
        (std::istreambuf_iterator<char>(input)), std::istreambuf_iterator<char>());
    expect(contents == "sentinel", "existing WAV target was modified");
}

void test_aliasing_paths_are_rejected() {
    DirectoryCleanup cleanup{test_directory()};
    const auto target = cleanup.path / "alias.wav";
    const auto equivalent = target.parent_path() / "." / target.filename();
    expect(
        qwen_tts_examples::AtomicWavOutput::paths_alias(target, equivalent),
        "equivalent output paths were not recognized");
}

void test_existing_temporary_wav_is_preserved_after_failed_reservation() {
    DirectoryCleanup cleanup{test_directory()};
    const auto temporary = cleanup.path / "reserved.wav";
    {
        std::ofstream output(temporary, std::ios::binary | std::ios::trunc);
        output << "wav-sentinel";
    }
    bool collision_rejected = false;
    try {
        qwen_tts_examples::AtomicWavOutput::reserve_temporary_path(temporary);
    }
    catch (const std::exception&) {
        collision_rejected = true;
    }
    expect(collision_rejected, "WAV temporary reservation accepted a collision");
    std::ifstream input(temporary, std::ios::binary);
    const std::string contents(
        (std::istreambuf_iterator<char>(input)), std::istreambuf_iterator<char>());
    expect(contents == "wav-sentinel", "pre-existing WAV temporary was modified");
}

void test_existing_temporary_json_is_preserved_after_failed_reservation() {
    DirectoryCleanup cleanup{test_directory()};
    const auto temporary = cleanup.path / "reserved.json";
    {
        std::ofstream output(temporary, std::ios::binary | std::ios::trunc);
        output << "json-sentinel";
    }
    bool collision_rejected = false;
    try {
        qwen_tts_examples::AtomicWavOutput::reserve_temporary_path(temporary);
    }
    catch (const std::exception&) {
        collision_rejected = true;
    }
    expect(collision_rejected, "temporary reservation was not exclusive");
    std::ifstream input(temporary, std::ios::binary);
    const std::string contents(
        (std::istreambuf_iterator<char>(input)), std::istreambuf_iterator<char>());
    expect(contents == "json-sentinel", "pre-existing temporary file was modified");
}

void test_concurrent_outputs_preserve_first_publication() {
    DirectoryCleanup cleanup{test_directory()};
    const auto target = cleanup.path / "concurrent.wav";
    qwen_tts_examples::AtomicWavOutput first(target.u8string(), 24'000, 1, 16);
    qwen_tts_examples::AtomicWavOutput second(target.u8string(), 24'000, 1, 16);
    expect(
        first.temporary_path() != second.temporary_path(),
        "concurrent outputs reused a temporary path");
    const std::byte sample[]{std::byte{0x01}, std::byte{0x00}};
    first.writer().write_pcm(sample, sizeof(sample));
    second.writer().write_pcm(sample, sizeof(sample));
    first.publish();
    const auto first_size = std::filesystem::file_size(target);
    bool second_rejected = false;
    try {
        second.publish();
    }
    catch (const std::exception&) {
        second_rejected = true;
    }
    expect(second_rejected, "concurrent publication replaced the first WAV");
    expect(
        std::filesystem::file_size(target) == first_size,
        "first published WAV was modified by a concurrent writer");
}

void test_json_publication_collision_preserves_target() {
    DirectoryCleanup cleanup{test_directory()};
    const auto temporary = cleanup.path / "result.tmp";
    const auto target = cleanup.path / "result.json";
    qwen_tts_examples::AtomicWavOutput::reserve_temporary_path(temporary);
    {
        std::ofstream output(temporary, std::ios::binary | std::ios::trunc);
        output << "new";
    }
    {
        std::ofstream output(target, std::ios::binary | std::ios::trunc);
        output << "old";
    }
    bool rejected = false;
    try {
        qwen_tts_examples::AtomicWavOutput::publish_temporary_path(
            temporary, target);
    }
    catch (const std::exception&) {
        rejected = true;
    }
    expect(rejected, "JSON publication replaced a concurrent target");
    std::ifstream input(target, std::ios::binary);
    const std::string contents(
        (std::istreambuf_iterator<char>(input)), std::istreambuf_iterator<char>());
    expect(contents == "old", "JSON publication changed the existing target");
}

void test_unpublished_output_is_removed_and_publish_is_complete() {
    DirectoryCleanup cleanup{test_directory()};
    const auto target = cleanup.path / "published.wav";
    {
        qwen_tts_examples::AtomicWavOutput output(target.u8string(), 24'000, 1, 16);
        output.writer().write_pcm(
            reinterpret_cast<const std::byte*>("\x01\x00"), 2);
        expect(
            !std::filesystem::exists(target),
            "WAV target was visible before publication");
        output.publish();
    }
    expect(std::filesystem::exists(target), "published WAV target is missing");

    const auto discarded = cleanup.path / "discarded.wav";
    std::filesystem::path temporary;
    {
        qwen_tts_examples::AtomicWavOutput output(discarded.u8string(), 24'000, 1, 16);
        temporary = output.temporary_path();
    }
    expect(!std::filesystem::exists(discarded), "discarded WAV was published");
    expect(!std::filesystem::exists(temporary), "temporary WAV was not removed");
}

} // namespace

int main() {
    try {
        test_existing_target_is_preserved();
        test_aliasing_paths_are_rejected();
        test_existing_temporary_wav_is_preserved_after_failed_reservation();
        test_existing_temporary_json_is_preserved_after_failed_reservation();
        test_concurrent_outputs_preserve_first_publication();
        test_json_publication_collision_preserves_target();
        test_unpublished_output_is_removed_and_publish_is_complete();
        return 0;
    }
    catch (const std::exception& error) {
        return (std::fputs(error.what(), stderr), std::fputc('\n', stderr), 1);
    }
}
