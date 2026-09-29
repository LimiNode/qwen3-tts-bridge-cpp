#pragma once

/// \file terminal_fade_post_processor.hpp
/// \brief Configurable terminal fade and silence PCM post-processor.

#include <cstddef>
#include <cstdint>
#include <optional>
#include <vector>

#include "post_processor.hpp"

namespace qwen_tts_bridge::audio {

/// \struct TerminalFadeOptions
/// \brief Terminal shaping durations for successful and cancelled streams.
struct TerminalFadeOptions {
    std::uint32_t fade_ms = 15; ///< Fade duration for completion and cancellation.
    std::uint32_t completion_silence_ms = 85; ///< Silence after normal completion.
    std::uint32_t cancellation_silence_ms = 0; ///< Silence after cancellation.
};

/// \class TerminalFadePostProcessor
/// \brief Retains a bounded PCM tail and fades it at a terminal boundary.
///
/// The current implementation accepts interleaved s16le PCM. On error it
/// releases retained PCM unchanged and appends no silence.
class TerminalFadePostProcessor final : public IAudioPostProcessor {
public:
    explicit TerminalFadePostProcessor(TerminalFadeOptions options = {});

    std::vector<PcmChunk> process(PcmChunk chunk) override;
    std::vector<PcmChunk> finish(AudioTerminalReason reason) override;
    void reset() noexcept override;

private:
    void configure(const PcmChunk& chunk);
    void validate_chunk(const PcmChunk& chunk) const;
    void apply_fade();
    [[nodiscard]] std::size_t silence_bytes(std::uint32_t duration_ms) const;

    TerminalFadeOptions options_;
    std::optional<AudioFormat> format_;
    RequestId request_id_ = 0;
    std::size_t frame_bytes_ = 0;
    std::size_t hold_bytes_ = 0;
    bool received_audio_ = false;
    bool finished_ = false;
    std::vector<std::byte> pending_;
};

} // namespace qwen_tts_bridge::audio
