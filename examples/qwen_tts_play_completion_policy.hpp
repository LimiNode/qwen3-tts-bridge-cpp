#pragma once

#include <qwen_tts_bridge/client.hpp>

#include <optional>

namespace qwen_tts_examples::playback {

inline bool completion_has_natural_eos(
    const std::optional<qwen_tts_bridge::TtsCompletion>& completion) noexcept {
    return completion.has_value() &&
        completion->has_generation_trace &&
        completion->termination_reason == "eos" &&
        completion->hit_eos &&
        !completion->hit_max_seq_len &&
        !completion->hit_max_new_tokens;
}

} // namespace qwen_tts_examples::playback
