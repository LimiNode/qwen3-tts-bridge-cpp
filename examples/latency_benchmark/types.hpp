#pragma once

#include <chrono>
#include <cstdint>
#include <optional>
#include <string>
#include <utility>
#include <vector>

namespace qwen_tts_examples::benchmark {

using qwen_tts_bridge::RequestId;
using qwen_tts_bridge::TtsCompletion;

struct ProgramOptions {
    bool help = false;
    bool self_test_eos_contract = false;
    bool use_mock_worker = false;
    std::string worker_executable;
    std::vector<std::string> worker_arguments;
    std::string working_directory;
    std::string text = "Latency benchmark request.";
    std::string warmup_text;
    std::string warmup_reference_audio_path;
    std::string warmup_reference_text;
    std::string language = "auto";
    std::string speaker;
    std::string voice_id;
    std::string instruction;
    std::string reference_audio_path;
    std::string reference_text;
    bool x_vector_only = false;
    std::string request_manifest;
    std::string result_json_path;
    std::uint32_t sample_rate = 24000;
    std::uint32_t channels = 1;
    int warmups = 5;
    int requests = 30;
    int cancel_every = 0;
    std::optional<std::uint64_t> seed;
    int mock_chunks = 3;
    int mock_chunk_ms = 100;
    double mock_chunk_delay = 0.0;
    std::chrono::milliseconds startup_timeout{30000};
    std::chrono::milliseconds request_timeout{60000};
    std::chrono::milliseconds terminal_quiet{250};
};

struct RequestSpec {
    std::string label;
    std::string text;
    std::string language;
    std::string speaker;
    std::string voice_id;
    std::string instruction;
    std::string reference_audio_path;
    std::string reference_text;
    bool x_vector_only = false;
    std::optional<std::uint64_t> seed;
    std::optional<int> expected_prefill_length;
    std::string expected_route;
    std::string expected_backend;
    std::vector<int> expected_chunk_schedule;
    std::vector<std::string> allowed_terminal_outcomes;
    std::string expected_error_category;
    std::string expected_error_code;
    std::vector<std::pair<std::string, std::string>> allowed_errors;
    bool cancel_after_first_pcm = false;

    bool has_contract() const {
        return expected_prefill_length.has_value();
    }
};

struct ChunkResult {
    std::size_t index = 0;
    double arrival_ms = 0.0;
    std::uint64_t audio_bytes = 0;
    double audio_duration_ms = 0.0;
};

struct RequestResult {
    int index = 0;
    std::string label;
    std::optional<int> expected_prefill_length;
    std::string expected_route;
    std::string expected_backend;
    std::vector<int> expected_chunk_schedule;
    std::vector<std::string> allowed_terminal_outcomes;
    std::string expected_error_category;
    std::string expected_error_code;
    std::vector<std::pair<std::string, std::string>> allowed_errors;
    bool cancel_after_first_pcm = false;
    RequestId request_id = 0;
    bool warmup = false;
    bool success = false;
    bool cancelled = false;
    bool cancellation_expected = false;
    std::optional<double> first_audio_ms;
    std::optional<double> completed_ms;
    double enqueue_ms = 0.0;
    std::size_t audio_chunks = 0;
    std::uint64_t audio_bytes = 0;
    std::vector<ChunkResult> chunks;
    double audio_duration_ms = 0.0;
    std::optional<double> real_time_factor;
    std::optional<double> inverse_real_time_factor;
    std::optional<double> worker_queue_ms;
    std::optional<double> worker_first_pcm_ready_ms;
    std::optional<double> worker_first_frame_enqueue_ms;
    std::optional<double> worker_pcm_to_enqueue_ms;
    std::optional<double> worker_writer_queue_ms;
    std::optional<double> worker_writer_flush_ms;
    std::optional<double> worker_writer_total_ms;
    std::optional<double> transport_dispatch_residual_ms;
    std::string error_category;
    std::string error_code;
    std::string error_message;
    std::optional<std::string> completion_execution_outcome;
    std::optional<TtsCompletion> completion_metadata;
    std::uint64_t late_audio_after_terminal_count = 0;
    std::uint64_t duplicate_terminal_event_count = 0;
    nlohmann::json worker_first_chunk_phases;
    std::vector<nlohmann::json> worker_pcm_chunks;
    nlohmann::json worker_generation_trace;
    nlohmann::json worker_finished;
    nlohmann::json worker_runtime_memory;
    bool contract_checked = false;
    bool contract_valid = true;
    std::vector<std::string> contract_failures;
    bool acceptance_valid = true;
    std::vector<std::string> acceptance_failures;
};

} // namespace qwen_tts_examples::benchmark
