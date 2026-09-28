#pragma once

/// \file save_wav_callbacks.hpp
/// \brief Callback helpers for streaming PCM into a WAV writer.

#include <chrono>
#include <condition_variable>
#include <cstddef>
#include <cstdint>
#include <mutex>
#include <string>

#include "../client/client_types.hpp"
#include "../protocol/control/control_messages.hpp"

namespace qwen_tts_bridge::audio {

class WavWriter;

/// \struct AudioTailOptions
/// \brief Optional terminal PCM shaping for saved or played audio.
///
/// The bridge keeps the final fade window buffered until a terminal callback
/// arrives.  This makes it possible to smooth both normal completion and an
/// intentionally cancelled request without changing the model's PCM output.
/// The option is disabled by default so callers that need model-faithful PCM
/// retain the existing behaviour.
struct AudioTailOptions {
    bool enabled = false; ///< Whether terminal shaping is enabled.
    std::uint32_t fade_ms = 15; ///< Duration of the terminal fade in milliseconds.
    std::uint32_t completion_silence_ms = 85; ///< Silence appended after completion.
    std::uint32_t cancellation_silence_ms = 0; ///< Silence appended after cancellation.
};

/// \struct SaveWavState
/// \brief Shared completion state for asynchronous WAV output.
struct SaveWavState {
    std::mutex mutex; ///< Protects terminal state and counters.
    std::mutex writer_mutex; ///< Serializes WAV writer access from callbacks.
    std::condition_variable condition; ///< Notifies terminal state changes.
    bool terminal = false; ///< Whether a terminal callback was received.
    bool success = false; ///< Whether the terminal state was completion.
    std::string message; ///< Terminal diagnostic when unsuccessful.
    std::size_t audio_chunks = 0; ///< Number of PCM chunks written.
    std::uint64_t audio_bytes = 0; ///< Number of PCM bytes written.
};

/// \brief Marks the WAV output operation as terminal and wakes waiters.
void mark_save_wav_finished(
    SaveWavState& state,
    bool success,
    std::string message);

/// \brief Waits until the request reaches a terminal callback state.
bool wait_for_save_wav_terminal(
    SaveWavState& state,
    std::chrono::milliseconds timeout);

/// \brief Builds callbacks that stream matching PCM chunks into a WAV writer.
TtsCallbacks make_save_wav_callbacks(
    SaveWavState& state,
    WavWriter& writer,
    const AudioFormat& expected_format,
    AudioTailOptions tail_options = {});

} // namespace qwen_tts_bridge::audio
