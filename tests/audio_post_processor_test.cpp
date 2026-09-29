#include <qwen_tts_bridge/audio.hpp>

#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <memory>
#include <string>
#include <utility>
#include <vector>

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
using qwen_tts_bridge::TtsCallbacks;
using qwen_tts_bridge::audio::AudioPostProcessorChain;
using qwen_tts_bridge::audio::AudioTerminalReason;
using qwen_tts_bridge::audio::IAudioPostProcessor;
using qwen_tts_bridge::audio::TerminalFadeOptions;
using qwen_tts_bridge::audio::TerminalFadePostProcessor;
using qwen_tts_bridge::audio::with_audio_post_processing;

PcmChunk constant_chunk(std::size_t samples, std::int16_t value = 1000) {
    PcmChunk chunk;
    chunk.request_id = 7;
    chunk.format.sample_format = "s16le";
    chunk.format.sample_rate = 1000;
    chunk.format.channels = 1;
    chunk.bytes.resize(samples * sizeof(value));
    for (std::size_t index = 0; index < samples; ++index) {
        std::memcpy(
            chunk.bytes.data() + index * sizeof(value),
            &value,
            sizeof(value));
    }
    return chunk;
}

std::vector<std::int16_t> samples_from(const std::vector<PcmChunk>& chunks) {
    std::vector<std::int16_t> samples;
    for (const PcmChunk& chunk : chunks) {
        CHECK(chunk.bytes.size() % sizeof(std::int16_t) == 0);
        for (std::size_t offset = 0; offset < chunk.bytes.size();
             offset += sizeof(std::int16_t)) {
            std::int16_t sample = 0;
            std::memcpy(&sample, chunk.bytes.data() + offset, sizeof(sample));
            samples.push_back(sample);
        }
    }
    return samples;
}

std::unique_ptr<TerminalFadePostProcessor> fade(
    std::uint32_t fade_ms = 10,
    std::uint32_t completion_silence_ms = 20,
    std::uint32_t cancellation_silence_ms = 0) {
    TerminalFadeOptions options;
    options.fade_ms = fade_ms;
    options.completion_silence_ms = completion_silence_ms;
    options.cancellation_silence_ms = cancellation_silence_ms;
    return std::make_unique<TerminalFadePostProcessor>(options);
}

void test_completion_fades_retained_tail_and_appends_silence() {
    AudioPostProcessorChain chain;
    chain.add(fade());

    auto output = chain.process(constant_chunk(20));
    CHECK(samples_from(output).size() == 10);
    auto final = chain.finish(AudioTerminalReason::Completed);
    const auto tail = samples_from(final);
    CHECK(tail.size() == 30);
    CHECK(tail.front() == 1000);
    CHECK(tail[9] == 0);
    CHECK(tail[10] == 0);
    CHECK(tail.back() == 0);
}

void test_cancellation_fades_without_default_silence() {
    AudioPostProcessorChain chain;
    chain.add(fade());

    static_cast<void>(chain.process(constant_chunk(20)));
    const auto tail = samples_from(chain.finish(AudioTerminalReason::Cancelled));
    CHECK(tail.size() == 10);
    CHECK(tail.front() == 1000);
    CHECK(tail.back() == 0);
    CHECK(chain.finish(AudioTerminalReason::Cancelled).empty());
    CHECK(chain.process(constant_chunk(1)).empty());
}

void test_error_releases_retained_audio_unchanged() {
    AudioPostProcessorChain chain;
    chain.add(fade());

    static_cast<void>(chain.process(constant_chunk(20)));
    const auto tail = samples_from(chain.finish(AudioTerminalReason::Error));
    CHECK(tail.size() == 10);
    for (const std::int16_t sample : tail) {
        CHECK(sample == 1000);
    }
}

class DuplicateProcessor final : public IAudioPostProcessor {
public:
    std::vector<PcmChunk> process(PcmChunk chunk) override {
        PcmChunk copy = chunk;
        return {std::move(chunk), std::move(copy)};
    }

    std::vector<PcmChunk> finish(AudioTerminalReason) override {
        return {};
    }

    void reset() noexcept override {
    }
};

void test_chain_supports_zero_one_or_many_chunks() {
    AudioPostProcessorChain chain;
    chain.add(std::make_unique<DuplicateProcessor>());
    const auto output = chain.process(constant_chunk(2));
    CHECK(output.size() == 2);
    CHECK(samples_from(output).size() == 4);
}

void test_callback_adapter_emits_tail_before_terminal_callback() {
    auto chain = std::make_shared<AudioPostProcessorChain>();
    chain->add(fade());
    std::vector<std::string> events;
    TtsCallbacks downstream;
    downstream.on_audio = [&events](const PcmChunk&) {
        events.push_back("audio");
    };
    downstream.on_cancelled = [&events]() {
        events.push_back("cancelled");
    };
    auto callbacks = with_audio_post_processing(chain, std::move(downstream));

    callbacks.on_audio(constant_chunk(20));
    callbacks.on_cancelled();
    CHECK(events.size() == 3);
    CHECK(events[0] == "audio");
    CHECK(events[1] == "audio");
    CHECK(events[2] == "cancelled");
}

} // namespace

int main() {
    test_completion_fades_retained_tail_and_appends_silence();
    test_cancellation_fades_without_default_silence();
    test_error_releases_retained_audio_unchanged();
    test_chain_supports_zero_one_or_many_chunks();
    test_callback_adapter_emits_tail_before_terminal_callback();
    return EXIT_SUCCESS;
}
