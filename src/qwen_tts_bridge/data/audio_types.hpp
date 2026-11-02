#pragma once

/// \file audio_types.hpp
/// \brief Backend-neutral PCM value types shared by bridge domains.

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

#include <qwen_tts_bridge/data/protocol_types.hpp>

namespace qwen_tts_bridge {

/// \struct AudioFormat
/// \brief PCM format announced, requested, or carried by an audio chunk.
struct AudioFormat {
    std::string sample_format = "s16le"; ///< PCM sample encoding.
    std::uint32_t sample_rate = 24000; ///< PCM samples per second.
    std::uint32_t channels = 1; ///< Number of interleaved PCM channels.
};

/// \struct PcmChunk
/// \brief PCM audio bytes routed to a request callback.
struct PcmChunk {
    RequestId request_id = 0; ///< Request that produced this audio.
    AudioFormat format; ///< PCM format for the chunk.
    std::vector<std::byte> bytes; ///< Raw PCM bytes.
    std::uint64_t first_sample = 0; ///< First interleaved sample-frame position.
    std::uint32_t sample_count = 0; ///< Number of sample frames in bytes.
};

/// \struct SpeechTimingChunk
/// \brief Sample-addressed sideband event for downstream speech analysis.
struct SpeechTimingChunk {
    RequestId request_id = 0; ///< Utterance/request that produced this timing.
    std::uint64_t first_sample = 0; ///< First sample-frame position.
    std::uint32_t sample_count = 0; ///< Number of sample frames in the chunk.
    std::uint32_t sample_rate = 0; ///< Samples per second for the timeline.
};

} // namespace qwen_tts_bridge
