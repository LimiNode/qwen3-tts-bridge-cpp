#include <qwen_tts_bridge/audio.hpp>

#include <chrono>
#include <cstddef>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iostream>
#include <mutex>
#include <string>
#include <vector>

#ifndef QWEN_TTS_BRIDGE_TEST_OUTPUT_DIR
#define QWEN_TTS_BRIDGE_TEST_OUTPUT_DIR "build/audio-test-output"
#endif

#define CHECK(expr)                                                            \
    do {                                                                       \
        if (!(expr)) {                                                         \
            std::cerr << "CHECK failed: " #expr << " at " << __FILE__ << ':'  \
                      << __LINE__ << '\n';                                     \
            std::exit(EXIT_FAILURE);                                           \
        }                                                                      \
    } while (false)

namespace {

using qwen_tts_bridge::AudioFormat;
using qwen_tts_bridge::PcmChunk;
using qwen_tts_bridge::audio::SaveWavState;
using qwen_tts_bridge::audio::AudioTailOptions;
using qwen_tts_bridge::audio::WavWriter;
using qwen_tts_bridge::audio::make_save_wav_callbacks;
using qwen_tts_bridge::audio::wait_for_save_wav_terminal;

std::string output_path(const std::string& file_name) {
    return std::string(QWEN_TTS_BRIDGE_TEST_OUTPUT_DIR) + "/" + file_name;
}

std::vector<std::byte> pcm_bytes(std::size_t size) {
    return std::vector<std::byte>(size, std::byte{0});
}

std::vector<std::int16_t> read_wav_samples(const std::string& path) {
    std::ifstream input(path, std::ios::binary);
    input.seekg(44, std::ios::beg);
    std::vector<std::int16_t> samples;
    std::int16_t sample = 0;
    while (input.read(reinterpret_cast<char*>(&sample), sizeof(sample))) {
        samples.push_back(sample);
    }
    return samples;
}

void remove_file(const std::string& path) {
    std::remove(path.c_str());
}

void test_audio_format_mismatch_marks_terminal_error() {
    const std::string path = output_path("save_wav_callbacks_mismatch.wav");
    remove_file(path);

    SaveWavState state;
    AudioFormat expected;
    WavWriter writer(path, expected.sample_rate, 1, 16);
    auto callbacks = make_save_wav_callbacks(state, writer, expected);

    PcmChunk chunk;
    chunk.format = expected;
    chunk.format.sample_rate = expected.sample_rate * 2;
    chunk.bytes = pcm_bytes(2);

    callbacks.on_audio(chunk);

    CHECK(wait_for_save_wav_terminal(state, std::chrono::seconds(1)));

    {
        std::lock_guard<std::mutex> lock(state.mutex);
        CHECK(state.terminal);
        CHECK(!state.success);
        CHECK(state.audio_chunks == 0);
        CHECK(state.audio_bytes == 0);
        CHECK(state.message.find("unexpected PCM format") != std::string::npos);
    }

    writer.close();
    remove_file(path);
}

void test_valid_audio_then_completed_marks_success() {
    const std::string path = output_path("save_wav_callbacks_success.wav");
    remove_file(path);

    SaveWavState state;
    AudioFormat expected;
    WavWriter writer(path, expected.sample_rate, 1, 16);
    auto callbacks = make_save_wav_callbacks(state, writer, expected);

    PcmChunk chunk;
    chunk.format = expected;
    chunk.bytes = pcm_bytes(4);

    callbacks.on_audio(chunk);
    callbacks.on_completed();

    CHECK(wait_for_save_wav_terminal(state, std::chrono::seconds(1)));

    {
        std::lock_guard<std::mutex> lock(state.mutex);
        CHECK(state.terminal);
        CHECK(state.success);
        CHECK(state.message == "completed");
        CHECK(state.audio_chunks == 1);
        CHECK(state.audio_bytes == chunk.bytes.size());
    }
    CHECK(writer.data_size() == chunk.bytes.size());

    remove_file(path);
}

void test_optional_tail_fades_completion_and_appends_silence() {
    const std::string path = output_path("save_wav_callbacks_tail.wav");
    remove_file(path);

    SaveWavState state;
    AudioFormat expected;
    expected.sample_rate = 1000;
    WavWriter writer(path, expected.sample_rate, 1, 16);
    AudioTailOptions options;
    options.enabled = true;
    options.fade_ms = 10;
    options.completion_silence_ms = 20;
    auto callbacks = make_save_wav_callbacks(state, writer, expected, options);

    PcmChunk chunk;
    chunk.format = expected;
    chunk.bytes.resize(20 * sizeof(std::int16_t));
    for (std::size_t i = 0; i < 20; ++i) {
        const std::int16_t sample = 1000;
        std::memcpy(chunk.bytes.data() + i * sizeof(sample), &sample, sizeof(sample));
    }

    callbacks.on_audio(chunk);
    callbacks.on_completed();

    CHECK(wait_for_save_wav_terminal(state, std::chrono::seconds(1)));
    CHECK(state.success);
    CHECK(writer.data_size() == 40 * sizeof(std::int16_t));
    const auto samples = read_wav_samples(path);
    CHECK(samples.size() == 40);
    CHECK(samples[9] == 1000);
    CHECK(samples[10] > 0);
    CHECK(samples[19] == 0);
    CHECK(samples[20] == 0);
    CHECK(samples[39] == 0);
    remove_file(path);
}

void test_optional_tail_fades_cancellation_without_default_pause() {
    const std::string path = output_path("save_wav_callbacks_cancel_tail.wav");
    remove_file(path);

    SaveWavState state;
    AudioFormat expected;
    expected.sample_rate = 1000;
    WavWriter writer(path, expected.sample_rate, 1, 16);
    AudioTailOptions options;
    options.enabled = true;
    options.fade_ms = 10;
    auto callbacks = make_save_wav_callbacks(state, writer, expected, options);

    PcmChunk chunk;
    chunk.format = expected;
    chunk.bytes.resize(20 * sizeof(std::int16_t));
    for (std::size_t i = 0; i < 20; ++i) {
        const std::int16_t sample = 1000;
        std::memcpy(chunk.bytes.data() + i * sizeof(sample), &sample, sizeof(sample));
    }

    callbacks.on_audio(chunk);
    callbacks.on_cancelled();

    CHECK(wait_for_save_wav_terminal(state, std::chrono::seconds(1)));
    CHECK(!state.success);
    CHECK(writer.data_size() == 20 * sizeof(std::int16_t));
    const auto samples = read_wav_samples(path);
    CHECK(samples.size() == 20);
    CHECK(samples[9] == 1000);
    CHECK(samples[19] == 0);
    remove_file(path);
}

} // namespace

int main() {
    test_audio_format_mismatch_marks_terminal_error();
    test_valid_audio_then_completed_marks_success();
    test_optional_tail_fades_completion_and_appends_silence();
    test_optional_tail_fades_cancellation_without_default_pause();
    return EXIT_SUCCESS;
}
