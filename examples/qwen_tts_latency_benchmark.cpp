#include <qwen_tts_bridge/client.hpp>

#include "latency_benchmark.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <condition_variable>
#include <cstdint>
#include <exception>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <mutex>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <unordered_map>
#include <utility>
#include <vector>

using namespace qwen_tts_examples::benchmark;

namespace {
#ifndef QWEN_TTS_BRIDGE_EXAMPLE_PYTHON_EXECUTABLE
#define QWEN_TTS_BRIDGE_EXAMPLE_PYTHON_EXECUTABLE ""
#endif

#ifndef QWEN_TTS_BRIDGE_EXAMPLE_WORKER_DIR
#define QWEN_TTS_BRIDGE_EXAMPLE_WORKER_DIR ""
#endif

using Clock = std::chrono::steady_clock;

using qwen_tts_bridge::AudioFormat;
using qwen_tts_bridge::PcmChunk;
using qwen_tts_bridge::QwenTtsClient;
using qwen_tts_bridge::QwenTtsClientOptions;
using qwen_tts_bridge::RequestId;
using qwen_tts_bridge::StdIoTransportOptions;
using qwen_tts_bridge::TtsCallbacks;
using qwen_tts_bridge::TtsCompletion;
using qwen_tts_bridge::TtsError;
using qwen_tts_bridge::TtsRequest;

struct RequestProbe {
    std::mutex mutex;
    std::condition_variable condition;
    bool terminal = false;
    bool success = false;
    bool cancelled = false;
    bool cancel_after_first_audio = false;
    bool cancellation_requested = false;
    bool cancellation_dispatched = false;
    RequestId request_id = 0;
    std::string error_category;
    std::string error_code;
    std::string error_message;
    std::optional<TtsCompletion> completion;
    std::optional<double> first_audio_ms;
    std::optional<double> completed_ms;
    double enqueue_ms = 0.0;
    std::size_t audio_chunks = 0;
    std::uint64_t audio_bytes = 0;
    std::vector<ChunkResult> chunks;
    Clock::time_point start;
};

struct WorkerRequestMetrics {
    std::optional<double> queue_ms;
    std::optional<double> first_pcm_ready_ms;
    std::optional<double> first_frame_enqueue_ms;
    std::optional<double> writer_queue_ms;
    std::optional<double> writer_flush_ms;
    std::optional<double> writer_total_ms;
    nlohmann::json first_chunk_phases;
    std::vector<nlohmann::json> pcm_chunks;
    nlohmann::json generation_trace;
    nlohmann::json finished;
    nlohmann::json runtime_memory;
};

class WorkerMetricCollector {
public:
    void append_stderr(std::string text) {
        std::lock_guard<std::mutex> lock(mutex_);
        stderr_text_ += text;
        line_buffer_ += std::move(text);

        std::size_t newline = line_buffer_.find('\n');
        while (newline != std::string::npos) {
            std::string line = line_buffer_.substr(0, newline);
            if (!line.empty() && line.back() == '\r') {
                line.pop_back();
            }
            line_buffer_.erase(0, newline + 1u);
            parse_metric_line(line);
            newline = line_buffer_.find('\n');
        }
    }

    std::unordered_map<RequestId, WorkerRequestMetrics> request_metrics() const {
        std::lock_guard<std::mutex> lock(mutex_);
        return request_metrics_;
    }

private:
    void parse_metric_line(const std::string& line) {
        const std::string prefix = "qtb_metric ";
        const std::size_t prefix_at = line.find(prefix);
        if (prefix_at == std::string::npos) {
            return;
        }

        const nlohmann::json payload = nlohmann::json::parse(
            line.substr(prefix_at + prefix.size()), nullptr, false);
        if (payload.is_discarded() || !payload.is_object()) {
            return;
        }
        const auto event = payload.find("event");
        const auto request_id_value = payload.find("request_id");
        if (event == payload.end() || !event->is_string() ||
            request_id_value == payload.end() || !request_id_value->is_number_unsigned()) {
            return;
        }

        const auto request_id = request_id_value->get<RequestId>();
        WorkerRequestMetrics& metrics = request_metrics_[request_id];
        const auto number = [&payload](const char* name) -> std::optional<double> {
            const auto value = payload.find(name);
            if (value == payload.end() || !value->is_number()) {
                return std::nullopt;
            }
            return value->get<double>();
        };
        const std::string event_name = event->get<std::string>();
        if (event_name == "request_engine_started") {
            metrics.queue_ms = number("queue_ms");
        }
        else if (event_name == "request_first_pcm_ready") {
            metrics.first_pcm_ready_ms = number("first_pcm_ready_ms");
        }
        else if (event_name == "request_first_frame_enqueued") {
            metrics.first_frame_enqueue_ms = number("first_frame_enqueue_ms");
        }
        else if (event_name == "request_first_frame_flushed") {
            metrics.writer_queue_ms = number("output_queue_ms");
            metrics.writer_flush_ms = number("flush_ms");
            metrics.writer_total_ms = number("output_writer_ms");
        }
        else if (event_name == "request_first_chunk_engine_phases") {
            metrics.first_chunk_phases = payload;
        }
        else if (event_name == "request_pcm_chunk") {
            metrics.pcm_chunks.push_back(payload);
        }
        else if (event_name == "request_generation_trace") {
            metrics.generation_trace = payload;
        }
        else if (event_name == "request_finished") {
            metrics.finished = payload;
        }
        else if (event_name == "worker_runtime_memory") {
            metrics.runtime_memory = payload;
        }
    }

