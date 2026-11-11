#include <qwen_tts_bridge/audio.hpp>

#include "play.hpp"

#include <utility>

namespace qwen_tts_examples::play {

void mark_one_shot_terminal(
    OneShotState* state,
    bool success,
    std::string message) {
    if (state == nullptr) {
        return;
    }
    std::lock_guard<std::mutex> lock(state->mutex);
    if (state->terminal) {
        return;
    }
    state->terminal = true;
    state->success = success;
    state->message = std::move(message);
    state->condition.notify_all();
}

bool is_active_request(ActiveRequestState& state, RequestId request_id) {
    std::lock_guard<std::mutex> lock(state.mutex);
    return state.active_request_id == request_id;
}

bool clear_active_request(ActiveRequestState& state, RequestId request_id) {
    std::lock_guard<std::mutex> lock(state.mutex);
    if (state.active_request_id != request_id) {
        return false;
    }
    state.active_request_id = 0;
    state.active_client = nullptr;
    state.processors.reset();
    return true;
}

bool complete_active_request(ActiveRequestState& state, RequestId request_id) {
    std::lock_guard<std::mutex> lock(state.mutex);
    if (state.active_request_id != request_id) {
        return false;
    }
    state.active_request_id = 0;
    state.active_client = nullptr;
    state.processors.reset();
    return true;
}

bool wait_for_one_shot(OneShotState& state, std::chrono::milliseconds timeout) {
    std::unique_lock<std::mutex> lock(state.mutex);
    return state.condition.wait_for(lock, timeout, [&state] { return state.terminal; });
}

} // namespace qwen_tts_examples::play
