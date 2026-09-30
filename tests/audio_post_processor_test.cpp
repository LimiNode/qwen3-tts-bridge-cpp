#include <qwen_tts_bridge/audio.hpp>

#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <memory>
#include <stdexcept>
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

PcmChunk constant_chunk(
    std::size_t frames,
    std::int16_t value = 1000,
    std::uint32_t sample_rate = 1000,
    std::uint32_t channels = 1,
    qwen_tts_bridge::RequestId request_id = 7) {
    PcmChunk chunk;
    chunk.request_id = request_id;
    chunk.format.sample_format = "s16le";
    chunk.format.sample_rate = sample_rate;
    chunk.format.channels = channels;
    const std::size_t sample_count = frames * channels;
    chunk.bytes.resize(sample_count * sizeof(value));
    for (std::size_t index = 0; index < sample_count; ++index) {
        std::memcpy(
            chunk.bytes.data() + index * sizeof(value),
            &value,
            sizeof(value));
    }
    return chunk;
}

PcmChunk stereo_chunk(
    std::size_t frames,
    std::int16_t left,
    std::int16_t right) {
    PcmChunk chunk = constant_chunk(frames, 0, 1000, 2);
    for (std::size_t frame = 0; frame < frames; ++frame) {
        std::memcpy(
            chunk.bytes.data() + (frame * 2) * sizeof(std::int16_t),
            &left,
            sizeof(left));
        std::memcpy(
            chunk.bytes.data() + (frame * 2 + 1) * sizeof(std::int16_t),
            &right,
            sizeof(right));
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

void test_multiple_small_chunks_fill_one_fade_window() {
    AudioPostProcessorChain chain;
    chain.add(fade(10, 0, 0));

    CHECK(chain.process(constant_chunk(3)).empty());
    CHECK(chain.process(constant_chunk(3)).empty());
    CHECK(chain.process(constant_chunk(4)).empty());
    const auto tail = samples_from(chain.finish(AudioTerminalReason::Completed));
    CHECK(tail.size() == 10);
    CHECK(tail.front() == 1000);
    CHECK(tail.back() == 0);
}

void test_real_sample_rate_retains_exact_fifteen_milliseconds() {
    AudioPostProcessorChain chain;
    chain.add(fade(15, 0, 0));

    const auto output = chain.process(constant_chunk(720, 1000, 24000));
    CHECK(samples_from(output).size() == 360);
    const auto tail = samples_from(chain.finish(AudioTerminalReason::Completed));
    CHECK(tail.size() == 360);
    CHECK(tail.front() == 1000);
    CHECK(tail.back() == 0);
}

void test_stereo_fade_keeps_channels_aligned() {
    AudioPostProcessorChain chain;
    chain.add(fade(4, 0, 0));

    CHECK(chain.process(stereo_chunk(4, 1000, -2000)).empty());
    const auto samples = samples_from(
        chain.finish(AudioTerminalReason::Completed));
    CHECK(samples.size() == 8);
    CHECK(samples[0] == 1000);
    CHECK(samples[1] == -2000);
    CHECK(samples[6] == 0);
    CHECK(samples[7] == 0);
}

void test_zero_fade_streams_without_retaining_audio() {
    AudioPostProcessorChain chain;
    chain.add(fade(0, 0, 0));

    const auto output = chain.process(constant_chunk(5));
    CHECK(samples_from(output).size() == 5);
    CHECK(chain.finish(AudioTerminalReason::Completed).empty());
}

void test_reset_allows_reuse_for_another_stream() {
    AudioPostProcessorChain chain;
    chain.add(fade(2, 0, 0));

    static_cast<void>(chain.process(constant_chunk(2, 1000, 1000, 1, 7)));
    CHECK(samples_from(chain.finish(AudioTerminalReason::Completed)).size() == 2);
    chain.reset();
    static_cast<void>(chain.process(constant_chunk(2, 2000, 1000, 1, 8)));
    const auto second = samples_from(
        chain.finish(AudioTerminalReason::Completed));
    CHECK(second.size() == 2);
    CHECK(second.front() == 2000);
    CHECK(second.back() == 0);
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

class HoldOneChunkProcessor final : public IAudioPostProcessor {
public:
    std::vector<PcmChunk> process(PcmChunk chunk) override {
        std::vector<PcmChunk> output;
        if (pending_.bytes.size() != 0) {
            output.push_back(std::move(pending_));
        }
        pending_ = std::move(chunk);
        return output;
    }

    std::vector<PcmChunk> finish(AudioTerminalReason) override {
        if (pending_.bytes.empty()) {
            return {};
        }
        std::vector<PcmChunk> output;
        output.push_back(std::move(pending_));
        return output;
    }

    void reset() noexcept override {
        pending_ = {};
    }

private:
    PcmChunk pending_;
};

class ThrowingProcessor final : public IAudioPostProcessor {
public:
    explicit ThrowingProcessor(bool throw_on_finish)
        : throw_on_finish_(throw_on_finish) {
    }

    std::vector<PcmChunk> process(PcmChunk chunk) override {
        if (!throw_on_finish_) {
            throw std::runtime_error("process exploded");
        }
        return {std::move(chunk)};
    }

    std::vector<PcmChunk> finish(AudioTerminalReason) override {
        if (throw_on_finish_) {
            throw std::runtime_error("finish exploded");
        }
        return {};
    }

    void reset() noexcept override {
    }

private:
    bool throw_on_finish_ = false;
};

void test_chain_supports_zero_one_or_many_chunks() {
    AudioPostProcessorChain chain;
    chain.add(std::make_unique<DuplicateProcessor>());
    const auto output = chain.process(constant_chunk(2));
    CHECK(output.size() == 2);
    CHECK(samples_from(output).size() == 4);
}

void test_finish_flushes_two_buffering_processors_in_order() {
    AudioPostProcessorChain chain;
    chain.add(std::make_unique<HoldOneChunkProcessor>());
    chain.add(std::make_unique<HoldOneChunkProcessor>());

    CHECK(chain.process(constant_chunk(1, 100)).empty());
    CHECK(chain.process(constant_chunk(1, 200)).empty());
    const auto output = samples_from(chain.finish(AudioTerminalReason::Completed));
    CHECK(output.size() == 2);
    CHECK(output[0] == 100);
    CHECK(output[1] == 200);
}

void test_format_and_request_id_mismatch_fail_closed() {
    {
        AudioPostProcessorChain chain;
        chain.add(fade());
        static_cast<void>(chain.process(constant_chunk(1)));
        bool threw = false;
        try {
            static_cast<void>(chain.process(
                constant_chunk(1, 1000, 24000, 1, 7)));
        }
        catch (const std::runtime_error&) {
            threw = true;
        }
        CHECK(threw);
    }
    {
        AudioPostProcessorChain chain;
        chain.add(fade());
        static_cast<void>(chain.process(constant_chunk(1)));
        bool threw = false;
        try {
            static_cast<void>(chain.process(
                constant_chunk(1, 1000, 1000, 1, 8)));
        }
        catch (const std::runtime_error&) {
            threw = true;
        }
        CHECK(threw);
    }
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

void test_callback_adapter_allows_reentrant_terminal_request() {
    auto chain = std::make_shared<AudioPostProcessorChain>();
    chain->add(fade());
    std::vector<std::string> events;
    TtsCallbacks callbacks;
    bool requested_completion = false;
    TtsCallbacks downstream;
    downstream.on_audio = [&events, &callbacks, &requested_completion](
                              const PcmChunk&) {
        events.push_back("audio");
        if (!requested_completion) {
            requested_completion = true;
            callbacks.on_completed();
        }
    };
    downstream.on_completed = [&events]() {
        events.push_back("completed");
    };
    callbacks = with_audio_post_processing(chain, std::move(downstream));

    callbacks.on_audio(constant_chunk(20));
    CHECK(events.size() == 3);
    CHECK(events[0] == "audio");
    CHECK(events[1] == "audio");
    CHECK(events[2] == "completed");
}

void test_callback_adapter_converts_process_exception_to_one_error() {
    auto chain = std::make_shared<AudioPostProcessorChain>();
    chain->add(std::make_unique<ThrowingProcessor>(false));
    std::vector<PcmChunk> audio;
    std::vector<qwen_tts_bridge::TtsError> errors;
    std::size_t completed = 0;
    std::size_t cancelled = 0;
    TtsCallbacks downstream;
    downstream.on_audio = [&audio](const PcmChunk& chunk) {
        audio.push_back(chunk);
    };
    downstream.on_completed = [&completed]() {
        ++completed;
    };
    downstream.on_cancelled = [&cancelled]() {
        ++cancelled;
    };
    downstream.on_error = [&errors](const qwen_tts_bridge::TtsError& error) {
        errors.push_back(error);
    };
    auto callbacks = with_audio_post_processing(chain, std::move(downstream));

    callbacks.on_audio(constant_chunk(1));
    callbacks.on_audio(constant_chunk(1));
    callbacks.on_completed();
    callbacks.on_cancelled();

    CHECK(audio.empty());
    CHECK(completed == 0);
    CHECK(cancelled == 0);
    CHECK(errors.size() == 1);
    CHECK(errors[0].request_id == 7);
    CHECK(errors[0].category == "client_error");
    CHECK(errors[0].code == "audio_post_processing_failed");
    CHECK(errors[0].message.find("process exploded") != std::string::npos);
}

void test_callback_adapter_converts_finish_exception_to_one_error() {
    auto chain = std::make_shared<AudioPostProcessorChain>();
    chain->add(std::make_unique<ThrowingProcessor>(true));
    std::vector<qwen_tts_bridge::TtsError> errors;
    std::size_t completed = 0;
    TtsCallbacks downstream;
    downstream.on_completed = [&completed]() {
        ++completed;
    };
    downstream.on_error = [&errors](const qwen_tts_bridge::TtsError& error) {
        errors.push_back(error);
    };
    auto callbacks = with_audio_post_processing(chain, std::move(downstream));

    callbacks.on_audio(constant_chunk(1));
    callbacks.on_completed();
    callbacks.on_completed();

    CHECK(completed == 0);
    CHECK(errors.size() == 1);
    CHECK(errors[0].request_id == 7);
    CHECK(errors[0].code == "audio_post_processing_failed");
    CHECK(errors[0].message.find("finish exploded") != std::string::npos);
}

void test_callback_adapter_reports_format_mismatch() {
    auto chain = std::make_shared<AudioPostProcessorChain>();
    chain->add(fade());
    std::vector<qwen_tts_bridge::TtsError> errors;
    TtsCallbacks downstream;
    downstream.on_error = [&errors](const qwen_tts_bridge::TtsError& error) {
        errors.push_back(error);
    };
    auto callbacks = with_audio_post_processing(chain, std::move(downstream));

    callbacks.on_audio(constant_chunk(1));
    callbacks.on_audio(constant_chunk(1, 1000, 24000));

    CHECK(errors.size() == 1);
    CHECK(errors[0].message.find("audio format changed") != std::string::npos);
}

} // namespace

int main() {
    test_completion_fades_retained_tail_and_appends_silence();
    test_cancellation_fades_without_default_silence();
    test_error_releases_retained_audio_unchanged();
    test_multiple_small_chunks_fill_one_fade_window();
    test_real_sample_rate_retains_exact_fifteen_milliseconds();
    test_stereo_fade_keeps_channels_aligned();
    test_zero_fade_streams_without_retaining_audio();
    test_reset_allows_reuse_for_another_stream();
    test_chain_supports_zero_one_or_many_chunks();
    test_finish_flushes_two_buffering_processors_in_order();
    test_format_and_request_id_mismatch_fail_closed();
    test_callback_adapter_emits_tail_before_terminal_callback();
    test_callback_adapter_allows_reentrant_terminal_request();
    test_callback_adapter_converts_process_exception_to_one_error();
    test_callback_adapter_converts_finish_exception_to_one_error();
    test_callback_adapter_reports_format_mismatch();
    return EXIT_SUCCESS;
}
