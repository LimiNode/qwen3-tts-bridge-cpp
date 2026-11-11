#pragma once

#include <chrono>
#include <condition_variable>
#include <memory>
#include <mutex>
#include <string>

namespace qwen_tts_examples::play {

using qwen_tts_bridge::QwenTtsClient;
using qwen_tts_bridge::RequestId;
using qwen_tts_bridge::audio::AudioPostProcessorChain;

struct ActiveRequestState {
    std::mutex mutex;
    RequestId active_request_id = 0;
    RequestId next_request_id = 1;
    QwenTtsClient* active_client = nullptr;
    std::shared_ptr<AudioPostProcessorChain> processors;
};

struct OneShotState {
    std::mutex mutex;
    std::condition_variable condition;
    bool terminal = false;
    bool success = false;
    std::string message;
};

bool is_active_request(ActiveRequestState& state, RequestId request_id);
bool clear_active_request(ActiveRequestState& state, RequestId request_id);
bool complete_active_request(ActiveRequestState& state, RequestId request_id);
void mark_one_shot_terminal(OneShotState* state, bool success, std::string message = {});
bool wait_for_one_shot(OneShotState& state, std::chrono::milliseconds timeout);

} // namespace qwen_tts_examples::play
