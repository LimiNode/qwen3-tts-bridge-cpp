#include <qwen_tts_bridge/client.hpp>
#include <qwen_tts_bridge/transport.hpp>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <condition_variable>
#include <cstdint>
#include <exception>
#include <iomanip>
#include <iostream>
#include <limits>
#include <mutex>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

#ifndef QWEN_TTS_BRIDGE_EXAMPLE_PYTHON_EXECUTABLE
#define QWEN_TTS_BRIDGE_EXAMPLE_PYTHON_EXECUTABLE ""
#endif

#ifndef QWEN_TTS_BRIDGE_EXAMPLE_WORKER_DIR
#define QWEN_TTS_BRIDGE_EXAMPLE_WORKER_DIR ""
#endif

namespace {

using Clock = std::chrono::steady_clock;

using qwen_tts_bridge::AudioFormat;
using qwen_tts_bridge::PcmChunk;
using qwen_tts_bridge::QwenTtsClient;
using qwen_tts_bridge::QwenTtsClientOptions;
using qwen_tts_bridge::RequestId;
using qwen_tts_bridge::StdIoTransportOptions;
using qwen_tts_bridge::TtsCallbacks;
using qwen_tts_bridge::TtsError;
using qwen_tts_bridge::TtsRequest;

struct ProgramOptions {
    bool help = false;
    bool use_mock_worker = false;
    std::string worker_executable;
    std::vector<std::string> worker_arguments;
    std::string working_directory;
    std::string text = "Latency benchmark request.";
    std::string language = "auto";
    std::string speaker;
    std::string instruction;
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
};

struct ChunkResult {
    std::size_t index = 0;
    double arrival_ms = 0.0;
    std::uint64_t audio_bytes = 0;
    double audio_duration_ms = 0.0;
};

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
    std::optional<double> first_audio_ms;
    std::optional<double> completed_ms;
    double enqueue_ms = 0.0;
    std::size_t audio_chunks = 0;
    std::uint64_t audio_bytes = 0;
    std::vector<ChunkResult> chunks;
    Clock::time_point start;
};

struct RequestResult {
    int index = 0;
    RequestId request_id = 0;
    bool warmup = false;
    bool success = false;
    bool cancelled = false;
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
};

struct WorkerRequestMetrics {
    std::optional<double> queue_ms;
    std::optional<double> first_pcm_ready_ms;
    std::optional<double> first_frame_enqueue_ms;
    std::optional<double> writer_queue_ms;
    std::optional<double> writer_flush_ms;
    std::optional<double> writer_total_ms;
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

        const std::string payload = line.substr(prefix_at + prefix.size());
        const std::optional<std::string> event = json_string_field(payload, "event");
        const std::optional<double> request_id_value =
            json_number_field(payload, "request_id");
        if (!event.has_value() || !request_id_value.has_value()) {
            return;
        }

        const auto request_id = static_cast<RequestId>(request_id_value.value());
        WorkerRequestMetrics& metrics = request_metrics_[request_id];
        if (event.value() == "request_engine_started") {
            metrics.queue_ms = json_number_field(payload, "queue_ms");
        }
        else if (event.value() == "request_first_pcm_ready") {
            metrics.first_pcm_ready_ms =
                json_number_field(payload, "first_pcm_ready_ms");
        }
        else if (event.value() == "request_first_frame_enqueued") {
            metrics.first_frame_enqueue_ms =
                json_number_field(payload, "first_frame_enqueue_ms");
        }
        else if (event.value() == "request_first_frame_flushed") {
            metrics.writer_queue_ms = json_number_field(payload, "output_queue_ms");
            metrics.writer_flush_ms = json_number_field(payload, "flush_ms");
            metrics.writer_total_ms = json_number_field(payload, "output_writer_ms");
        }
    }

    static std::optional<std::string> json_string_field(
        const std::string& payload,
        const std::string& name) {
        const std::string key = "\"" + name + "\":\"";
        const std::size_t start = payload.find(key);
        if (start == std::string::npos) {
            return std::nullopt;
        }
        const std::size_t value_start = start + key.size();
        const std::size_t value_end = payload.find('"', value_start);
        if (value_end == std::string::npos) {
            return std::nullopt;
        }
        return payload.substr(value_start, value_end - value_start);
    }

    static std::optional<double> json_number_field(
        const std::string& payload,
        const std::string& name) {
        const std::string key = "\"" + name + "\":";
        const std::size_t start = payload.find(key);
        if (start == std::string::npos) {
            return std::nullopt;
        }
        const std::size_t value_start = start + key.size();
        std::size_t value_end = value_start;
        while (value_end < payload.size()) {
            const char ch = payload[value_end];
            if ((ch >= '0' && ch <= '9') || ch == '-' || ch == '+' ||
                ch == '.' || ch == 'e' || ch == 'E') {
                ++value_end;
                continue;
            }
            break;
        }
        if (value_end == value_start) {
            return std::nullopt;
        }
        try {
            return std::stod(payload.substr(value_start, value_end - value_start));
        }
        catch (const std::exception&) {
            return std::nullopt;
        }
    }

    mutable std::mutex mutex_;
    std::string stderr_text_;
    std::string line_buffer_;
    std::unordered_map<RequestId, WorkerRequestMetrics> request_metrics_;
};

