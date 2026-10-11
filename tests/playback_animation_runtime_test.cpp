#include <qwen_tts_bridge/integration/speech_animation/PlaybackAnimationRuntime.hpp>

#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <string>
#include <vector>

#define CHECK(expr)                                                            \
    do {                                                                       \
        if (!(expr)) {                                                         \
            std::cerr << "CHECK failed: " #expr << " at " << __FILE__ << ':' \
                      << __LINE__ << '\n';                                     \
            std::exit(EXIT_FAILURE);                                           \
        }                                                                        \
    } while (false)

namespace {

using qwen_tts_bridge::AudioFormat;
using qwen_tts_bridge::PcmChunk;
using qwen_tts_bridge::TtsCallbacks;
using qwen_tts_bridge::speech_animation::PlaybackAnimationRuntime;
using speech_animation::integration::PlaybackCursorSnapshot;
using speech_animation::integration::PlaybackSelectionStatus;
using speech_animation::integration::PipelineConfig;

PcmChunk pcm_chunk(std::uint64_t request_id, std::uint64_t first_sample) {
    PcmChunk chunk;
    chunk.request_id = request_id;
    chunk.format = AudioFormat{"s16le", 24000, 1};
    chunk.first_sample = first_sample;
    chunk.sample_count = 2400;
    chunk.bytes.resize(chunk.sample_count * sizeof(std::int16_t));
    for (std::uint32_t index = 0; index < chunk.sample_count; ++index) {
        const auto sample = static_cast<std::int16_t>(
            (index / 120) % 2 == 0 ? 12000 : 24000);
        chunk.bytes[index * 2] = static_cast<std::byte>(sample & 0xff);
        chunk.bytes[index * 2 + 1] =
            static_cast<std::byte>((sample >> 8) & 0xff);
    }
    return chunk;
}

void test_selection_uses_sample_cursor_and_resets_stale_epoch() {
    PlaybackCursorSnapshot snapshot;
    snapshot.playback_epoch = 3;
    snapshot.request_id = 17;
    snapshot.sample_rate = 24000;
    snapshot.position_available = true;

    PlaybackAnimationRuntime runtime([&snapshot] { return snapshot; });
    runtime.begin(3, 17, 24000);

    auto callbacks = runtime.make_callbacks({}, false);
    callbacks.on_audio(pcm_chunk(17, 0));
    runtime.push_audio(pcm_chunk(17, 0));
    const auto first = runtime.tick();
    CHECK(first.status == PlaybackSelectionStatus::Selected);
    CHECK(first.request_id == 17);
    CHECK(first.sample_rate == 24000);
    CHECK(first.cue_sample_count != 0);

    snapshot.utterance_sample = first.cue_first_sample + first.cue_sample_count - 1;
    const auto later = runtime.tick();
    CHECK(later.status == PlaybackSelectionStatus::Selected);
    CHECK(later.cursor_sample == snapshot.utterance_sample);

    callbacks.on_completed();
}

void test_degradation_is_reported_without_rewriting_playback() {
    PlaybackCursorSnapshot snapshot;
    snapshot.playback_epoch = 4;
    snapshot.request_id = 31;
    snapshot.sample_rate = 24000;
    snapshot.position_available = true;
    std::vector<std::string> diagnostics;
    PipelineConfig config;
    config.queue_capacity = 1;
    PlaybackAnimationRuntime runtime(
        [&snapshot] { return snapshot; },
        {},
        [&diagnostics](const PlaybackAnimationRuntime::AdapterDiagnostic& diagnostic) {
            diagnostics.push_back(diagnostic.code);
        },
        config);
    runtime.begin(4, 31, 24000);
    runtime.push_audio(pcm_chunk(31, 0));
    runtime.push_audio(pcm_chunk(31, 2400));
    CHECK(diagnostics.size() == 1);
    CHECK(diagnostics.front() == "speech_animation_queue_full");
}

void test_unavailable_and_stale_snapshots_are_neutral() {
    PlaybackCursorSnapshot snapshot;
    snapshot.playback_epoch = 8;
    snapshot.request_id = 21;
    snapshot.sample_rate = 24000;

    PlaybackAnimationRuntime runtime([&snapshot] { return snapshot; });
    runtime.begin(8, 21, 24000);
    auto callbacks = runtime.make_callbacks();
    callbacks.on_audio(pcm_chunk(21, 0));

    snapshot.position_available = false;
    CHECK(runtime.tick().status == PlaybackSelectionStatus::CursorUnavailable);

    snapshot.position_available = true;
    snapshot.playback_epoch = 7;
    CHECK(runtime.tick().status == PlaybackSelectionStatus::StaleEpoch);

    runtime.invalidate(9);
    snapshot.playback_epoch = 9;
    snapshot.request_id = 21;
    CHECK(runtime.tick().status == PlaybackSelectionStatus::StaleRequest);
}

} // namespace

int main() {
    test_selection_uses_sample_cursor_and_resets_stale_epoch();
    test_degradation_is_reported_without_rewriting_playback();
    test_unavailable_and_stale_snapshots_are_neutral();
    return EXIT_SUCCESS;
}
