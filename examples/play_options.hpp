#pragma once

#include <chrono>
#include <cstddef>
#include <cstdint>
#include <optional>
#include <string>
#include <vector>

namespace qwen_tts_examples::play {

struct ProgramOptions {
    bool help = false;
    bool self_test_playback_lifecycle = false;
    bool use_mock_worker = false;
    bool playback_enabled = true;
    bool use_mock_playback_sink = false;
    bool require_natural_eos = true;
    std::string worker_executable;
    std::vector<std::string> worker_arguments;
    std::string working_directory;
    std::string text;
    std::string language = "auto";
    std::string speaker;
    std::string instruction;
    std::string voice_id;
    std::string reference_audio_path;
    std::string reference_text;
    bool x_vector_only = false;
    std::optional<double> temperature;
    std::optional<std::uint32_t> top_k;
    std::optional<double> top_p;
    std::optional<double> repetition_penalty;
    std::optional<bool> do_sample;
    std::optional<std::uint64_t> seed;
    bool sampling_overrides_supported = false;
    bool deterministic_seed_supported = false;
    bool voice_clone_supported = false;
    bool voice_profiles_supported = false;
    std::vector<std::string> voice_ids;
    std::uint32_t sample_rate = 24000;
    std::uint32_t channels = 1;
    int mock_chunks = 3;
    int mock_chunk_ms = 100;
    double mock_chunk_delay = 0.0;
    std::optional<std::size_t> mock_playback_fail_after_submissions;
    std::optional<std::string> mock_playback_fail_stage;
    std::chrono::milliseconds startup_timeout{30000};
    std::chrono::milliseconds request_timeout{300000};
    std::string playback_metrics_file;
    std::string playback_interruption_diagnostics_file;
    std::string playback_animation_receipts_file;
    std::uint32_t playback_animation_fps = 60;
    std::string pcm_capture_file;
    std::string wav_capture_file;
    bool mock_wav_capture_failure = false;
    std::size_t playback_prebuffer_chunks = 1;
    bool etw_playback_markers = false;
    bool auto_profile = false;
    std::size_t auto_fast_max_bytes = 240;
    bool terminal_fade_enabled = true;
    qwen_tts_bridge::audio::TerminalFadeOptions terminal_fade;
};

} // namespace qwen_tts_examples::play
