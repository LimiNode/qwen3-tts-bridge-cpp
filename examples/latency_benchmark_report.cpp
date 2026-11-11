#include <qwen_tts_bridge/client.hpp>

#include "latency_benchmark.hpp"

#include <algorithm>
#include <cmath>
#include <iomanip>
#include <ostream>
#include <sstream>

namespace qwen_tts_examples::benchmark {

std::string json_escape(const std::string& value) {
    std::ostringstream out;
    for (const char ch : value) {
        switch (ch) {
        case '\\':
            out << "\\\\";
            break;
        case '"':
            out << "\\\"";
            break;
        case '\b':
            out << "\\b";
            break;
        case '\f':
            out << "\\f";
            break;
        case '\n':
            out << "\\n";
            break;
        case '\r':
            out << "\\r";
            break;
        case '\t':
            out << "\\t";
            break;
        default:
            if (static_cast<unsigned char>(ch) < 0x20u) {
                out << "\\u"
                    << std::hex << std::setw(4) << std::setfill('0')
                    << static_cast<int>(static_cast<unsigned char>(ch))
                    << std::dec << std::setfill(' ');
            }
            else {
                out << ch;
            }
            break;
        }
    }
    return out.str();
}

void write_number_or_null(std::ostream& out, const std::optional<double>& value) {
    if (value.has_value()) {
        out << std::fixed << std::setprecision(3) << value.value();
    }
    else {
        out << "null";
    }
}

std::vector<double> collect_metric(
    const std::vector<RequestResult>& results,
    std::optional<double> RequestResult::*field) {
    std::vector<double> values;
    for (const RequestResult& result : results) {
        if (!result.success || !result.acceptance_valid ||
            (result.contract_checked && !result.contract_valid)) {
            continue;
        }
        const std::optional<double>& value = result.*field;
        if (value.has_value()) {
            values.push_back(value.value());
        }
    }
    std::sort(values.begin(), values.end());
    return values;
}

double percentile(const std::vector<double>& values, double percentile_value) {
    if (values.empty()) {
        return 0.0;
    }
    const double rank =
        percentile_value / 100.0 * static_cast<double>(values.size() - 1u);
    const auto low = static_cast<std::size_t>(std::floor(rank));
    const auto high = static_cast<std::size_t>(std::ceil(rank));
    if (low == high) {
        return values[low];
    }
    const double fraction = rank - static_cast<double>(low);
    return values[low] * (1.0 - fraction) + values[high] * fraction;
}

void write_metric_summary(
    std::ostream& out,
    const char* name,
    const std::vector<double>& values) {
    out << "\"" << name << "\":";
    if (values.empty()) {
        out << "null";
        return;
    }
    out << "{"
        << "\"min\":" << std::fixed << std::setprecision(3) << values.front()
        << ",\"median\":" << percentile(values, 50.0)
        << ",\"p90\":" << percentile(values, 90.0)
        << ",\"p95\":" << percentile(values, 95.0)
        << ",\"max\":" << values.back()
        << "}";
}

void write_results_json(
    std::ostream& out,
    const ProgramOptions& options,
    double startup_ms,
    const std::vector<RequestResult>& warmups,
    const std::vector<RequestResult>& measured) {
    out << "{";
    out << "\"config\":{"
        << "\"text\":\"" << json_escape(options.text) << "\","
        << "\"warmup_text\":\"" << json_escape(options.warmup_text) << "\","
        << "\"warmup_reference_audio_path\":\""
        << json_escape(options.warmup_reference_audio_path) << "\","
        << "\"warmup_reference_text\":\""
        << json_escape(options.warmup_reference_text) << "\","
        << "\"terminal_quiet_ms\":" << options.terminal_quiet.count() << ","
        << "\"language\":\"" << json_escape(options.language) << "\","
        << "\"speaker\":\"" << json_escape(options.speaker) << "\","
        << "\"instruction\":\"" << json_escape(options.instruction) << "\","
        << "\"voice_id\":\"" << json_escape(options.voice_id) << "\","
        << "\"reference_audio_path\":\"" << json_escape(options.reference_audio_path) << "\","
        << "\"reference_text\":\"" << json_escape(options.reference_text) << "\","
        << "\"x_vector_only\":" << (options.x_vector_only ? "true" : "false") << ","
        << "\"sample_rate\":" << options.sample_rate << ","
        << "\"channels\":" << options.channels << ","
        << "\"warmups\":" << options.warmups << ","
        << "\"requests\":" << options.requests << ","
        << "\"cancel_every\":" << options.cancel_every << ","
        << "\"seed\":";
    if (options.seed.has_value()) {
        out << options.seed.value();
    }
    else {
        out << "null";
    }
    out
        << "},";
    out << "\"startup_ms\":" << std::fixed << std::setprecision(3) << startup_ms << ",";

    out << "\"summary\":{";
    const auto cancelled_count = std::count_if(
        measured.begin(),
        measured.end(),
        [](const RequestResult& result) { return result.cancelled; });
    const auto failed_count = std::count_if(
        measured.begin(),
        measured.end(),
        [](const RequestResult& result) {
            return !result.success && !result.cancelled;
        });
    const auto excluded_contract_count = std::count_if(
        measured.begin(),
        measured.end(),
        [](const RequestResult& result) {
            return result.contract_checked && !result.contract_valid;
        });
    const auto acceptance_failure_count = std::count_if(
        measured.begin(),
        measured.end(),
        [](const RequestResult& result) { return !result.acceptance_valid; });
    out << "\"cancelled_requests\":" << cancelled_count << ","
        << "\"failed_requests\":" << failed_count << ","
        << "\"excluded_contract_requests\":" << excluded_contract_count << ",";
    out << "\"acceptance_failed_requests\":" << acceptance_failure_count << ",";
    write_metric_summary(out, "first_audio_ms", collect_metric(measured, &RequestResult::first_audio_ms));
    out << ",";
    write_metric_summary(out, "completed_ms", collect_metric(measured, &RequestResult::completed_ms));
    out << ",";
    write_metric_summary(out, "real_time_factor", collect_metric(measured, &RequestResult::real_time_factor));
    out << ",";
    write_metric_summary(out, "inverse_real_time_factor", collect_metric(measured, &RequestResult::inverse_real_time_factor));
    out << ",";
    write_metric_summary(out, "transport_dispatch_residual_ms", collect_metric(measured, &RequestResult::transport_dispatch_residual_ms));
    out << "},";

    auto write_array = [&out](const char* name, const std::vector<RequestResult>& results) {
        out << "\"" << name << "\":[";
        for (std::size_t index = 0; index < results.size(); ++index) {
            const RequestResult& result = results[index];
            if (index != 0u) {
                out << ",";
            }
            out << "{"
                << "\"index\":" << result.index << ","
                << "\"label\":\"" << json_escape(result.label) << "\","
                << "\"request_id\":" << result.request_id << ","
                << "\"success\":" << (result.success ? "true" : "false") << ","
                << "\"cancelled\":" << (result.cancelled ? "true" : "false") << ","
                << "\"cancellation_expected\":"
                << (result.cancellation_expected ? "true" : "false") << ","
                << "\"cancel_after_first_pcm\":"
                << (result.cancel_after_first_pcm ? "true" : "false") << ","
                << "\"late_audio_after_terminal_count\":"
                << result.late_audio_after_terminal_count << ","
                << "\"duplicate_terminal_event_count\":"
                << result.duplicate_terminal_event_count << ","
                << "\"completion_execution_outcome\":";
            if (result.completion_execution_outcome.has_value()) {
                out << "\"" << json_escape(result.completion_execution_outcome.value()) << "\"";
            } else {
                out << "null";
            }
            out << ","
                << "\"completion_metadata\":";
            if (result.completion_metadata.has_value()) {
                const TtsCompletion& completion = result.completion_metadata.value();
                out << "{\"execution_outcome\":\""
                    << json_escape(completion.execution_outcome)
                    << "\",\"has_generation_trace\":"
                    << (completion.has_generation_trace ? "true" : "false")
                    << ",\"termination_reason\":\""
                    << json_escape(completion.termination_reason)
                    << "\",\"hit_eos\":" << (completion.hit_eos ? "true" : "false")
                    << ",\"hit_max_seq_len\":" << (completion.hit_max_seq_len ? "true" : "false")
                    << ",\"hit_max_new_tokens\":" << (completion.hit_max_new_tokens ? "true" : "false")
                    << ",\"codec_frame_count\":" << completion.codec_frame_count
                    << ",\"generated_steps\":" << completion.generated_steps
                    << ",\"emitted_steps\":" << completion.emitted_steps
                    << ",\"terminal_step_index\":" << completion.terminal_step_index
                    << "}";
            } else {
                out << "null";
            }
            out << ","
                << "\"enqueue_ms\":" << std::fixed << std::setprecision(3) << result.enqueue_ms
                << ",\"first_audio_ms\":";
            write_number_or_null(out, result.first_audio_ms);
            out << ",\"completed_ms\":";
            write_number_or_null(out, result.completed_ms);
            out << ",\"audio_bytes\":" << result.audio_bytes
                << ",\"audio_chunks\":" << result.audio_chunks
                << ",\"chunks\":[";
            for (std::size_t chunk_index = 0; chunk_index < result.chunks.size(); ++chunk_index) {
                const ChunkResult& chunk = result.chunks[chunk_index];
                if (chunk_index != 0u) {
                    out << ",";
                }
                out << "{"
                    << "\"index\":" << chunk.index
                    << ",\"arrival_ms\":" << std::fixed << std::setprecision(3)
                    << chunk.arrival_ms
                    << ",\"audio_bytes\":" << chunk.audio_bytes
                    << ",\"audio_duration_ms\":" << chunk.audio_duration_ms
                    << "}";
            }
            out << "]"
                << ",\"audio_duration_ms\":" << result.audio_duration_ms
                << ",\"real_time_factor\":";
            write_number_or_null(out, result.real_time_factor);
            out << ",\"local_rtf\":";
            write_number_or_null(out, result.real_time_factor);
            out << ",\"inverse_rtf\":";
            write_number_or_null(out, result.inverse_real_time_factor);
            out << ",\"worker_queue_ms\":";
            write_number_or_null(out, result.worker_queue_ms);
            out << ",\"worker_first_pcm_ready_ms\":";
            write_number_or_null(out, result.worker_first_pcm_ready_ms);
            out << ",\"worker_first_frame_enqueue_ms\":";
            write_number_or_null(out, result.worker_first_frame_enqueue_ms);
            out << ",\"worker_pcm_to_enqueue_ms\":";
            write_number_or_null(out, result.worker_pcm_to_enqueue_ms);
            out << ",\"worker_writer_queue_ms\":";
            write_number_or_null(out, result.worker_writer_queue_ms);
            out << ",\"worker_writer_flush_ms\":";
            write_number_or_null(out, result.worker_writer_flush_ms);
            out << ",\"worker_writer_total_ms\":";
            write_number_or_null(out, result.worker_writer_total_ms);
            out << ",\"transport_dispatch_residual_ms\":";
            write_number_or_null(out, result.transport_dispatch_residual_ms);
            out << ",\"manifest_contract\":{"
                << "\"checked\":" << (result.contract_checked ? "true" : "false")
                << ",\"valid\":" << (result.contract_valid ? "true" : "false")
                << ",\"expected\":";
            if (result.contract_checked) {
                out << "{"
                    << "\"prefill_length\":" << result.expected_prefill_length.value()
                    << ",\"route\":\"" << json_escape(result.expected_route) << "\""
                    << ",\"backend\":\"" << json_escape(result.expected_backend) << "\""
                    << ",\"chunk_schedule\":"
                    << nlohmann::json(result.expected_chunk_schedule).dump()
                    << "}";
            }
            else {
                out << "null";
            }
            out << ",\"failures\":"
                << nlohmann::json(result.contract_failures).dump()
                << "}"
                << ",\"acceptance\":{"
                << "\"valid\":" << (result.acceptance_valid ? "true" : "false")
                << ",\"failures\":"
                << nlohmann::json(result.acceptance_failures).dump()
                << ",\"allowed_terminal_outcomes\":"
                << nlohmann::json(result.allowed_terminal_outcomes).dump()
                << ",\"expected_error_category\":\""
                << json_escape(result.expected_error_category)
                << "\",\"expected_error_code\":\""
                << json_escape(result.expected_error_code)
                << "\",\"allowed_errors\":[";
            for (std::size_t error_index = 0; error_index < result.allowed_errors.size(); ++error_index) {
                if (error_index != 0u) {
                    out << ",";
                }
                out << "{\"category\":\""
                    << json_escape(result.allowed_errors[error_index].first)
                    << "\",\"code\":\""
                    << json_escape(result.allowed_errors[error_index].second)
                    << "\"}";
            }
            out << "]}"
                << ",\"worker_telemetry\":{"
                << "\"first_chunk_phases\":" << result.worker_first_chunk_phases.dump()
                << ",\"pcm_chunks\":" << nlohmann::json(result.worker_pcm_chunks).dump()
                << ",\"generation_trace\":" << result.worker_generation_trace.dump()
                << ",\"finished\":" << result.worker_finished.dump()
                << ",\"runtime_memory\":" << result.worker_runtime_memory.dump()
                << "}";
            if (!result.success) {
                out << ",\"error_category\":\"" << json_escape(result.error_category) << "\""
                    << ",\"error_code\":\"" << json_escape(result.error_code) << "\""
                    << ",\"error_message\":\"" << json_escape(result.error_message) << "\"";
            }
            out << "}";
        }
        out << "]";
    };
    write_array("warmups", warmups);
    out << ",";
    write_array("requests", measured);
    out << "}\n";
}

} // namespace qwen_tts_examples::benchmark
