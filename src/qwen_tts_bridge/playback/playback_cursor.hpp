#pragma once

/// \file playback_cursor.hpp
/// \brief Neutral sample-clock snapshot supplied by a playback sink.

#include <cstdint>

namespace qwen_tts_bridge::playback {

using qwen_tts_bridge::RequestId;

/// \struct PlaybackCursorSnapshot
/// \brief Physical playback position on the player-owned sample clock.
///
/// A sink may report an unavailable position while it is stopped, empty, or
/// between device callbacks. Consumers must treat an unavailable snapshot as
/// neutral rather than estimating a position from callback arrival time.
struct PlaybackCursorSnapshot {
    std::uint64_t playback_epoch = 0;
    RequestId request_id = 0;
    std::uint64_t utterance_sample = 0;
    std::uint32_t sample_rate = 0;
    bool position_available = false;
};

} // namespace qwen_tts_bridge::playback
