#include <qwen_tts_bridge/playback/winmm_playback.hpp>

#include <cstddef>
#include <cstdint>
#include <exception>
#include <iostream>
#include <optional>
#include <vector>

namespace {

using qwen_tts_bridge::AudioFormat;
using qwen_tts_bridge::PcmChunk;
using qwen_tts_bridge::playback::MockPlaybackFailureStage;
using qwen_tts_bridge::playback::PlaybackSinkMode;
using qwen_tts_bridge::playback::WaveOutPlayer;

PcmChunk make_chunk(std::uint64_t request_id, std::size_t frames) {
    PcmChunk chunk;
    chunk.request_id = request_id;
    chunk.first_sample = 0;
    chunk.format = AudioFormat{"s16le", 24000, 1};
    chunk.bytes.resize(frames * sizeof(std::int16_t));
    return chunk;
}

bool check(bool condition, const char* message) {
    if (!condition) {
        std::cerr << message << '\n';
    }
    return condition;
}

} // namespace

int main() {
    try {
        WaveOutPlayer player(PlaybackSinkMode::Mock);
        const auto epoch = player.playback_epoch();
        player.enqueue(epoch, make_chunk(1, 240));
        if (!check(player.buffered_chunk_count_for_test() == 1,
                   "mock playback did not retain submitted buffer") ||
            !check(player.next_stream_frame_for_test() == 240,
                   "mock playback cursor did not advance")) {
            return 1;
        }
        const auto next_epoch = player.reset();
        if (!check(next_epoch != epoch, "reset did not advance playback epoch") ||
            !check(player.buffered_chunk_count_for_test() == 0,
                   "reset did not clear playback buffers")) {
            return 1;
        }

        WaveOutPlayer prepare_failure(
            PlaybackSinkMode::Mock,
            nullptr,
            1,
            0,
            MockPlaybackFailureStage::Prepare);
        bool prepare_threw = false;
        try {
            prepare_failure.enqueue(prepare_failure.playback_epoch(), make_chunk(2, 120));
        }
        catch (const std::exception&) {
            prepare_threw = true;
        }
        if (!check(prepare_threw, "prepare fault injection did not fail") ||
            !check(prepare_failure.buffered_chunk_count_for_test() == 1,
                   "prepare failure lost pending buffer ownership")) {
            return 1;
        }

        WaveOutPlayer write_failure(
            PlaybackSinkMode::Mock,
            nullptr,
            1,
            0,
            MockPlaybackFailureStage::Write);
        bool write_threw = false;
        try {
            write_failure.enqueue(write_failure.playback_epoch(), make_chunk(3, 120));
        }
        catch (const std::exception&) {
            write_threw = true;
        }
        if (!check(write_threw, "write fault injection did not fail") ||
            !check(write_failure.buffered_chunk_count_for_test() == 1,
                   "write failure lost pending buffer ownership")) {
            return 1;
        }
    }
    catch (const std::exception& error) {
        std::cerr << "unexpected playback test failure: " << error.what() << '\n';
        return 1;
    }
    return 0;
}