void print_usage(std::ostream& out, const char* executable_name) {
    out << "Usage:\n"
        << "  " << executable_name << " --mock --text \"Hello\"\n"
        << "  " << executable_name << " --worker qwen_tts_worker.exe --text \"Hello\"\n\n"
        << "Options:\n"
        << "  --help                         Show this help.\n"
        << "  --mock                         Run the bundled Python mock worker.\n"
        << "  --worker <path>                Worker executable path.\n"
        << "  --worker-arg <arg>             Extra worker argument; may be repeated.\n"
        << "  --cwd <path>                   Worker working directory.\n"
        << "  --text <utf8>                  Text to synthesize.\n"
        << "  --language <name>              Request language, default: auto.\n"
        << "  --speaker <name>               Optional request speaker or voice name.\n"
        << "  --instruction <utf8>           Natural-language style instruction.\n"
        << "  --sample-rate <hz>             Requested sample rate, default: 24000.\n"
        << "  --channels <count>             Requested channel count, default: 1.\n"
        << "  --warmups <count>              Warmup requests, default: 5.\n"
        << "  --requests <count>             Measured requests, default: 30.\n"
        << "  --cancel-every <count>         Cancel every Nth measured request after first PCM.\n"
        << "  --seed <value>                 Optional deterministic per-request seed.\n"
        << "  --startup-timeout-ms <ms>      Worker startup timeout, default: 30000.\n"
        << "  --request-timeout-ms <ms>      Per-request timeout, default: 60000.\n"
        << "  --mock-chunks <count>          Mock worker chunk count, default: 3.\n"
        << "  --mock-chunk-ms <ms>           Mock chunk duration, default: 100.\n"
        << "  --mock-chunk-delay <seconds>   Mock delay between chunks, default: 0.\n";
}

std::string require_value(
    int& index,
    int argc,
    char** argv,
    const std::string& option) {
    const std::string prefix = option + '=';
    const std::string current = argv[index];
    if (current.rfind(prefix, 0) == 0) {
        return current.substr(prefix.size());
    }
    if (index + 1 >= argc) {
        throw std::runtime_error("missing value for " + option);
    }
    ++index;
    return argv[index];
}

std::uint32_t parse_u32(const std::string& value, const std::string& option) {
    std::size_t parsed = 0;
    const unsigned long result = std::stoul(value, &parsed, 10);
    if (parsed != value.size() ||
        result > std::numeric_limits<std::uint32_t>::max()) {
        throw std::runtime_error("invalid integer for " + option + ": " + value);
    }
    return static_cast<std::uint32_t>(result);
}

int parse_int(const std::string& value, const std::string& option) {
    std::size_t parsed = 0;
    const long result = std::stol(value, &parsed, 10);
    if (parsed != value.size() ||
        result < std::numeric_limits<int>::min() ||
        result > std::numeric_limits<int>::max()) {
        throw std::runtime_error("invalid integer for " + option + ": " + value);
    }
    return static_cast<int>(result);
}

std::uint64_t parse_u64(const std::string& value, const std::string& option) {
    std::size_t parsed = 0;
    const unsigned long long result = std::stoull(value, &parsed, 10);
    if (parsed != value.size()) {
        throw std::runtime_error("invalid integer for " + option + ": " + value);
    }
    return static_cast<std::uint64_t>(result);
}

double parse_double(const std::string& value, const std::string& option) {
    std::size_t parsed = 0;
    const double result = std::stod(value, &parsed);
    if (parsed != value.size() || !std::isfinite(result)) {
        throw std::runtime_error("invalid number for " + option + ": " + value);
    }
    return result;
}

