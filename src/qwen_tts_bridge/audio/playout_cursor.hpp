#pragma once

/// \file playout_cursor.hpp
/// \brief Cursor-relative PCM extraction for interruption shaping.

#include <cstdint>
#include <optional>
#include <vector>

#include "../client/client_types.hpp"

namespace qwen_tts_bridge::audio {

/// \struct PlayoutBuffer
/// \brief PCM buffer with its absolute position in the sink stream.
struct PlayoutBuffer {
    PcmChunk chunk;
    std::uint64_t start_frame = 0;
};

/// \brief Copies and fades the samples nearest a playback cursor.
///
/// The returned chunk starts at `cursor_frame` (or the first available frame)
/// and contains at most `fade_ms` of audio. Producer-ahead buffers after that
/// window are not included. This function is deterministic and does not know
/// about a physical sink; the sink supplies the measured cursor position.
/// \throws std::invalid_argument when buffers use incompatible PCM formats.
std::optional<PcmChunk> make_playout_cursor_fade(
    const std::vector<PlayoutBuffer>& buffers,
    std::uint64_t cursor_frame,
    std::uint32_t fade_ms);

} // namespace qwen_tts_bridge::audio
