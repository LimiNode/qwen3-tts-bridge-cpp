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
        test_unpublished_output_is_removed_and_publish_is_complete();
        return 0;
    }
    catch (const std::exception& error) {
        return (std::fputs(error.what(), stderr), std::fputc('\n', stderr), 1);
    }
}
