#include <qwen_tts_bridge/client.hpp>
#include <qwen_tts_bridge/integration/speech_animation/SpeechAnimationAdapter.hpp>
#include <qwen_tts_bridge/transport.hpp>

#include <nlohmann/json.hpp>

#include <algorithm>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <functional>
#include <iomanip>
#include <iostream>
#include <iterator>
#include <limits>
#include <memory>
#include <mutex>
#include <optional>
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>
#include <vector>

namespace {

using Clock = std::chrono::steady_clock;
using qwen_tts_bridge::PcmChunk;
using qwen_tts_bridge::QwenTtsClient;
using qwen_tts_bridge::QwenTtsClientOptions;
using qwen_tts_bridge::RequestId;
using qwen_tts_bridge::StdIoTransportOptions;
using qwen_tts_bridge::TtsCallbacks;
using qwen_tts_bridge::TtsCompletion;
using qwen_tts_bridge::TtsError;
using qwen_tts_bridge::TtsRequest;
using SpeechAnimationAdapter = qwen_tts_bridge::speech_animation::SpeechAnimationAdapter;
using PipelineConfig = speech_animation::integration::PipelineConfig;
using QueuePushResult = speech_animation::integration::QueuePushResult;
using Receipt = speech_animation::integration::SpeechAnimationReceipt;
using ReceiptKind = speech_animation::integration::SpeechAnimationReceiptKind;

struct Options {
    bool adapter_enabled = false;
    std::string worker;
    std::vector<std::string> worker_arguments;
    std::string working_directory;
    std::string text;
    std::string text_file;
    std::string language = "auto";
    std::string speaker;
    std::string instruction;
    std::string voice_id;
    std::string reference_audio_path;
    std::string reference_text;
    bool x_vector_only = false;
    bool has_seed = false;
    std::uint64_t seed = 0;
    std::string output_json;
    std::size_t queue_capacity = 64;
    std::uint32_t consumer_poll_ms = 2;
    std::uint32_t sample_rate = 24000;
    std::uint32_t channels = 1;
    std::uint32_t startup_timeout_ms = 30000;
    std::uint32_t request_timeout_ms = 120000;
};

struct PcmObservation {
    RequestId request_id = 0;
    std::uint64_t first_sample = 0;
    std::uint32_t sample_count = 0;
    std::uint32_t sample_rate = 0;
    double callback_ms = 0.0;
    double downstream_callback_ms = 0.0;
    double callback_total_ms = 0.0;
    double adapter_ms = 0.0;
};

struct ReceiptObservation {
    Receipt receipt;
    double available_ms = 0.0;
};

struct ProbeState {
    Clock::time_point synthesis_started;
    std::mutex mutex;
    std::condition_variable condition;
    bool terminal = false;
    std::string terminal_state;
    std::optional<TtsCompletion> completion;
    std::optional<TtsError> error;
    std::vector<PcmObservation> pcm;
    std::vector<ReceiptObservation> receipts;
    std::vector<SpeechAnimationAdapter::AdapterDiagnostic> diagnostics;
    std::size_t queue_high_water = 0;
    bool consumer_stop = false;
};

[[noreturn]] void usage_error(const std::string& message) {
    throw std::invalid_argument(message +
        "\nUse --help for qwen_tts_speech_animation_probe options.");
}

std::string require_value(
    int& index,
    int argc,
    char** argv,
    const std::string& option) {
    if (index + 1 >= argc) {
        usage_error(option + " requires a value");
    }
    return argv[++index];
}

std::uint64_t parse_uint64(const std::string& value, const std::string& option) {
    try {
        std::size_t consumed = 0;
        const auto parsed = std::stoull(value, &consumed, 10);
        if (consumed != value.size()) {
            usage_error(option + " must be an unsigned decimal integer");
        }
        return parsed;
    }
    catch (const std::exception&) {
        usage_error(option + " must be an unsigned decimal integer");
    }
}

std::string require_option_value(
    int& index,
    int argc,
    char** argv,
    const std::string& argument,
    const std::string& option) {
    if (argument == option) {
        return require_value(index, argc, argv, option);
    }
    const auto prefix = option + "=";
    if (argument.rfind(prefix, 0) == 0) {
        return argument.substr(prefix.size());
    }
    return {};
}

void print_help() {
    std::cout
        << "qwen_tts_speech_animation_probe\n"
        << "  --worker <path>                 Worker executable\n"
        << "  --worker-arg <value>            Repeat for worker arguments\n"
        << "  --cwd <path>                    Worker working directory\n"
        << "  --adapter on|off                Enable optional animation adapter\n"
        << "  --text <utf8>                   Spoken text\n"
        << "  --text-file <path>              Read spoken UTF-8 bytes from a file\n"
        << "  --language <name>               Language (default: auto)\n"
        << "  --speaker <id>                  Optional CustomVoice speaker\n"
        << "  --voice-id <id>                 Optional registered Base voice\n"
        << "  --reference-audio <path>        Optional Base clone reference\n"
        << "  --reference-text <utf8>         Reference transcript\n"
        << "  --x-vector-only                Base x-vector-only clone mode\n"
        << "  --seed <integer>                Optional deterministic request seed\n"
        << "  --output-json <path>            Receipt output path\n"
        << "  --queue-capacity <integer>      Animation queue slots (default: 64)\n"
        << "  --consumer-poll-ms <integer>   Consumer poll interval (default: 2)\n"
        << "  --sample-rate <integer>         Requested PCM sample rate\n"
        << "  --channels <integer>            Requested PCM channels\n"
        << "  --startup-timeout-ms <integer>  Worker ready timeout\n"
        << "  --request-timeout-ms <integer>  Synthesis timeout\n"
        << "  --help                          Show this help\n";
}

Options parse_options(int argc, char** argv) {
    Options options;
    for (int index = 1; index < argc; ++index) {
        const std::string argument = argv[index];
        if (argument == "--help") {
            print_help();
            std::exit(EXIT_SUCCESS);
        }
        if (argument == "--x-vector-only") {
            options.x_vector_only = true;
            continue;
        }

        auto value = require_option_value(index, argc, argv, argument, "--worker");
        if (!value.empty()) {
            options.worker = std::move(value);
            continue;
        }
        if (argument == "--worker-arg" || argument.rfind("--worker-arg=", 0) == 0) {
            options.worker_arguments.push_back(
                require_option_value(index, argc, argv, argument, "--worker-arg"));
            continue;
        }
        value = require_option_value(index, argc, argv, argument, "--cwd");
        if (!value.empty()) {
            options.working_directory = std::move(value);
            continue;
        }
        value = require_option_value(index, argc, argv, argument, "--adapter");
        if (!value.empty()) {
            if (value == "on") {
                options.adapter_enabled = true;
            }
            else if (value == "off") {
                options.adapter_enabled = false;
            }
            else {
                usage_error("--adapter must be on or off");
            }
            continue;
        }
        value = require_option_value(index, argc, argv, argument, "--text");
        if (!value.empty()) { options.text = std::move(value); continue; }
        value = require_option_value(index, argc, argv, argument, "--text-file");
        if (!value.empty()) { options.text_file = std::move(value); continue; }
        value = require_option_value(index, argc, argv, argument, "--language");
        if (!value.empty()) { options.language = std::move(value); continue; }
        value = require_option_value(index, argc, argv, argument, "--speaker");
        if (!value.empty()) { options.speaker = std::move(value); continue; }
        value = require_option_value(index, argc, argv, argument, "--instruction");
        if (!value.empty()) { options.instruction = std::move(value); continue; }
        value = require_option_value(index, argc, argv, argument, "--voice-id");
        if (!value.empty()) { options.voice_id = std::move(value); continue; }
        value = require_option_value(index, argc, argv, argument, "--reference-audio");
        if (!value.empty()) { options.reference_audio_path = std::move(value); continue; }
        value = require_option_value(index, argc, argv, argument, "--reference-text");
        if (!value.empty()) { options.reference_text = std::move(value); continue; }
        value = require_option_value(index, argc, argv, argument, "--output-json");
        if (!value.empty()) { options.output_json = std::move(value); continue; }

        value = require_option_value(index, argc, argv, argument, "--seed");
        if (!value.empty()) {
            options.has_seed = true;
            options.seed = parse_uint64(value, "--seed");
            continue;
        }
        value = require_option_value(index, argc, argv, argument, "--queue-capacity");
        if (!value.empty()) { options.queue_capacity = static_cast<std::size_t>(parse_uint64(value, "--queue-capacity")); continue; }
        value = require_option_value(index, argc, argv, argument, "--consumer-poll-ms");
        if (!value.empty()) { options.consumer_poll_ms = static_cast<std::uint32_t>(parse_uint64(value, "--consumer-poll-ms")); continue; }
        value = require_option_value(index, argc, argv, argument, "--sample-rate");
        if (!value.empty()) { options.sample_rate = static_cast<std::uint32_t>(parse_uint64(value, "--sample-rate")); continue; }
        value = require_option_value(index, argc, argv, argument, "--channels");
        if (!value.empty()) { options.channels = static_cast<std::uint32_t>(parse_uint64(value, "--channels")); continue; }
        value = require_option_value(index, argc, argv, argument, "--startup-timeout-ms");
        if (!value.empty()) { options.startup_timeout_ms = static_cast<std::uint32_t>(parse_uint64(value, "--startup-timeout-ms")); continue; }
        value = require_option_value(index, argc, argv, argument, "--request-timeout-ms");
        if (!value.empty()) { options.request_timeout_ms = static_cast<std::uint32_t>(parse_uint64(value, "--request-timeout-ms")); continue; }
        usage_error("unknown option: " + argument);
    }
    if (options.worker.empty()) usage_error("--worker is required");
    if (!options.text.empty() && !options.text_file.empty()) {
        usage_error("--text and --text-file are mutually exclusive");
    }
    if (!options.text_file.empty()) {
        std::ifstream input(std::filesystem::u8path(options.text_file), std::ios::binary);
        if (!input) usage_error("failed to open --text-file: " + options.text_file);
        options.text.assign(
            std::istreambuf_iterator<char>(input),
            std::istreambuf_iterator<char>());
        if (options.text.size() >= 3 &&
            static_cast<unsigned char>(options.text[0]) == 0xEFu &&
            static_cast<unsigned char>(options.text[1]) == 0xBBu &&
            static_cast<unsigned char>(options.text[2]) == 0xBFu) {
            options.text.erase(0, 3);
        }
    }
    if (options.text.empty()) usage_error("--text or --text-file is required");
    if (options.output_json.empty()) usage_error("--output-json is required");
    if (options.queue_capacity == 0 || options.sample_rate == 0 || options.channels == 0) {
        usage_error("queue capacity, sample rate, and channels must be greater than zero");
    }
    return options;
}

double elapsed_ms(const Clock::time_point start, const Clock::time_point end) {
    return std::chrono::duration<double, std::milli>(end - start).count();
}

bool contiguous_pcm(const std::vector<PcmObservation>& chunks, std::uint64_t& end) {
    if (chunks.empty()) return false;
    end = chunks.front().first_sample;
    for (const auto& chunk : chunks) {
        if (chunk.first_sample != end) return false;
        end += chunk.sample_count;
    }
    return true;
}

std::vector<const ReceiptObservation*> audio_receipts(
    const std::vector<ReceiptObservation>& observations) {
    std::vector<const ReceiptObservation*> result;
    for (const auto& observation : observations) {
        if (!observation.receipt.terminal &&
            observation.receipt.kind == ReceiptKind::AudioSpan &&
            observation.receipt.output_sample_count != 0) {
            result.push_back(&observation);
        }
    }
    return result;
}

bool contiguous_animation(
    const std::vector<const ReceiptObservation*>& spans,
    std::uint64_t& end) {
    if (spans.empty()) return false;
    end = spans.front()->receipt.output_first_sample;
    for (const auto* observation : spans) {
        const auto& receipt = observation->receipt;
        if (receipt.output_first_sample != end) return false;
        end += receipt.output_sample_count;
    }
    return true;
}

nlohmann::json receipt_json(const Receipt& receipt) {
    return {
        {"kind", receipt.kind == ReceiptKind::AudioSpan ? "audio_span" : "terminal_fade"},
        {"request_id", receipt.request_id},
        {"input_first_sample", receipt.input_first_sample},
        {"input_sample_count", receipt.input_sample_count},
        {"output_first_sample", receipt.output_first_sample},
        {"output_sample_count", receipt.output_sample_count},
        {"sample_rate", receipt.sample_rate},
        {"activity", receipt.activity == speech_animation::SpeechActivity::Active ? "active" : "silence"},
        {"mouth_open", receipt.mouth_open},
        {"terminal", receipt.terminal},
        {"terminal_fade_sample_count", receipt.terminal_fade_sample_count}
    };
}

nlohmann::json run_probe(const Options& options) {
    ProbeState state;
    std::shared_ptr<SpeechAnimationAdapter::Pipeline> pipeline;
    std::unique_ptr<SpeechAnimationAdapter> adapter;
    if (options.adapter_enabled) {
        PipelineConfig config;
        config.queue_capacity = options.queue_capacity;
        pipeline = std::make_shared<SpeechAnimationAdapter::Pipeline>(config);
        adapter = std::make_unique<SpeechAnimationAdapter>(
            pipeline,
            SpeechAnimationAdapter::ReceiptHandler{},
            [&state](const SpeechAnimationAdapter::AdapterDiagnostic& diagnostic) {
                std::lock_guard<std::mutex> lock(state.mutex);
                state.diagnostics.push_back(diagnostic);
            });
        if (adapter->begin(1, 0, options.sample_rate) != QueuePushResult::Accepted) {
            throw std::runtime_error("speech-animation pipeline begin() was rejected");
        }
    }

    std::thread consumer;
    const auto start_consumer = [&]() {
        if (!adapter) {
            return;
        }
        consumer = std::thread([&state, &adapter, &pipeline, &options]() {
            while (true) {
                const auto receipts = adapter->process_available();
                if (!receipts.empty()) {
                    const double available_ms = elapsed_ms(
                        state.synthesis_started,
                        Clock::now());
                    std::lock_guard<std::mutex> lock(state.mutex);
                    for (const auto& receipt : receipts) {
                        state.receipts.push_back({receipt, available_ms});
                    }
                }
                {
                    std::lock_guard<std::mutex> lock(state.mutex);
                    state.queue_high_water = std::max(
                        state.queue_high_water,
                        pipeline->queued_chunks());
                    if (state.consumer_stop) return;
                }
                std::this_thread::sleep_for(
                    std::chrono::milliseconds(options.consumer_poll_ms));
            }
        });
    };

    const auto stop_consumer = [&]() {
        if (!consumer.joinable()) {
            return;
        }
        {
            std::lock_guard<std::mutex> lock(state.mutex);
            state.consumer_stop = true;
            state.condition.notify_all();
        }
        consumer.join();
    };

    StdIoTransportOptions transport;
    transport.arguments.push_back(options.worker);
    transport.arguments.insert(
        transport.arguments.end(),
        options.worker_arguments.begin(),
        options.worker_arguments.end());
    transport.working_directory = options.working_directory;
    transport.stderr_handler = [](std::string text) { std::cerr << text; };

    QwenTtsClientOptions client_options;
    client_options.session.startup_timeout =
        std::chrono::milliseconds(options.startup_timeout_ms);
    QwenTtsClient client;
    if (!client.start(transport, client_options)) {
        stop_consumer();
        throw std::runtime_error("failed to start Qwen worker");
    }

    double downstream_duration_ms = 0.0;
    std::optional<std::size_t> current_audio_index;
    Clock::time_point callback_start{};
    TtsCallbacks downstream;
    downstream.on_audio = [&](const PcmChunk& chunk) {
        const auto downstream_start = Clock::now();
        const double downstream_ms = elapsed_ms(state.synthesis_started, downstream_start);
        const auto downstream_end = Clock::now();
        downstream_duration_ms = elapsed_ms(downstream_start, downstream_end);
        std::lock_guard<std::mutex> lock(state.mutex);
        state.pcm.push_back({
            chunk.request_id,
            chunk.first_sample,
            chunk.sample_count,
            chunk.format.sample_rate,
            elapsed_ms(state.synthesis_started, callback_start),
            downstream_ms,
            0.0,
            0.0});
        current_audio_index = state.pcm.size() - 1;
    };
    downstream.on_completed = [&state]() {
        std::lock_guard<std::mutex> lock(state.mutex);
        state.terminal = true;
        state.terminal_state = "completed";
        state.condition.notify_all();
    };
    downstream.on_cancelled = [&state]() {
        std::lock_guard<std::mutex> lock(state.mutex);
        state.terminal = true;
        state.terminal_state = "cancelled";
        state.condition.notify_all();
    };
    downstream.on_error = [&state](const TtsError& error) {
        std::lock_guard<std::mutex> lock(state.mutex);
        state.error = error;
        state.terminal = true;
        state.terminal_state = "error";
        state.condition.notify_all();
    };
    downstream.on_completion_metadata = [&state](const TtsCompletion& completion) {
        std::lock_guard<std::mutex> lock(state.mutex);
        state.completion = completion;
    };

    TtsCallbacks callbacks = adapter
        ? adapter->make_callbacks(std::move(downstream))
        : std::move(downstream);
    auto original_audio = callbacks.on_audio;
    callbacks.on_audio = [&, original_audio](const PcmChunk& chunk) {
        callback_start = Clock::now();
        current_audio_index.reset();
        original_audio(chunk);
        const double total_ms = elapsed_ms(callback_start, Clock::now());
        if (current_audio_index.has_value()) {
            std::lock_guard<std::mutex> lock(state.mutex);
            auto& observation = state.pcm[current_audio_index.value()];
            observation.callback_total_ms = total_ms;
            observation.adapter_ms = options.adapter_enabled
                ? std::max(0.0, total_ms - downstream_duration_ms)
                : 0.0;
            if (pipeline) {
                state.queue_high_water = std::max(
                    state.queue_high_water,
                    pipeline->queued_chunks());
            }
        }
    };

    TtsRequest request;
    request.id = 1;
    request.text = options.text;
    request.language = options.language;
    request.speaker = options.speaker;
    request.instruction = options.instruction;
    request.voice_id = options.voice_id;
    request.reference_audio_path = options.reference_audio_path;
    request.reference_text = options.reference_text;
    request.x_vector_only = options.x_vector_only;
    request.has_seed = options.has_seed;
    request.seed = options.seed;
    request.output.sample_rate = options.sample_rate;
    request.output.channels = options.channels;
    request.output.sample_format = "s16le";

    state.synthesis_started = Clock::now();
    start_consumer();
    const auto request_id = client.synthesize_async(std::move(request), std::move(callbacks));
    if (request_id != 1) {
        client.stop();
        stop_consumer();
        throw std::runtime_error("failed to enqueue request with id 1");
    }

    {
        std::unique_lock<std::mutex> lock(state.mutex);
        if (!state.condition.wait_for(
                lock,
                std::chrono::milliseconds(options.request_timeout_ms),
                [&state]() { return state.terminal; })) {
            client.cancel(request_id);
            state.condition.wait_for(lock, std::chrono::seconds(10), [&state]() {
                return state.terminal;
            });
        }
    }
    client.stop();
    stop_consumer();
    if (adapter) {
        // Drain terminal receipts after the consumer observed the terminal
        // callback. No analyzer work runs on the Qwen callback thread.
        const auto receipts = adapter->process_available();
        const double available_ms = elapsed_ms(state.synthesis_started, Clock::now());
        for (const auto& receipt : receipts) {
            state.receipts.push_back({receipt, available_ms});
        }
    }

    nlohmann::json report;
    report["schema_version"] = 1;
    report["experiment"] = "qwen_speech_animation_e2e";
    report["adapter_enabled"] = options.adapter_enabled;
    report["worker"] = options.worker;
    report["worker_arguments"] = options.worker_arguments;
    report["request_id"] = request_id;
    report["text"] = options.text;
    report["text_source"] = options.text_file.empty() ? "command_line" : "utf8_file";
    report["text_file"] = options.text_file;
    report["language"] = options.language;
    report["speaker"] = options.speaker;
    report["voice_id"] = options.voice_id;
    report["sample_rate"] = options.sample_rate;
    report["channels"] = options.channels;
    report["terminal_state"] = state.terminal_state;
    report["queue_capacity"] = options.adapter_enabled ? options.queue_capacity : 0;
    report["queue_high_water"] = state.queue_high_water;

    nlohmann::json pcm_json = nlohmann::json::array();
    double adapter_total_ms = 0.0;
    double adapter_max_ms = 0.0;
    for (const auto& chunk : state.pcm) {
        adapter_total_ms += chunk.adapter_ms;
        adapter_max_ms = std::max(adapter_max_ms, chunk.adapter_ms);
        pcm_json.push_back({
            {"request_id", chunk.request_id},
            {"first_sample", chunk.first_sample},
            {"sample_count", chunk.sample_count},
            {"sample_rate", chunk.sample_rate},
            {"callback_ms", chunk.callback_ms},
            {"downstream_callback_ms", chunk.downstream_callback_ms},
            {"callback_total_ms", chunk.callback_total_ms},
            {"adapter_ms", chunk.adapter_ms}
        });
    }
    report["pcm_chunks"] = std::move(pcm_json);

    nlohmann::json receipts_json = nlohmann::json::array();
    std::optional<double> first_animation_ms;
    std::optional<Receipt> terminal_receipt;
    std::size_t active_span_count = 0;
    std::size_t silence_span_count = 0;
    double mouth_open_total = 0.0;
    double mouth_open_min = 1.0;
    double mouth_open_max = 0.0;
    for (const auto& observation : state.receipts) {
        auto receipt = receipt_json(observation.receipt);
        receipt["available_ms"] = observation.available_ms;
        receipts_json.push_back(std::move(receipt));
        if (!observation.receipt.terminal &&
            observation.receipt.kind == ReceiptKind::AudioSpan &&
            !first_animation_ms.has_value()) {
            first_animation_ms = observation.available_ms;
        }
        if (!observation.receipt.terminal &&
            observation.receipt.kind == ReceiptKind::AudioSpan) {
            if (observation.receipt.activity == speech_animation::SpeechActivity::Active) {
                ++active_span_count;
            }
            else {
                ++silence_span_count;
            }
            mouth_open_total += observation.receipt.mouth_open;
            mouth_open_min = std::min(
                mouth_open_min,
                static_cast<double>(observation.receipt.mouth_open));
            mouth_open_max = std::max(
                mouth_open_max,
                static_cast<double>(observation.receipt.mouth_open));
        }
        if (observation.receipt.terminal) {
            terminal_receipt = observation.receipt;
        }
    }
    report["animation_receipts"] = std::move(receipts_json);
    const auto analyzed_span_count = active_span_count + silence_span_count;
    report["active_span_count"] = active_span_count;
    report["silence_span_count"] = silence_span_count;
    report["mouth_open_min"] = analyzed_span_count == 0
        ? nlohmann::json(nullptr)
        : nlohmann::json(mouth_open_min);
    report["mouth_open_max"] = analyzed_span_count == 0
        ? nlohmann::json(nullptr)
        : nlohmann::json(mouth_open_max);
    report["mouth_open_mean"] = analyzed_span_count == 0
        ? nlohmann::json(nullptr)
        : nlohmann::json(mouth_open_total / analyzed_span_count);

    if (!state.pcm.empty()) {
        report["first_pcm_ms"] = state.pcm.front().callback_ms;
        report["first_downstream_pcm_ms"] = state.pcm.front().downstream_callback_ms;
    }
    else {
        report["first_pcm_ms"] = nullptr;
        report["first_downstream_pcm_ms"] = nullptr;
    }
    report["first_animation_span_ms"] = first_animation_ms.has_value()
        ? nlohmann::json(first_animation_ms.value())
        : nlohmann::json(nullptr);
    report["adapter_callback_count"] = state.pcm.size();
    report["adapter_total_ms"] = adapter_total_ms;
    report["adapter_max_ms"] = adapter_max_ms;
    report["adapter_mean_ms"] = state.pcm.empty() ? 0.0 : adapter_total_ms / state.pcm.size();
    report["diagnostics"] = nlohmann::json::array();
    for (const auto& diagnostic : state.diagnostics) {
        report["diagnostics"].push_back({
            {"request_id", diagnostic.request_id},
            {"code", diagnostic.code},
            {"message", diagnostic.message}
        });
    }
    report["queue_full_count"] = std::count_if(
        state.diagnostics.begin(),
        state.diagnostics.end(),
        [](const auto& diagnostic) { return diagnostic.code == "speech_animation_queue_full"; });

    std::uint64_t pcm_end = 0;
    const bool pcm_contiguous = contiguous_pcm(state.pcm, pcm_end);
    const auto spans = audio_receipts(state.receipts);
    std::uint64_t animation_end = 0;
    const bool animation_contiguous = contiguous_animation(spans, animation_end);
    report["pcm_timeline_contiguous"] = pcm_contiguous;
    report["animation_timeline_contiguous"] = animation_contiguous;
    report["last_audio_span_matches_pcm_end"] =
        pcm_contiguous && animation_contiguous && animation_end == pcm_end;
    const bool terminal_fade_anchored = terminal_receipt.has_value() &&
        pcm_contiguous && terminal_receipt->output_first_sample == pcm_end;
    report["terminal_fade_anchored_at_pcm_end"] = terminal_fade_anchored;
    report["pcm_end_sample"] = pcm_contiguous ? nlohmann::json(pcm_end) : nlohmann::json(nullptr);
    report["animation_end_sample"] = animation_contiguous
        ? nlohmann::json(animation_end)
        : nlohmann::json(nullptr);
    if (terminal_receipt.has_value()) {
        report["terminal_fade_sample_count"] = terminal_receipt->terminal_fade_sample_count;
        report["terminal_fade_output_first_sample"] = terminal_receipt->output_first_sample;
    }
    else {
        report["terminal_fade_sample_count"] = nullptr;
        report["terminal_fade_output_first_sample"] = nullptr;
    }
    if (state.completion.has_value()) {
        report["completion"] = {
            {"execution_outcome", state.completion->execution_outcome},
            {"termination_reason", state.completion->termination_reason},
            {"hit_eos", state.completion->hit_eos},
            {"hit_max_seq_len", state.completion->hit_max_seq_len},
            {"hit_max_new_tokens", state.completion->hit_max_new_tokens},
            {"codec_frame_count", state.completion->codec_frame_count},
            {"generated_steps", state.completion->generated_steps},
            {"emitted_steps", state.completion->emitted_steps}
        };
    }
    if (state.error.has_value()) {
        report["error"] = {
            {"request_id", state.error->request_id},
            {"category", state.error->category},
            {"code", state.error->code},
            {"message", state.error->message}
        };
    }
    report["success"] = state.terminal_state == "completed" &&
        !state.pcm.empty() &&
        (!options.adapter_enabled ||
         (state.diagnostics.empty() && pcm_contiguous && animation_contiguous &&
          animation_end == pcm_end && terminal_fade_anchored));
    return report;
}

} // namespace

int main(int argc, char** argv) {
    try {
        const auto options = parse_options(argc, argv);
        const auto report = run_probe(options);
        const std::filesystem::path output = std::filesystem::u8path(options.output_json);
        if (std::filesystem::exists(output)) {
            throw std::runtime_error("refusing to overwrite output JSON: " + options.output_json);
        }
        if (!output.parent_path().empty()) {
            std::filesystem::create_directories(output.parent_path());
        }
        std::ofstream stream(output, std::ios::binary | std::ios::trunc);
        if (!stream) throw std::runtime_error("failed to open output JSON: " + options.output_json);
        stream << std::setw(2) << report << '\n';
        if (!stream) throw std::runtime_error("failed to write output JSON: " + options.output_json);
        std::cout << report.dump(2) << '\n';
        return report.value("success", false) ? EXIT_SUCCESS : EXIT_FAILURE;
    }
    catch (const std::exception& error) {
        std::cerr << "qwen_tts_speech_animation_probe: " << error.what() << '\n';
        return EXIT_FAILURE;
    }
}
