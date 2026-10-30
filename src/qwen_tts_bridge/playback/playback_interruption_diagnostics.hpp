#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace qwen_tts_bridge::playback {

struct PlaybackInterruptionDiagnostic;

namespace detail {

/// \brief Formats the schema-2 WinMM interruption diagnostic document.
///
/// This is an implementation-private serializer. Snapshot acquisition and
/// filesystem publication remain owned by WaveOutPlayer.
std::string format_interruption_diagnostics_json(
    const std::vector<PlaybackInterruptionDiagnostic>& diagnostics,
    std::uint64_t late_audio_after_terminal_count);

} // namespace detail
} // namespace qwen_tts_bridge::playback
