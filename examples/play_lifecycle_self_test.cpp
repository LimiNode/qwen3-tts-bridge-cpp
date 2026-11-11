#include <qwen_tts_bridge/audio.hpp>

#include "play.hpp"

#include <stdexcept>
#include <thread>

namespace qwen_tts_examples::play {

using qwen_tts_bridge::PcmChunk;
using qwen_tts_bridge::playback::WaveOutPlayer;
using qwen_tts_bridge::playback::PlaybackSinkMode;
using qwen_tts_bridge::playback::MockPlaybackFailureStage;

int run_playback_lifecycle_self_test() {
    WaveOutPlayer player(PlaybackSinkMode::Mock);
    const auto initial_epoch = player.playback_epoch();

    std::mutex reset_gate_mutex;
    std::condition_variable reset_gate_condition;
    bool reset_started = false;
    bool release_reset = false;
    player.set_reset_wait_hook_for_test([&] {
        std::unique_lock<std::mutex> lock(reset_gate_mutex);
        reset_started = true;
        reset_gate_condition.notify_all();
        reset_gate_condition.wait(lock, [&] { return release_reset; });
    });

    bool stale_reset_started = false;
    std::thread stale_reset([&] {
        stale_reset_started = player.reset_if_epoch(initial_epoch);
    });
    {
        std::unique_lock<std::mutex> lock(reset_gate_mutex);
        reset_gate_condition.wait(lock, [&] { return reset_started; });
    }

    const auto replacement_epoch = player.reset();
    PcmChunk replacement_chunk;
    replacement_chunk.request_id = 43;
    replacement_chunk.format.sample_format = "s16le";
    replacement_chunk.format.sample_rate = 24000;
    replacement_chunk.format.channels = 1;
    replacement_chunk.bytes = {std::byte{0}, std::byte{0}};
    replacement_chunk.sample_count = 1;
    player.enqueue(replacement_epoch, replacement_chunk);

    {
        std::lock_guard<std::mutex> lock(reset_gate_mutex);
        release_reset = true;
    }
    reset_gate_condition.notify_all();
    stale_reset.join();
    if (!stale_reset_started ||
        player.playback_epoch() != replacement_epoch ||
        player.buffered_chunk_count_for_test() != 1) {
        throw std::runtime_error("stale playback reset destroyed replacement playback");
    }

    WaveOutPlayer terminal_player(PlaybackSinkMode::Mock);
    ActiveRequestState terminal_state;
    {
        std::lock_guard<std::mutex> lock(terminal_state.mutex);
        terminal_state.active_request_id = 41;
    }
    const auto terminal_epoch = terminal_player.playback_epoch();
    if (!clear_active_request(terminal_state, 41)) {
        throw std::runtime_error("failed to claim terminal request in self-test");
    }
    const auto terminal_replacement_epoch = terminal_player.reset();
    terminal_player.enqueue(terminal_replacement_epoch, replacement_chunk);
    if (terminal_player.reset_if_epoch(terminal_epoch) ||
        terminal_player.interrupt_with_fade_if_epoch(terminal_epoch, 0, 41).has_value() ||
        terminal_player.buffered_chunk_count_for_test() != 1) {
        throw std::runtime_error("stale error/cancel path destroyed replacement playback");
    }

    ActiveRequestState state;
    {
        std::lock_guard<std::mutex> lock(state.mutex);
        state.active_request_id = 42;
    }
    std::mutex gate_mutex;
    std::condition_variable gate_condition;
    bool completion_released = false;
    bool completion_won = false;
    std::thread completion([&] {
        std::unique_lock<std::mutex> lock(gate_mutex);
        gate_condition.wait(lock, [&] { return completion_released; });
        completion_won = complete_active_request(state, 42);
    });
    clear_active_request(state, 42);
    {
        std::lock_guard<std::mutex> lock(gate_mutex);
        completion_released = true;
    }
    gate_condition.notify_all();
    completion.join();
    if (completion_won) {
        throw std::runtime_error("stale completion claimed success after cancellation");
    }

    {
        std::lock_guard<std::mutex> lock(state.mutex);
        state.active_request_id = 43;
    }
    if (!complete_active_request(state, 43) ||
        complete_active_request(state, 43)) {
        throw std::runtime_error("active completion transition is not exactly once");
    }

    OneShotState worker_error_state;
    mark_one_shot_terminal(&worker_error_state, false, "worker error");
    mark_one_shot_terminal(&worker_error_state, true, "late completion");
    {
        std::lock_guard<std::mutex> lock(worker_error_state.mutex);
        if (!worker_error_state.terminal || worker_error_state.success ||
            worker_error_state.message != "worker error") {
            throw std::runtime_error(
                "worker error terminalization was not preserved exactly once");
        }
    }

    OneShotState cancelled_state;
    mark_one_shot_terminal(&cancelled_state, false, "request cancelled");
    mark_one_shot_terminal(&cancelled_state, true, "late completion");
    {
        std::lock_guard<std::mutex> lock(cancelled_state.mutex);
        if (!cancelled_state.terminal || cancelled_state.success ||
            cancelled_state.message != "request cancelled") {
            throw std::runtime_error(
                "cancellation terminalization was not preserved exactly once");
        }
    }

    const auto assert_injected_submission_failure = [](
        MockPlaybackFailureStage stage,
        const char* expected_operation) {
        WaveOutPlayer failure_player(
            PlaybackSinkMode::Mock,
            nullptr,
            1,
            0,
            stage);
        PcmChunk chunk;
        chunk.request_id = 44;
        chunk.format.sample_format = "s16le";
        chunk.format.sample_rate = 24000;
        chunk.format.channels = 1;
        chunk.bytes = {std::byte{0}, std::byte{0}};
        chunk.sample_count = 1;
        bool failed = false;
        try {
            failure_player.enqueue(failure_player.playback_epoch(), chunk);
        }
        catch (const std::runtime_error& error) {
            failed = std::string(error.what()).find(expected_operation) != std::string::npos;
        }
        if (!failed || failure_player.next_stream_frame_for_test() != 0 ||
            failure_player.buffered_chunk_count_for_test() != 1) {
            throw std::runtime_error("submission failure changed the committed playback frontier");
        }
        const auto retry_epoch = failure_player.reset();
        failure_player.enqueue(retry_epoch, chunk);
        if (failure_player.next_stream_frame_for_test() != 1 ||
            failure_player.buffered_chunk_count_for_test() != 1) {
            throw std::runtime_error("submission retry did not recover a clean playback queue");
        }
    };
    assert_injected_submission_failure(
        MockPlaybackFailureStage::Prepare,
        "waveOutPrepareHeader");
    assert_injected_submission_failure(
        MockPlaybackFailureStage::Write,
        "waveOutWrite");

    WaveOutPlayer partial_player(
        PlaybackSinkMode::Mock,
        nullptr,
        2,
        1,
        MockPlaybackFailureStage::Write);
    const auto partial_epoch = partial_player.playback_epoch();
    partial_player.enqueue(partial_epoch, replacement_chunk);
    bool partial_failed = false;
    try {
        partial_player.enqueue(partial_epoch, replacement_chunk);
    }
    catch (const std::runtime_error& error) {
        partial_failed = std::string(error.what()).find("waveOutWrite") != std::string::npos;
    }
    if (!partial_failed || partial_player.next_stream_frame_for_test() != 1 ||
        partial_player.buffered_chunk_count_for_test() != 2) {
        throw std::runtime_error("partial submission did not preserve committed buffers");
    }
    const auto partial_retry_epoch = partial_player.reset();
    partial_player.enqueue(partial_retry_epoch, replacement_chunk);
    partial_player.enqueue(partial_retry_epoch, replacement_chunk);
    if (partial_player.next_stream_frame_for_test() != 2 ||
        partial_player.buffered_chunk_count_for_test() != 2) {
        throw std::runtime_error("partial submission cleanup left stale buffer ownership");
    }
    return 0;
}

} // namespace qwen_tts_examples::play
