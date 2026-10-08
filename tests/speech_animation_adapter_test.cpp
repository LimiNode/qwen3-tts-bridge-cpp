#include <qwen_tts_bridge/integration/speech_animation/SpeechAnimationAdapter.hpp>

#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <memory>
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
using qwen_tts_bridge::speech_animation::SpeechAnimationAdapter;
using speech_animation::integration::PipelineConfig;
using speech_animation::integration::QueuePushResult;

PcmChunk pcm_chunk(std::uint64_t request_id, std::uint64_t first_sample) {
    PcmChunk chunk;
    chunk.request_id = request_id;
    chunk.format = AudioFormat{"s16le", 24000, 1};
    chunk.first_sample = first_sample;
    chunk.sample_count = 8;
    chunk.bytes.resize(chunk.sample_count * sizeof(std::int16_t));
    for (std::uint32_t index = 0; index < chunk.sample_count; ++index) {
        const auto sample = static_cast<std::int16_t>(index < 4 ? 12000 : 24000);
        std::memcpy(
            chunk.bytes.data() + index * sizeof(sample),
            &sample,
            sizeof(sample));
    }
    return chunk;
}

void test_audio_and_completion_mapping() {
    PipelineConfig config;
    config.queue_capacity = 2;
    config.analyzer.output_hop_samples = 8;
    config.analyzer.energy_attack_ms = 0.0F;
    config.analyzer.energy_release_ms = 0.0F;
    config.analyzer.mouth_attack_ms = 0.0F;
    config.analyzer.mouth_release_ms = 0.0F;
    config.analyzer.normalizer_attack_ms = 0.0F;
    config.analyzer.normalizer_release_ms = 0.0F;

    auto pipeline = std::make_shared<SpeechAnimationAdapter::Pipeline>(config);
    std::vector<SpeechAnimationAdapter::Receipt> observed;
    SpeechAnimationAdapter adapter(
        pipeline,
        [&observed](const SpeechAnimationAdapter::Receipt& receipt) {
            observed.push_back(receipt);
        });
    CHECK(adapter.begin(7, 0, 24000) == QueuePushResult::Accepted);

    std::size_t downstream_audio = 0;
    TtsCallbacks downstream;
    downstream.on_audio = [&downstream_audio](const PcmChunk&) {
        ++downstream_audio;
    };
    auto callbacks = adapter.make_callbacks(std::move(downstream));
    const auto input = pcm_chunk(7, 0);
    callbacks.on_audio(input);
    CHECK(downstream_audio == 1);

    const auto audio_receipts = adapter.process_available();
    CHECK(audio_receipts.size() == 1);
    CHECK(audio_receipts.front().request_id == 7);
    CHECK(audio_receipts.front().input_first_sample == 0);
    CHECK(audio_receipts.front().input_sample_count == 8);
    CHECK(audio_receipts.front().output_first_sample == 0);
    CHECK(audio_receipts.front().output_sample_count == 8);
    CHECK(!audio_receipts.front().terminal);

    callbacks.on_completed();
    const auto terminal_receipts = adapter.process_available();
    CHECK(terminal_receipts.size() == 1);
    CHECK(terminal_receipts.front().terminal);
    CHECK(terminal_receipts.front().output_first_sample == 8);
    CHECK(observed.size() == 2);
}

void test_cancel_without_audio_maps_to_terminal_receipt() {
    auto pipeline = std::make_shared<SpeechAnimationAdapter::Pipeline>();
    SpeechAnimationAdapter adapter(pipeline);
    CHECK(adapter.begin(9, 100, 24000) == QueuePushResult::Accepted);

    auto callbacks = adapter.make_callbacks();
    callbacks.on_cancelled();
    const auto receipts = adapter.process_available();
    CHECK(receipts.size() == 1);
    CHECK(receipts.front().terminal);
    CHECK(receipts.front().terminal_state ==
          speech_animation::integration::PipelineState::Cancelled);
    CHECK(receipts.front().output_first_sample == 100);
}

} // namespace

int main() {
    test_audio_and_completion_mapping();
    test_cancel_without_audio_maps_to_terminal_receipt();
    return EXIT_SUCCESS;
}
