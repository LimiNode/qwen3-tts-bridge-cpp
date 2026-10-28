#pragma once

#include <qwen.h>

#include <cstdint>
#include <filesystem>
#include <string>
#include <vector>

namespace qwen_tts_bridge::native_worker {

struct PreparedVoiceReferenceContext {
    std::filesystem::path manifest_path;
    std::filesystem::path source_audio_path;
    std::string reference_text;
    bool x_vector_only = false;
    std::string source_audio_sha256;
    std::string talker_sha256;
    std::string codec_sha256;
    std::string engine_commit;
    int abi_version = 0;
    int num_codebooks = 0;
};

struct PreparedVoiceReferenceData {
    std::vector<float> speaker_embedding;
    std::vector<std::int32_t> codes;
    int frames = 0;
    int num_codebooks = 0;
    std::string cache_key;
};

/// Resolve a registry-relative prepared manifest without allowing traversal.
std::filesystem::path resolve_prepared_manifest_path(
    const std::filesystem::path& registry_directory,
    const std::string& relative_path);

/// Load and fully validate persisted speaker/RVQ conditioning.
PreparedVoiceReferenceData load_prepared_voice_reference(
    const PreparedVoiceReferenceContext& context);

/// Transactionally persist, re-read and validate one extracted reference.
PreparedVoiceReferenceData persist_prepared_voice_reference(
    const PreparedVoiceReferenceContext& context,
    const qt_voice_ref& extracted);

} // namespace qwen_tts_bridge::native_worker