ProgramOptions parse_options(int argc, char** argv) {
    ProgramOptions options;
    for (int index = 1; index < argc; ++index) {
        const std::string arg = argv[index];

        if (arg == "--help" || arg == "-h") {
            options.help = true;
        }
        else if (arg == "--mock") {
            options.use_mock_worker = true;
        }
        else if (arg == "--worker" || arg.rfind("--worker=", 0) == 0) {
            options.worker_executable = require_value(index, argc, argv, "--worker");
        }
        else if (arg == "--worker-arg" || arg.rfind("--worker-arg=", 0) == 0) {
            options.worker_arguments.push_back(
                require_value(index, argc, argv, "--worker-arg"));
        }
        else if (arg == "--cwd" || arg.rfind("--cwd=", 0) == 0) {
            options.working_directory = require_value(index, argc, argv, "--cwd");
        }
        else if (arg == "--text" || arg.rfind("--text=", 0) == 0) {
            options.text = require_value(index, argc, argv, "--text");
        }
        else if (arg == "--language" || arg.rfind("--language=", 0) == 0) {
            options.language = require_value(index, argc, argv, "--language");
        }
        else if (arg == "--speaker" || arg.rfind("--speaker=", 0) == 0) {
            options.speaker = require_value(index, argc, argv, "--speaker");
        }
        else if (arg == "--instruction" || arg.rfind("--instruction=", 0) == 0) {
            options.instruction = require_value(index, argc, argv, "--instruction");
        }
        else if (arg == "--sample-rate" || arg.rfind("--sample-rate=", 0) == 0) {
            options.sample_rate =
                parse_u32(require_value(index, argc, argv, "--sample-rate"), "--sample-rate");
        }
        else if (arg == "--channels" || arg.rfind("--channels=", 0) == 0) {
            options.channels =
                parse_u32(require_value(index, argc, argv, "--channels"), "--channels");
        }
        else if (arg == "--warmups" || arg.rfind("--warmups=", 0) == 0) {
            options.warmups = parse_int(require_value(index, argc, argv, "--warmups"), "--warmups");
        }
        else if (arg == "--requests" || arg.rfind("--requests=", 0) == 0) {
            options.requests = parse_int(require_value(index, argc, argv, "--requests"), "--requests");
        }
        else if (arg == "--cancel-every" || arg.rfind("--cancel-every=", 0) == 0) {
            options.cancel_every = parse_int(
                require_value(index, argc, argv, "--cancel-every"),
                "--cancel-every");
        }
        else if (arg == "--seed" || arg.rfind("--seed=", 0) == 0) {
            options.seed = parse_u64(require_value(index, argc, argv, "--seed"), "--seed");
        }
        else if (arg == "--request-timeout-ms" ||
                 arg.rfind("--request-timeout-ms=", 0) == 0) {
            options.request_timeout = std::chrono::milliseconds(parse_u32(
                require_value(index, argc, argv, "--request-timeout-ms"),
                "--request-timeout-ms"));
        }
        else if (arg == "--startup-timeout-ms" ||
                 arg.rfind("--startup-timeout-ms=", 0) == 0) {
            options.startup_timeout = std::chrono::milliseconds(parse_u32(
                require_value(index, argc, argv, "--startup-timeout-ms"),
                "--startup-timeout-ms"));
        }
        else if (arg == "--mock-chunks" || arg.rfind("--mock-chunks=", 0) == 0) {
            options.mock_chunks =
                parse_int(require_value(index, argc, argv, "--mock-chunks"), "--mock-chunks");
        }
        else if (arg == "--mock-chunk-ms" || arg.rfind("--mock-chunk-ms=", 0) == 0) {
            options.mock_chunk_ms = parse_int(
                require_value(index, argc, argv, "--mock-chunk-ms"),
                "--mock-chunk-ms");
        }
        else if (arg == "--mock-chunk-delay" ||
                 arg.rfind("--mock-chunk-delay=", 0) == 0) {
            options.mock_chunk_delay = parse_double(
                require_value(index, argc, argv, "--mock-chunk-delay"),
                "--mock-chunk-delay");
        }
        else {
            throw std::runtime_error("unknown option: " + arg);
        }
    }

    return options;
}