    mutable std::mutex mutex_;
    std::string stderr_text_;
    std::string line_buffer_;
    std::unordered_map<RequestId, WorkerRequestMetrics> request_metrics_;
};

StdIoTransportOptions make_transport_options(
    const ProgramOptions& options,
    WorkerMetricCollector& metrics) {
    StdIoTransportOptions transport_options;
    transport_options.stderr_handler = [&metrics](std::string text) {
        metrics.append_stderr(text);
        std::cerr << text;
    };

    if (options.use_mock_worker) {
        const std::string python_executable = QWEN_TTS_BRIDGE_EXAMPLE_PYTHON_EXECUTABLE;
        const std::string worker_dir = QWEN_TTS_BRIDGE_EXAMPLE_WORKER_DIR;
        if (python_executable.empty() || worker_dir.empty()) {
            throw std::runtime_error(
                "--mock is unavailable because the example was built without Python discovery");
        }

        transport_options.arguments = {
            python_executable,
            "-m",
            "qwen_tts_bridge_worker.main",
            "--mock",
            "--mock-chunks",
            std::to_string(options.mock_chunks),
            "--mock-chunk-ms",
            std::to_string(options.mock_chunk_ms),
            "--mock-chunk-delay",
            std::to_string(options.mock_chunk_delay)
        };
        transport_options.working_directory = worker_dir;
        return transport_options;
    }

    transport_options.arguments.push_back(options.worker_executable);
    transport_options.arguments.insert(
        transport_options.arguments.end(),
        options.worker_arguments.begin(),
        options.worker_arguments.end());
    transport_options.working_directory = options.working_directory;
    return transport_options;
}

AudioFormat requested_audio_format(const ProgramOptions& options) {
    AudioFormat format;
    format.sample_format = "s16le";
    format.sample_rate = options.sample_rate;
    format.channels = options.channels;
    return format;
}

double elapsed_ms(Clock::time_point start) {
    return std::chrono::duration<double, std::milli>(Clock::now() - start).count();
}

TtsCallbacks make_latency_callbacks(QwenTtsClient& client, RequestProbe& probe) {
    TtsCallbacks callbacks;
    callbacks.on_audio = [&client, &probe](const PcmChunk& chunk) {
        RequestId request_id = 0;
        bool cancel = false;
        {
            std::lock_guard<std::mutex> lock(probe.mutex);
            const double arrival_ms = elapsed_ms(probe.start);
            if (!probe.first_audio_ms.has_value()) {
                probe.first_audio_ms = arrival_ms;
            }
            const double bytes_per_ms =
                static_cast<double>(chunk.format.sample_rate) *
                static_cast<double>(chunk.format.channels) *
                2.0 / 1000.0;
            probe.chunks.push_back(ChunkResult{
                probe.audio_chunks,
                arrival_ms,
                static_cast<std::uint64_t>(chunk.bytes.size()),
                bytes_per_ms > 0.0
                    ? static_cast<double>(chunk.bytes.size()) / bytes_per_ms
                    : 0.0,
            });
            probe.audio_chunks += 1;
            probe.audio_bytes += chunk.bytes.size();
            if (probe.cancel_after_first_audio && !probe.cancellation_requested) {
                probe.cancellation_requested = true;
            }
            if (probe.cancellation_requested &&
                !probe.cancellation_dispatched &&
                probe.request_id != 0) {
                probe.cancellation_dispatched = true;
                request_id = probe.request_id;
                cancel = true;
            }
        }
        if (cancel) {
            client.cancel(request_id);
        }
    };
    callbacks.on_completed = [&probe]() {
        {
            std::lock_guard<std::mutex> lock(probe.mutex);
            probe.completed_ms = elapsed_ms(probe.start);
            probe.success = true;
            probe.terminal = true;
        }
        probe.condition.notify_all();
    };
    callbacks.on_completion_metadata = [&probe](const TtsCompletion& completion) {
        std::lock_guard<std::mutex> lock(probe.mutex);
        probe.completion = completion;
    };
    callbacks.on_cancelled = [&probe]() {
        {
            std::lock_guard<std::mutex> lock(probe.mutex);
            probe.completed_ms = elapsed_ms(probe.start);
            probe.cancelled = true;
            probe.error_category = "request";
            probe.error_code = "cancelled";
            probe.error_message = "request was cancelled";
            probe.terminal = true;
        }
        probe.condition.notify_all();
    };
    callbacks.on_error = [&probe](const TtsError& error) {
        {
            std::lock_guard<std::mutex> lock(probe.mutex);
            probe.completed_ms = elapsed_ms(probe.start);
            probe.error_category = error.category;
            probe.error_code = error.code;
            probe.error_message = error.message;
            probe.terminal = true;
        }
        probe.condition.notify_all();
    };
    return callbacks;
}

TtsRequest make_request(
    const ProgramOptions& options,
    const AudioFormat& audio_format,
    const RequestSpec* spec) {
    TtsRequest request;
    request.text = spec != nullptr ? spec->text : options.text;
    request.language = spec != nullptr ? spec->language : options.language;
    request.speaker = spec != nullptr ? spec->speaker : options.speaker;
    request.voice_id = spec != nullptr ? spec->voice_id : options.voice_id;
    request.instruction = spec != nullptr ? spec->instruction : options.instruction;
    request.reference_audio_path = spec != nullptr
        ? spec->reference_audio_path
        : options.reference_audio_path;
    request.reference_text = spec != nullptr ? spec->reference_text : options.reference_text;
    request.x_vector_only = spec != nullptr ? spec->x_vector_only : options.x_vector_only;
    const std::optional<std::uint64_t> seed =
        spec != nullptr && spec->seed.has_value() ? spec->seed : options.seed;
    if (seed.has_value()) {
        request.has_seed = true;
        request.seed = seed.value();
    }
    request.output = audio_format;
    return request;
}

RequestResult run_request(
    QwenTtsClient& client,
    const ProgramOptions& options,
    const AudioFormat& audio_format,
    int index,
    bool warmup,
    const RequestSpec* spec = nullptr) {
    RequestProbe probe;
    const std::uint64_t late_audio_before = client.late_audio_after_terminal_count();
    const std::uint64_t duplicate_terminal_before = client.duplicate_terminal_event_count();
    const bool row_has_terminal_contract = spec != nullptr &&
        (!spec->allowed_terminal_outcomes.empty() ||
         !spec->expected_error_category.empty() || !spec->allowed_errors.empty());
    probe.cancel_after_first_audio = !warmup &&
        ((spec != nullptr && spec->cancel_after_first_pcm) ||
         (!row_has_terminal_contract && options.cancel_every > 0 && index % options.cancel_every == 0));
    probe.start = Clock::now();
    const RequestId request_id = client.synthesize_async(
        make_request(options, audio_format, spec),
        make_latency_callbacks(client, probe));
    probe.enqueue_ms = elapsed_ms(probe.start);

    if (request_id == 0) {
        throw std::runtime_error("failed to enqueue synthesis request");
    }
    RequestId immediate_cancel_id = 0;
    {
        std::lock_guard<std::mutex> lock(probe.mutex);
        probe.request_id = request_id;
        if (probe.cancellation_requested && !probe.cancellation_dispatched) {
            probe.cancellation_dispatched = true;
            immediate_cancel_id = request_id;
        }
    }
    if (immediate_cancel_id != 0) {
        client.cancel(immediate_cancel_id);
    }

    {
        std::unique_lock<std::mutex> lock(probe.mutex);
        if (!probe.condition.wait_for(
                lock,
                options.request_timeout,
                [&probe]() { return probe.terminal; })) {
            lock.unlock();
            client.cancel(request_id);
            throw std::runtime_error("synthesis request timed out");
        }
    }
    if (options.terminal_quiet.count() > 0) {
        std::this_thread::sleep_for(options.terminal_quiet);
    }

    RequestResult result;
    {
        std::lock_guard<std::mutex> lock(probe.mutex);
        result.index = index;
        result.label = spec != nullptr ? spec->label : "";
        if (spec != nullptr) {
            result.allowed_terminal_outcomes = spec->allowed_terminal_outcomes;
            result.expected_error_category = spec->expected_error_category;
            result.expected_error_code = spec->expected_error_code;
            result.allowed_errors = spec->allowed_errors;
            result.cancel_after_first_pcm = spec->cancel_after_first_pcm;
        }
        if (spec != nullptr && spec->has_contract()) {
            result.expected_prefill_length = spec->expected_prefill_length;
            result.expected_route = spec->expected_route;
            result.expected_backend = spec->expected_backend;
            result.expected_chunk_schedule = spec->expected_chunk_schedule;
        }
        result.request_id = request_id;
        result.warmup = warmup;
        result.success = probe.success;
        result.cancelled = probe.cancelled;
        result.cancellation_expected = probe.cancel_after_first_audio;
        result.first_audio_ms = probe.first_audio_ms;
        result.completed_ms = probe.completed_ms;
        result.enqueue_ms = probe.enqueue_ms;
        result.audio_chunks = probe.audio_chunks;
        result.audio_bytes = probe.audio_bytes;
        result.chunks = probe.chunks;
        result.error_category = probe.error_category;
        result.error_code = probe.error_code;
        result.error_message = probe.error_message;
        if (probe.completion.has_value()) {
            result.completion_metadata = probe.completion;
            result.completion_execution_outcome = probe.completion->execution_outcome;
        }
    }

    const double bytes_per_ms =
        static_cast<double>(audio_format.sample_rate) *
        static_cast<double>(audio_format.channels) *
        2.0 / 1000.0;
    result.audio_duration_ms =
        bytes_per_ms > 0.0 ? static_cast<double>(result.audio_bytes) / bytes_per_ms : 0.0;
    if (result.completed_ms.has_value() && result.audio_duration_ms > 0.0) {
        result.real_time_factor = result.completed_ms.value() / result.audio_duration_ms;
        result.inverse_real_time_factor =
            result.audio_duration_ms / result.completed_ms.value();
    }
    result.late_audio_after_terminal_count =
        client.late_audio_after_terminal_count() - late_audio_before;
    result.duplicate_terminal_event_count =
        client.duplicate_terminal_event_count() - duplicate_terminal_before;
    return result;
}

void attach_worker_metrics(
    std::vector<RequestResult>& results,
    const std::unordered_map<RequestId, WorkerRequestMetrics>& metrics_by_request) {
    for (RequestResult& result : results) {
        const auto found = metrics_by_request.find(result.request_id);
        if (found == metrics_by_request.end()) {
            continue;
        }
        const WorkerRequestMetrics& metrics = found->second;
        result.worker_queue_ms = metrics.queue_ms;
        result.worker_first_pcm_ready_ms = metrics.first_pcm_ready_ms;
        result.worker_first_frame_enqueue_ms = metrics.first_frame_enqueue_ms;
        result.worker_writer_queue_ms = metrics.writer_queue_ms;
        result.worker_writer_flush_ms = metrics.writer_flush_ms;
        result.worker_writer_total_ms = metrics.writer_total_ms;
        result.worker_first_chunk_phases = metrics.first_chunk_phases;
        result.worker_pcm_chunks = metrics.pcm_chunks;
        result.worker_generation_trace = metrics.generation_trace;
        result.worker_finished = metrics.finished;
        result.worker_runtime_memory = metrics.runtime_memory;

        if (metrics.first_frame_enqueue_ms.has_value() &&
            metrics.first_pcm_ready_ms.has_value()) {
            result.worker_pcm_to_enqueue_ms =
                metrics.first_frame_enqueue_ms.value() -
                metrics.first_pcm_ready_ms.value();
        }

        if (result.first_audio_ms.has_value() &&
            metrics.queue_ms.has_value() &&
            metrics.first_pcm_ready_ms.has_value() &&
            result.worker_pcm_to_enqueue_ms.has_value() &&
            metrics.writer_total_ms.has_value()) {
            result.transport_dispatch_residual_ms =
                result.first_audio_ms.value() -
                metrics.queue_ms.value() -
                metrics.first_pcm_ready_ms.value() -
                result.worker_pcm_to_enqueue_ms.value() -
                metrics.writer_total_ms.value();
        }
    }
}

RequestSpec make_reference_warmup_spec(
    const ProgramOptions& options,
    const ProgramOptions& warmup_options) {
    RequestSpec warmup_spec;
    warmup_spec.text = warmup_options.text;
    warmup_spec.language = options.language;
    warmup_spec.speaker = options.speaker;
    warmup_spec.instruction = options.instruction;
    warmup_spec.reference_audio_path = options.warmup_reference_audio_path;
    warmup_spec.reference_text = options.warmup_reference_text;
    warmup_spec.x_vector_only = options.x_vector_only;
    warmup_spec.seed = options.seed;
    return warmup_spec;
}

} // namespace

