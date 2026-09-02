#pragma once

/// \file SaveWavCallbacks.hpp
/// \brief Callback helpers for streaming PCM into a WAV writer.

#include <chrono>
#include <condition_variable>
#include <cstddef>
#include <cstdint>
#include <mutex>
#include <string>

namespace qwen_tts_bridge::audio {

class WavWriter;

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
    const AudioFormat& expected_format);

} // namespace qwen_tts_bridge::audio
