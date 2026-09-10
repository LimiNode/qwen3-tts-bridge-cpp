#include <qwen_tts_bridge/client.hpp>
#include <qwen_tts_bridge/transport.hpp>

#include <nlohmann/json.hpp>

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
using qwen_tts_bridge::TtsCompletion;
using qwen_tts_bridge::TtsError;
using qwen_tts_bridge::TtsRequest;

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

void print_usage(std::ostream& out, const char* executable_name) {
    out << "Usage:\n"
        << "  " << executable_name << " --mock --text \"Hello\"\n"
        << "  " << executable_name << " --worker qwen_tts_worker.exe --text \"Hello\"\n\n"
        << "Options:\n"
        << "  --help                         Show this help.\n"
        << "  --self-test-eos-contract       Exercise backend-neutral EOS acceptance branches.\n"
        << "  --mock                         Run the bundled Python mock worker.\n"
        << "  --worker <path>                Worker executable path.\n"
        << "  --worker-arg <arg>             Extra worker argument; may be repeated.\n"
        << "  --cwd <path>                   Worker working directory.\n"
        << "  --text <utf8>                  Text to synthesize.\n"
        << "  --warmup-text <utf8>           Dedicated warmup text; keeps manifest rows measured-only.\n"
        << "  --warmup-reference-audio-path <path>  Optional Base reference for warmup requests.\n"
        << "  --warmup-reference-text <utf8>       Transcript for the warmup reference.\n"
        << "  --terminal-quiet-ms <ms>       Quiet period before lifecycle counters are sampled.\n"
        << "  --language <name>              Request language, default: auto.\n"
        << "  --speaker <name>               Optional request speaker or voice name.\n"
        << "  --voice-id <id>                Registered Base voice profile identifier.\n"
        << "  --instruction <utf8>           Natural-language style instruction.\n"
        << "  --reference-audio-path <path>  Base voice-clone reference WAV.\n"
        << "  --reference-text <utf8>       Reference WAV transcript.\n"
        << "  --x-vector-only               Use speaker embedding without ICL codes.\n"
        << "  --request-manifest <jsonl>     Cycle measured requests through JSONL cases.\n"
        << "  --result-json <path>           Write raw diagnostic JSON to a file.\n"
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
        else if (arg == "--self-test-eos-contract") {
            options.self_test_eos_contract = true;
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
        else if (arg == "--warmup-text" || arg.rfind("--warmup-text=", 0) == 0) {
            options.warmup_text = require_value(index, argc, argv, "--warmup-text");
        }
        else if (arg == "--warmup-reference-audio-path" || arg.rfind("--warmup-reference-audio-path=", 0) == 0) {
            options.warmup_reference_audio_path = require_value(index, argc, argv, "--warmup-reference-audio-path");
        }
        else if (arg == "--warmup-reference-text" || arg.rfind("--warmup-reference-text=", 0) == 0) {
            options.warmup_reference_text = require_value(index, argc, argv, "--warmup-reference-text");
        }
        else if (arg == "--terminal-quiet-ms" || arg.rfind("--terminal-quiet-ms=", 0) == 0) {
            options.terminal_quiet = std::chrono::milliseconds(parse_u32(
                require_value(index, argc, argv, "--terminal-quiet-ms"),
                "--terminal-quiet-ms"));
        }
        else if (arg == "--language" || arg.rfind("--language=", 0) == 0) {
            options.language = require_value(index, argc, argv, "--language");
        }
        else if (arg == "--speaker" || arg.rfind("--speaker=", 0) == 0) {
            options.speaker = require_value(index, argc, argv, "--speaker");
        }
        else if (arg == "--voice-id" || arg.rfind("--voice-id=", 0) == 0) {
            options.voice_id = require_value(index, argc, argv, "--voice-id");
        }
        else if (arg == "--instruction" || arg.rfind("--instruction=", 0) == 0) {
            options.instruction = require_value(index, argc, argv, "--instruction");
        }
        else if (arg == "--reference-audio-path" || arg.rfind("--reference-audio-path=", 0) == 0) {
            options.reference_audio_path = require_value(index, argc, argv, "--reference-audio-path");
        }
        else if (arg == "--reference-text" || arg.rfind("--reference-text=", 0) == 0) {
            options.reference_text = require_value(index, argc, argv, "--reference-text");
        }
        else if (arg == "--x-vector-only") {
            options.x_vector_only = true;
        }
        else if (arg == "--request-manifest" || arg.rfind("--request-manifest=", 0) == 0) {
            options.request_manifest = require_value(index, argc, argv, "--request-manifest");
        }
        else if (arg == "--result-json" || arg.rfind("--result-json=", 0) == 0) {
            options.result_json_path = require_value(index, argc, argv, "--result-json");
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
    if (options.terminal_quiet.count() < 0) {
        throw std::runtime_error("--terminal-quiet-ms must be non-negative");
    }
    if (!options.warmup_reference_audio_path.empty() &&
        options.warmup_reference_text.empty()) {
        throw std::runtime_error(
            "--warmup-reference-text is required with --warmup-reference-audio-path");
    }
    if (!options.voice_id.empty() && !options.warmup_reference_audio_path.empty()) {
        throw std::runtime_error(
            "--voice-id cannot be combined with --warmup-reference-audio-path");
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

std::vector<RequestSpec> load_request_manifest(const ProgramOptions& options) {
    if (options.request_manifest.empty()) {
        return {};
    }

    std::ifstream input(options.request_manifest);
    if (!input) {
        throw std::runtime_error("failed to open --request-manifest");
    }

    std::vector<RequestSpec> specs;
    std::string line;
    int line_number = 0;
    while (std::getline(input, line)) {
        ++line_number;
        if (line.empty()) {
            continue;
        }
        const nlohmann::json value = nlohmann::json::parse(line);
        RequestSpec spec;
        spec.label = value.at("label").get<std::string>();
        spec.text = value.at("text").get<std::string>();
        spec.language = value.value("language", options.language);
        spec.speaker = value.value("speaker", options.speaker);
        spec.voice_id = value.value("voice_id", options.voice_id);
        spec.instruction = value.value("instruction", options.instruction);
        spec.reference_audio_path = value.value("reference_audio_path", options.reference_audio_path);
        spec.reference_text = value.value("reference_text", options.reference_text);
        spec.x_vector_only = value.value("x_vector_only", options.x_vector_only);
        if (value.contains("seed")) {
            spec.seed = value.at("seed").get<std::uint64_t>();
        }
        if (value.contains("allowed_terminal_outcomes")) {
            spec.allowed_terminal_outcomes =
                value.at("allowed_terminal_outcomes").get<std::vector<std::string>>();
            if (spec.allowed_terminal_outcomes.empty() ||
                std::any_of(spec.allowed_terminal_outcomes.begin(),
                    spec.allowed_terminal_outcomes.end(),
                    [](const std::string& outcome) { return outcome.empty(); })) {
                throw std::runtime_error(
                    "--request-manifest line " + std::to_string(line_number) +
                    " has invalid allowed_terminal_outcomes");
            }
        }
        spec.expected_error_category = value.value("expected_error_category", "");
        spec.expected_error_code = value.value("expected_error_code", "");
        if (value.contains("allowed_errors")) {
            for (const auto& error : value.at("allowed_errors")) {
                if (!error.is_object() || !error.contains("category") ||
                    !error.contains("code")) {
                    throw std::runtime_error(
                        "--request-manifest line " + std::to_string(line_number) +
                        " has invalid allowed_errors");
                }
                const std::string category = error.at("category").get<std::string>();
                const std::string code = error.at("code").get<std::string>();
                if (category.empty() || code.empty()) {
                    throw std::runtime_error(
                        "--request-manifest line " + std::to_string(line_number) +
                        " has empty allowed error category/code");
                }
                spec.allowed_errors.emplace_back(category, code);
            }
            if (spec.allowed_errors.empty()) {
                throw std::runtime_error(
                    "--request-manifest line " + std::to_string(line_number) +
                    " has empty allowed_errors");
            }
        }
        spec.cancel_after_first_pcm = value.value("cancel_after_first_pcm", false);
        if (!spec.expected_error_code.empty() && spec.expected_error_category.empty()) {
            throw std::runtime_error(
                "--request-manifest line " + std::to_string(line_number) +
                " expected_error_code requires expected_error_category");
        }
        const bool has_any_contract_field =
            value.contains("expected_prefill_length") ||
            value.contains("expected_route") ||
            value.contains("expected_backend") ||
            value.contains("expected_chunk_schedule");
        if (has_any_contract_field) {
            if (!value.contains("expected_prefill_length") ||
                !value.contains("expected_route") ||
                !value.contains("expected_backend") ||
                !value.contains("expected_chunk_schedule")) {
                throw std::runtime_error(
                    "--request-manifest line " + std::to_string(line_number) +
                    " must provide all expected_* contract fields");
            }
            spec.expected_prefill_length =
                value.at("expected_prefill_length").get<int>();
            spec.expected_route = value.at("expected_route").get<std::string>();
            spec.expected_backend = value.at("expected_backend").get<std::string>();
            spec.expected_chunk_schedule =
                value.at("expected_chunk_schedule").get<std::vector<int>>();
            if (spec.expected_prefill_length.value() <= 0 ||
                spec.expected_route.empty() || spec.expected_backend.empty() ||
                spec.expected_chunk_schedule.empty() ||
                std::any_of(
                    spec.expected_chunk_schedule.begin(),
                    spec.expected_chunk_schedule.end(),
                    [](int steps) { return steps <= 0; })) {
                throw std::runtime_error(
                    "--request-manifest line " + std::to_string(line_number) +
                    " has an invalid expected_* contract");
            }
            if (spec.expected_route != "compiled_allowlist" &&
                spec.expected_route != "eager_unknown") {
                throw std::runtime_error(
                    "--request-manifest line " + std::to_string(line_number) +
                    " has unsupported expected_route");
            }
        }
        if (spec.label.empty() || spec.text.empty()) {
            throw std::runtime_error(
                "--request-manifest line " + std::to_string(line_number) +
                " requires non-empty label and text");
        }
        specs.push_back(std::move(spec));
    }
    if (specs.empty()) {
        throw std::runtime_error("--request-manifest contains no request cases");
    }
    return specs;
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

bool json_field_equals(
    const nlohmann::json& value,
    const char* field,
    const nlohmann::json& expected) {
    const auto found = value.find(field);
    return found != value.end() && *found == expected;
}

void fail_contract(RequestResult& result, std::string message) {
    result.contract_valid = false;
    result.contract_failures.push_back(std::move(message));
}

void validate_request_contract(RequestResult& result) {
    result.contract_checked = result.expected_prefill_length.has_value();
    if (!result.contract_checked) {
        return;
    }
    if (!result.success && !result.cancelled) {
        fail_contract(result, "request did not complete successfully");
        return;
    }
    if (result.cancelled && result.audio_chunks == 0u) {
        fail_contract(result, "cancelled request has no PCM prefix to validate");
        return;
    }

    const nlohmann::json& phases = result.worker_first_chunk_phases;
    if (!phases.is_object()) {
        fail_contract(result, "missing request_first_chunk_engine_phases telemetry");
        return;
    }
    const auto require = [&result, &phases](const char* field, const nlohmann::json& expected) {
        if (!json_field_equals(phases, field, expected)) {
            fail_contract(
                result,
                std::string("expected ") + field + "=" + expected.dump());
        }
    };
    require("talker_prefill_length", result.expected_prefill_length.value());
    require("prefill_shape_policy", result.expected_route);
    require("prefill_backend_used", result.expected_backend);
    require("prefill_compile_attempted", false);
    require("prefill_compile_fallback", false);
    require("prefill_compile_cache_entries_delta", 0);
    require("prefill_dynamo_unique_graphs_delta", 0);
    require("prefill_require_precompiled", true);

    if (result.expected_route == "compiled_allowlist") {
        require("prefill_compile_cache_hit", true);
        require("prefill_shape_allowlist_hit", true);
        require("prefill_backend_used", "compile_reduce_overhead");
        const auto ordinal = phases.find("prefill_shape_call_ordinal");
        if (ordinal == phases.end() || !ordinal->is_number_integer() ||
            ordinal->get<int>() < 4) {
            fail_contract(result, "compiled route lacks warmed prefill shape ordinal");
        }
    }
    else {
        require("prefill_compile_cache_hit", false);
        require("prefill_shape_allowlist_hit", false);
        require("prefill_backend_used", "eager");
    }

    if (result.worker_pcm_chunks.size() != result.audio_chunks) {
        fail_contract(result, "worker and C++ PCM chunk counts differ");
    }
    for (std::size_t index = 0; index < result.worker_pcm_chunks.size(); ++index) {
        const nlohmann::json& chunk = result.worker_pcm_chunks[index];
        if (!chunk.is_object()) {
            fail_contract(result, "worker PCM telemetry entry is not an object");
            continue;
        }
        const int target = result.expected_chunk_schedule[
            std::min(index, result.expected_chunk_schedule.size() - 1u)];
        if (!json_field_equals(chunk, "chunk_target_steps", target)) {
            fail_contract(
                result,
                "chunk " + std::to_string(index) + " has unexpected target steps");
        }
        const auto steps = chunk.find("chunk_steps");
        if (steps == chunk.end() || !steps->is_number_integer() ||
            steps->get<int>() <= 0 || steps->get<int>() > target) {
            fail_contract(result, "chunk " + std::to_string(index) + " has invalid step count");
            continue;
        }
        const bool terminal_chunk = index + 1u == result.worker_pcm_chunks.size();
        if (!terminal_chunk && steps->get<int>() != target) {
            fail_contract(result, "non-terminal chunk is shorter than its target");
        }
    }
    if (result.cancelled) {
        if (!result.worker_finished.is_object() ||
            !json_field_equals(result.worker_finished, "terminal_state", "cancelled")) {
            fail_contract(result, "missing cancelled request_finished telemetry");
        }
        return;
    }
    if (!result.worker_generation_trace.is_object()) {
        fail_contract(result, "missing request_generation_trace telemetry");
    }
    if (!result.worker_finished.is_object() ||
        !json_field_equals(result.worker_finished, "terminal_state", "completed")) {
        fail_contract(result, "missing completed request_finished telemetry");
    }
}

void fail_acceptance(RequestResult& result, std::string message) {
    result.acceptance_valid = false;
    result.acceptance_failures.push_back(std::move(message));
}

void validate_generic_acceptance(RequestResult& result) {
    const bool has_expected_error = !result.expected_error_category.empty() ||
        !result.expected_error_code.empty();
    if (!result.allowed_terminal_outcomes.empty() || !result.allowed_errors.empty() ||
        has_expected_error) {
        std::string actual;
        if (result.success) {
            actual = result.completion_execution_outcome.value_or("completed");
        } else if (result.cancelled) {
            actual = "cancelled";
        } else {
            actual = result.error_category;
        }
        bool terminal_allowed = std::find(result.allowed_terminal_outcomes.begin(),
            result.allowed_terminal_outcomes.end(), actual) !=
            result.allowed_terminal_outcomes.end();
        if (!result.success && !result.cancelled) {
            terminal_allowed = std::any_of(result.allowed_errors.begin(),
                result.allowed_errors.end(),
                [&result](const auto& allowed) {
                    return allowed.first == result.error_category &&
                        allowed.second == result.error_code;
                });
            if (has_expected_error &&
                (result.expected_error_category.empty() ||
                 result.error_category == result.expected_error_category) &&
                (result.expected_error_code.empty() ||
                 result.error_code == result.expected_error_code)) {
                terminal_allowed = true;
            }
        }
        if (!terminal_allowed) {
            fail_acceptance(result, "terminal outcome '" + actual + "' was not allowed");
        }
        if (!result.success && !result.cancelled &&
            !result.expected_error_category.empty() &&
            result.error_category != result.expected_error_category) {
            fail_acceptance(result, "unexpected error category");
        }
        if (!result.success && !result.cancelled &&
            !result.expected_error_code.empty() &&
            result.error_code != result.expected_error_code) {
            fail_acceptance(result, "unexpected error code");
        }
        if (has_expected_error && result.success) {
            fail_acceptance(result, "expected an error but request completed");
        }
    }
    if (result.cancellation_expected) {
        if (!result.cancelled) {
            fail_acceptance(result, "expected cancellation did not occur");
        }
        if (result.success) {
            fail_acceptance(result, "request completed despite expected cancellation");
        }
    }
    else {
        if (result.cancelled) {
            fail_acceptance(result, "unexpected cancellation");
        }
        if (!result.success && result.allowed_terminal_outcomes.empty() &&
            result.allowed_errors.empty() && !has_expected_error) {
            fail_acceptance(result, "request failed");
        }
    }

    if (result.success && (result.audio_bytes == 0u || result.audio_chunks == 0u)) {
        fail_acceptance(result, "completed request produced no PCM");
    }
    if (result.success && result.completion_execution_outcome.has_value() &&
        result.completion_execution_outcome.value() == "max_tokens") {
            fail_acceptance(result, "request exhausted max_new_tokens before natural EOS");
    }
    if (result.success && !result.completion_metadata.has_value()) {
        fail_acceptance(result, "completed request has no completion metadata/EOS evidence");
    }
    if (result.success && result.completion_metadata.has_value()) {
        const TtsCompletion& completion = result.completion_metadata.value();
        if (!completion.has_generation_trace && completion.execution_outcome == "natural_eos") {
            // Native workers may provide an explicit finish outcome without
            // exposing model-specific generation trace fields.
        } else if (!completion.has_generation_trace) {
            fail_acceptance(result, "completed request has no generation trace/EOS evidence");
        } else if (!completion.hit_eos || completion.hit_max_seq_len ||
                   completion.hit_max_new_tokens || completion.termination_reason != "eos") {
            fail_acceptance(result, "generation trace did not report natural EOS");
        }
    }
    if (result.cancelled && result.audio_bytes == 0u) {
        fail_acceptance(result, "cancelled request produced no PCM prefix");
    }
    if (result.late_audio_after_terminal_count != 0u) {
        fail_acceptance(result, "audio arrived after request terminal state");
    }
    if (result.duplicate_terminal_event_count != 0u) {
        fail_acceptance(result, "duplicate terminal event arrived after request terminal state");
    }
}

bool has_contract_failures(const std::vector<RequestResult>& results) {
    return std::any_of(
        results.begin(),
        results.end(),
        [](const RequestResult& result) {
            return result.contract_checked && !result.contract_valid;
        });
}

bool has_acceptance_failures(const std::vector<RequestResult>& results) {
    return std::any_of(
        results.begin(),
        results.end(),
        [](const RequestResult& result) { return !result.acceptance_valid; });
}

int run_eos_contract_self_test() {
    auto make_result = [](const std::string& outcome) {
        RequestResult result;
        result.success = true;
        result.audio_bytes = 2;
        result.audio_chunks = 1;
        TtsCompletion completion;
        completion.execution_outcome = outcome;
        completion.has_generation_trace = false;
        result.completion_execution_outcome = outcome;
        result.completion_metadata = completion;
        return result;
    };

    RequestResult native_natural = make_result("natural_eos");
    validate_generic_acceptance(native_natural);
    if (!native_natural.acceptance_valid) {
        std::cerr << "EOS self-test: native natural_eos was rejected\n";
        return 1;
    }

    RequestResult bare_completed = make_result("completed");
    validate_generic_acceptance(bare_completed);
    if (bare_completed.acceptance_valid) {
        std::cerr << "EOS self-test: bare completed was accepted\n";
        return 1;
    }

    RequestResult max_tokens = make_result("max_tokens");
    validate_generic_acceptance(max_tokens);
    if (max_tokens.acceptance_valid) {
        std::cerr << "EOS self-test: max_tokens was accepted\n";
        return 1;
    }
    return 0;
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