int main(int argc, char** argv) {
    try {
        ProgramOptions options = parse_options(argc, argv);
        if (options.self_test_eos_contract) {
            return run_eos_contract_self_test();
        }
        validate_options(options);

        if (options.help) {
            print_usage(std::cout, argv[0]);
            return 0;
        }

        const std::vector<RequestSpec> request_specs = load_request_manifest(options);
        const AudioFormat audio_format = requested_audio_format(options);

        QwenTtsClientOptions client_options;
        client_options.session.startup_timeout = options.startup_timeout;

        WorkerMetricCollector worker_metrics;
        QwenTtsClient client;
        const Clock::time_point startup_start = Clock::now();
        if (!client.start(make_transport_options(options, worker_metrics), client_options)) {
            throw std::runtime_error("failed to start Qwen TTS worker");
        }
        const double startup_ms = elapsed_ms(startup_start);

        std::vector<RequestResult> warmups;
        std::vector<RequestResult> measured;
        warmups.reserve(static_cast<std::size_t>(options.warmups));
        measured.reserve(static_cast<std::size_t>(options.requests));

        ProgramOptions warmup_options = options;
        if (!options.warmup_text.empty()) {
            warmup_options.text = options.warmup_text;
        }
        for (int index = 0; index < options.warmups; ++index) {
            RequestSpec warmup_spec;
            const RequestSpec* spec = nullptr;
            if (!options.warmup_reference_audio_path.empty()) {
                warmup_spec = make_reference_warmup_spec(options, warmup_options);
                spec = &warmup_spec;
            } else if (options.warmup_text.empty()) {
                spec = request_specs.empty()
                    ? nullptr
                    : &request_specs[static_cast<std::size_t>(index) % request_specs.size()];
            }
            warmups.push_back(run_request(
                client,
                warmup_options,
                audio_format,
                index + 1,
                true,
                spec));
        }
        for (int index = 0; index < options.requests; ++index) {
            const RequestSpec* spec = request_specs.empty()
                ? nullptr
                : &request_specs[static_cast<std::size_t>(index) % request_specs.size()];
            measured.push_back(run_request(
                client,
                options,
                audio_format,
                index + 1,
                false,
                spec));
        }

        client.stop();
        const auto metrics_by_request = worker_metrics.request_metrics();
        attach_worker_metrics(warmups, metrics_by_request);
        attach_worker_metrics(measured, metrics_by_request);
        for (RequestResult& result : warmups) {
            validate_generic_acceptance(result);
        }
        for (RequestResult& result : measured) {
            validate_generic_acceptance(result);
            validate_request_contract(result);
        }
        if (options.result_json_path.empty()) {
            write_results_json(std::cout, options, startup_ms, warmups, measured);
        }
        else {
            std::ofstream output(options.result_json_path, std::ios::binary | std::ios::trunc);
            if (!output) {
                throw std::runtime_error("failed to open --result-json output");
            }
            write_results_json(output, options, startup_ms, warmups, measured);
            if (!output) {
                throw std::runtime_error("failed to write --result-json output");
            }
        }
        return (has_acceptance_failures(warmups) ||
                has_acceptance_failures(measured) ||
                has_contract_failures(measured)) ? 2 : 0;
    }
    catch (const std::exception& exc) {
        std::cerr << "qwen_tts_latency_benchmark: " << exc.what() << '\n';
        std::cerr << "Run with --help for usage.\n";
        return 1;
    }
}
