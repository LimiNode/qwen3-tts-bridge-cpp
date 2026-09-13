#pragma once

#include <filesystem>
#include <vector>

namespace qwen_tts_bridge::native_worker {

/// Load a mono 24 kHz PCM reference WAV as normalized float samples.
///
/// The native Base voice-clone path deliberately normalizes the reference
/// boundary after decoding.  Callers that need the same conditioning as the
/// FasterQwen backend should pass the returned samples through
/// append_reference_trailing_silence() before encoding them.
///
/// \param path WAV file to decode.
/// \return Normalized mono samples at 24 kHz.
/// \throws std::runtime_error if the file is malformed or uses an unsupported
///         format.
std::vector<float> read_mono_24k_wav(const std::filesystem::path& path);

/// Append the canonical Base ICL boundary silence used by FasterQwen.
///
/// Half a second of zero PCM makes the final reference codec frames represent
/// silence rather than the last phoneme of the recording.  This is part of the
/// voice-clone conditioning contract, so the silence must be present before
/// both raw synthesis and qt_voice_ref extraction/cache population.
///
/// \param samples Decoded mono 24 kHz samples; modified in place.
/// \param silence_seconds Duration to append.  The production default is 0.5.
void append_reference_trailing_silence(std::vector<float>& samples, double silence_seconds = 0.5);

} // namespace qwen_tts_bridge::native_worker