void validate_options(const ProgramOptions& options) {
    if (options.help) {
        return;
    }
    if (!options.use_mock_worker && options.worker_executable.empty()) {
        throw std::runtime_error("--worker is required unless --mock is used");
    }
    if (options.text.empty()) {
        throw std::runtime_error("--text must not be empty");
    }
    if (options.sample_rate == 0) {
        throw std::runtime_error("--sample-rate must be greater than zero");
    }
    if (options.channels == 0 ||
        options.channels > std::numeric_limits<std::uint16_t>::max()) {
        throw std::runtime_error("--channels must fit into uint16 and be greater than zero");
    }
    if (options.warmups < 0) {
        throw std::runtime_error("--warmups must be non-negative");
    }
    if (options.requests <= 0) {
        throw std::runtime_error("--requests must be greater than zero");
    }
    if (options.cancel_every < 0) {
        throw std::runtime_error("--cancel-every must be non-negative");
    }
    if (options.mock_chunks <= 0) {
        throw std::runtime_error("--mock-chunks must be greater than zero");
    }
    if (options.mock_chunk_ms <= 0) {
        throw std::runtime_error("--mock-chunk-ms must be greater than zero");
    }
    if (options.mock_chunk_delay < 0.0) {
        throw std::runtime_error("--mock-chunk-delay must be non-negative");
    }
}

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

TtsRequest make_request(const ProgramOptions& options, const AudioFormat& audio_format) {
    TtsRequest request;
    request.text = options.text;
    request.language = options.language;
    request.speaker = options.speaker;
    request.instruction = options.instruction;
    if (options.seed.has_value()) {
        request.has_seed = true;
        request.seed = options.seed.value();
    }
    request.output = audio_format;
    return request;
}

RequestResult run_request(
    QwenTtsClient& client,
    const ProgramOptions& options,
    const AudioFormat& audio_format,
    int index,
    bool warmup) {
    RequestProbe probe;
    probe.cancel_after_first_audio =
        !warmup && options.cancel_every > 0 && index % options.cancel_every == 0;
    probe.start = Clock::now();
    const RequestId request_id = client.synthesize_async(
        make_request(options, audio_format),
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

    RequestResult result;
    {
        std::lock_guard<std::mutex> lock(probe.mutex);
        result.index = index;
        result.request_id = request_id;
        result.warmup = warmup;
        result.success = probe.success;
        result.cancelled = probe.cancelled;
        result.first_audio_ms = probe.first_audio_ms;
        result.completed_ms = probe.completed_ms;
        result.enqueue_ms = probe.enqueue_ms;
        result.audio_chunks = probe.audio_chunks;
        result.audio_bytes = probe.audio_bytes;
        result.chunks = probe.chunks;
        result.error_category = probe.error_category;
        result.error_code = probe.error_code;
        result.error_message = probe.error_message;
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
        if (!result.success) {
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
        << "\"language\":\"" << json_escape(options.language) << "\","
        << "\"speaker\":\"" << json_escape(options.speaker) << "\","
        << "\"instruction\":\"" << json_escape(options.instruction) << "\","
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
    out << "\"cancelled_requests\":" << cancelled_count << ","
        << "\"failed_requests\":" << failed_count << ",";
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
                << "\"request_id\":" << result.request_id << ","
                << "\"success\":" << (result.success ? "true" : "false") << ","
                << "\"cancelled\":" << (result.cancelled ? "true" : "false") << ","
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

} // namespace

int main(int argc, char** argv) {
    try {
        ProgramOptions options = parse_options(argc, argv);
        validate_options(options);

        if (options.help) {
            print_usage(std::cout, argv[0]);
            return 0;
        }

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

        for (int index = 0; index < options.warmups; ++index) {
            warmups.push_back(run_request(
                client,
                options,
                audio_format,
                index + 1,
                true));
        }
        for (int index = 0; index < options.requests; ++index) {
            measured.push_back(run_request(
                client,
                options,
                audio_format,
                index + 1,
                false));
        }

        client.stop();
        const auto metrics_by_request = worker_metrics.request_metrics();
        attach_worker_metrics(warmups, metrics_by_request);
        attach_worker_metrics(measured, metrics_by_request);
        write_results_json(std::cout, options, startup_ms, warmups, measured);
        return 0;
    }
    catch (const std::exception& exc) {
        std::cerr << "qwen_tts_latency_benchmark: " << exc.what() << '\n';
        std::cerr << "Run with --help for usage.\n";
        return 1;
    }
}
