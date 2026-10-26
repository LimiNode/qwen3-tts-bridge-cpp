#include <qwen_tts_bridge/audio.hpp>
#include <qwen_tts_bridge/client.hpp>
#include <qwen_tts_bridge/transport.hpp>
#include <qwen_tts_bridge/playback/winmm_playback.hpp>

#ifdef QWEN_TTS_BRIDGE_HAS_SPEECH_ANIMATION
#include <qwen_tts_bridge/integration/speech_animation/PlaybackAnimationRuntime.hpp>
#endif

#define WIN32_LEAN_AND_MEAN
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <array>
#include <cmath>
#include <condition_variable>
#include <cstdint>
#include <cstring>
#include <deque>
#include <exception>
#include <filesystem>
#include <fstream>
#include <functional>
#include <iomanip>
#include <iostream>
#include <limits>
#include <memory>
#include <mutex>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>
#include <vector>

#ifndef QWEN_TTS_BRIDGE_EXAMPLE_PYTHON_EXECUTABLE
#define QWEN_TTS_BRIDGE_EXAMPLE_PYTHON_EXECUTABLE ""
#endif

#ifndef QWEN_TTS_BRIDGE_EXAMPLE_WORKER_DIR
#define QWEN_TTS_BRIDGE_EXAMPLE_WORKER_DIR ""
#endif

namespace {

using qwen_tts_bridge::AudioFormat;
using qwen_tts_bridge::PcmChunk;
using qwen_tts_bridge::PreparedText;
using qwen_tts_bridge::PreparedTtsRequest;
using qwen_tts_bridge::QwenTtsClient;
using qwen_tts_bridge::QwenTtsClientOptions;
using qwen_tts_bridge::ReadyMessage;
using qwen_tts_bridge::RequestId;
using qwen_tts_bridge::StdIoTransportOptions;
using qwen_tts_bridge::TtsCallbacks;
using qwen_tts_bridge::TtsError;
using qwen_tts_bridge::TtsRequest;
using qwen_tts_bridge::audio::AudioPostProcessorChain;
using qwen_tts_bridge::audio::AudioTerminalReason;
using qwen_tts_bridge::audio::PlayoutBuffer;
using qwen_tts_bridge::audio::TerminalFadeOptions;
using qwen_tts_bridge::audio::TerminalFadePostProcessor;
using qwen_tts_bridge::playback::MockPlaybackFailureStage;
using qwen_tts_bridge::playback::PlaybackInterruptionDiagnostic;
using qwen_tts_bridge::playback::PlaybackMetrics;
using qwen_tts_bridge::playback::PlaybackCursorSnapshot;
using qwen_tts_bridge::playback::PlaybackSinkMode;
using qwen_tts_bridge::playback::WaveOutPlayer;
using qwen_tts_bridge::playback::WprPlaybackMarkers;

struct ProgramOptions {
    bool help = false;
    bool self_test_playback_lifecycle = false;
    bool use_mock_worker = false;
    bool playback_enabled = true;
    bool use_mock_playback_sink = false;
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
    std::string playback_metrics_file;
    std::string playback_interruption_diagnostics_file;
    std::string playback_animation_receipts_file;
    std::uint32_t playback_animation_fps = 60;
    std::string pcm_capture_file;
    std::size_t playback_prebuffer_chunks = 1;
    bool etw_playback_markers = false;
    bool auto_profile = false;
    std::size_t auto_fast_max_bytes = 240;
    bool terminal_fade_enabled = true;
    TerminalFadeOptions terminal_fade;
};

class ConsoleCodePageGuard final {
public:
    ConsoleCodePageGuard()
        : input_code_page_(GetConsoleCP()),
          output_code_page_(GetConsoleOutputCP()) {
        if (input_code_page_ != 0) {
            SetConsoleCP(CP_UTF8);
        }
        if (output_code_page_ != 0) {
            SetConsoleOutputCP(CP_UTF8);
        }
    }

    ~ConsoleCodePageGuard() {
        if (input_code_page_ != 0) {
            SetConsoleCP(input_code_page_);
        }
        if (output_code_page_ != 0) {
            SetConsoleOutputCP(output_code_page_);
        }
    }

    ConsoleCodePageGuard(const ConsoleCodePageGuard&) = delete;
    ConsoleCodePageGuard& operator=(const ConsoleCodePageGuard&) = delete;

private:
    UINT input_code_page_ = 0;
    UINT output_code_page_ = 0;
};


class PcmCapture final {
public:
    explicit PcmCapture(const std::string& file_name)
        : target_(std::filesystem::u8path(file_name)),
          metadata_target_(metadata_path(target_)),
          temporary_(temporary_path(target_)),
          metadata_temporary_(temporary_path(metadata_target_)) {
        if (std::filesystem::exists(target_)) {
            throw std::runtime_error("refusing to overwrite existing PCM capture file: " + file_name);
        }
        if (std::filesystem::exists(metadata_target_)) {
            throw std::runtime_error(
                "refusing to overwrite existing PCM capture metadata file: " +
                metadata_target_.string());
        }
        if (std::filesystem::exists(temporary_) || std::filesystem::exists(metadata_temporary_)) {
            throw std::runtime_error("PCM capture temporary path already exists; remove it before retrying");
        }
        output_.open(temporary_, std::ios::binary | std::ios::trunc);
        if (!output_) {
            throw std::runtime_error("failed to open PCM capture file: " + temporary_.string());
        }
    }

    ~PcmCapture() {
        output_.close();
        if (!finalized_) {
            std::error_code ignored;
            std::filesystem::remove(temporary_, ignored);
            std::filesystem::remove(metadata_temporary_, ignored);
        }
    }

    PcmCapture(const PcmCapture&) = delete;
    PcmCapture& operator=(const PcmCapture&) = delete;

    void append(const PcmChunk& chunk) {
        if (chunk.bytes.empty()) {
            return;
        }

        std::lock_guard<std::mutex> lock(mutex_);
        if (finalized_) {
            throw std::runtime_error("cannot append PCM after capture finalization");
        }
        if (!format_.has_value()) {
            format_ = chunk.format;
        }
        else if (!formats_match(format_.value(), chunk.format)) {
            throw std::runtime_error("PCM capture cannot combine chunks with different audio formats");
        }
        output_.write(
            reinterpret_cast<const char*>(chunk.bytes.data()),
            static_cast<std::streamsize>(chunk.bytes.size()));
        if (!output_) {
            throw std::runtime_error("failed to write PCM capture file: " + temporary_.string());
        }
        byte_count_ += chunk.bytes.size();
        ++chunk_count_;
    }

    void finalize() {
        std::lock_guard<std::mutex> lock(mutex_);
        if (finalized_) {
            return;
        }
        if (!format_.has_value() || byte_count_ == 0) {
            throw std::runtime_error("cannot finalize PCM capture without audio");
        }
        output_.close();
        if (!output_) {
            throw std::runtime_error("failed to close PCM capture file: " + temporary_.string());
        }

        std::ostringstream metadata;
        metadata << "{\n"
                 << "  \"schema_version\": 1,\n"
                 << "  \"measurement\": \"raw_s16le_pcm_capture\",\n"
                 << "  \"completed\": true,\n"
                 << "  \"audio_chunk_count\": " << chunk_count_ << ",\n"
                 << "  \"byte_count\": " << byte_count_ << ",\n"
                 << "  \"audio_format\": {\"sample_format\": \""
                 << format_.value().sample_format << "\", \"sample_rate\": "
                 << format_.value().sample_rate << ", \"channels\": "
                 << format_.value().channels << "}\n"
                 << "}\n";
        bool pcm_promoted = false;
        try {
            std::ofstream metadata_output(metadata_temporary_, std::ios::binary | std::ios::trunc);
            if (!metadata_output) {
                throw std::runtime_error(
                    "failed to open PCM capture metadata file: " + metadata_temporary_.string());
            }
            metadata_output << metadata.str();
            metadata_output.close();
            if (!metadata_output) {
                throw std::runtime_error(
                    "failed to write PCM capture metadata file: " + metadata_temporary_.string());
            }
            std::filesystem::rename(temporary_, target_);
            pcm_promoted = true;
            std::filesystem::rename(metadata_temporary_, metadata_target_);
            finalized_ = true;
        }
        catch (...) {
            if (pcm_promoted) {
                std::error_code rollback_error;
                std::filesystem::rename(target_, temporary_, rollback_error);
                if (rollback_error) {
                    throw std::runtime_error(
                        "failed to roll back incomplete PCM capture finalization: " +
                        rollback_error.message());
                }
            }
            std::error_code ignored;
            std::filesystem::remove(metadata_temporary_, ignored);
            throw;
        }
    }

private:
    static bool formats_match(const AudioFormat& left, const AudioFormat& right) {
        return left.sample_format == right.sample_format &&
            left.sample_rate == right.sample_rate &&
            left.channels == right.channels;
    }

    static std::filesystem::path metadata_path(const std::filesystem::path& target) {
        return std::filesystem::path(target.native() + L".json");
    }

    static std::filesystem::path temporary_path(const std::filesystem::path& target) {
        return std::filesystem::path(
            target.native() + L".tmp." + std::to_wstring(GetCurrentProcessId()));
    }

    std::mutex mutex_;
    std::filesystem::path target_;
    std::filesystem::path metadata_target_;
    std::filesystem::path temporary_;
    std::filesystem::path metadata_temporary_;
    std::ofstream output_;
    std::optional<AudioFormat> format_;
    std::size_t chunk_count_ = 0;
    std::size_t byte_count_ = 0;
    bool finalized_ = false;
};


struct ActiveRequestState {
    std::mutex mutex;
    RequestId active_request_id = 0;
    RequestId next_request_id = 1;
    QwenTtsClient* active_client = nullptr;
    std::shared_ptr<AudioPostProcessorChain> processors;
};

#ifdef QWEN_TTS_BRIDGE_HAS_SPEECH_ANIMATION
struct PlaybackAnimationContext {
    std::mutex mutex;
    std::uint64_t playback_epoch = 0;
    RequestId request_id = 0;
};

using PlaybackAnimationDiagnostic =
    qwen_tts_bridge::speech_animation::PlaybackAnimationRuntime::AdapterDiagnostic;

struct PlaybackAnimationDiagnosticQueue {
    std::mutex mutex;
    std::deque<PlaybackAnimationDiagnostic> records;
};

class PlaybackAnimationLoop final {
public:
    PlaybackAnimationLoop() = default;
    PlaybackAnimationLoop(const PlaybackAnimationLoop&) = delete;
    PlaybackAnimationLoop& operator=(const PlaybackAnimationLoop&) = delete;

    void start(std::function<void()> tick, std::uint32_t fps) {
        if (thread_.joinable()) {
            throw std::logic_error("playback animation loop already started");
        }
        stop_.store(false, std::memory_order_release);
        thread_ = std::thread([
            this,
            tick = std::move(tick),
            interval = std::chrono::duration_cast<std::chrono::steady_clock::duration>(
                std::chrono::duration<double>(1.0 / static_cast<double>(fps)))] {
            auto deadline = std::chrono::steady_clock::now();
            while (!stop_.load(std::memory_order_acquire)) {
                tick();
                deadline += interval;
                const auto now = std::chrono::steady_clock::now();
                if (deadline < now) {
                    deadline = now;
                }
                std::this_thread::sleep_until(deadline);
            }
        });
    }

    ~PlaybackAnimationLoop() {
        stop();
    }

    void stop() noexcept {
        stop_.store(true, std::memory_order_release);
        if (thread_.joinable()) {
            thread_.join();
        }
    }

private:
    std::atomic<bool> stop_{false};
    std::thread thread_;
};

std::string json_escape(const std::string& value) {
    std::string escaped;
    escaped.reserve(value.size());
    for (const char character : value) {
        if (character == '\\' || character == '"') {
            escaped.push_back('\\');
        }
        escaped.push_back(character);
    }
    return escaped;
}
#endif

struct OneShotState {
    std::mutex mutex;
    std::condition_variable condition;
    bool terminal = false;
    bool success = false;
    std::string message;
};

void mark_one_shot_terminal(
    OneShotState* state,
    bool success,
    std::string message = {}) {
    if (state == nullptr) {
        return;
    }
    std::lock_guard<std::mutex> lock(state->mutex);
    if (state->terminal) {
        return;
    }
    state->terminal = true;
    state->success = success;
    state->message = std::move(message);
    state->condition.notify_all();
}

std::string utf8_from_wide(const std::wstring& value);

void print_usage(std::ostream& out, const std::string& executable_name) {
    out << "Usage:\n"
        << "  " << executable_name << " --self-test-playback-lifecycle\n"
        << "  " << executable_name << " --mock [--speaker name]\n"
        << "  " << executable_name << " --worker qwen_tts_worker.exe [--speaker name]\n"
        << "  " << executable_name << " --worker qwen_tts_worker.exe --text \"Hello\"\n\n"
        << "Interactive commands:\n"
        << "  <text>                 Cancel current generation and speak this text.\n"
        << "  /cancel                Cancel current generation and stop playback.\n"
        << "  /voice <name>          Select a registered profile, or a CustomVoice speaker.\n"
        << "  /voices                 List registered Base voice profiles.\n"
        << "  /language <name>       Set the language for future requests.\n"
        << "  /style <text>          Set the style instruction for future requests.\n"
        << "  /temperature <value|default>  Set sampling temperature for future requests.\n"
        << "  /top-k <value|default> Set top-k candidate limit for future requests.\n"
        << "  /top-p <value|default> Set nucleus probability for future requests.\n"
        << "  /repetition-penalty <value|default> Set repetition penalty for future requests.\n"
        << "  /sample <on|off|default> Set sampling mode for future requests.\n"
        << "  /seed <value|default>  Set deterministic seed for future requests.\n"
        << "  /sampling               Show current per-request sampling controls.\n"
        << "  --etw-playback-markers  Emit ETW request and queue-starvation markers (diagnostic).\n"
        << "  /help                  Show this help.\n"
        << "  /quit                  Stop the worker and exit.\n\n"
        << "Options:\n"
        << "  --help                         Show this help.\n"
        << "  --mock                         Run the bundled Python mock worker.\n"
        << "  --worker <path>                Worker executable path.\n"
        << "  --worker-arg <arg>             Extra worker argument; may be repeated.\n"
        << "  --auto-profile                 Keep fast and safe workers warm and route by text length.\n"
        << "  --auto-fast-max-bytes <n>      Use the fast worker up to n non-space UTF-8 bytes, default: 240.\n"
        << "  --auto-fast-max-chars <n>      Backward-compatible alias for --auto-fast-max-bytes.\n"
        << "  --cwd <path>                   Worker working directory.\n"
        << "  --text <utf8>                  One-shot playback instead of interactive mode.\n"
        << "  --language <name>              Request language, default: auto.\n"
        << "  --speaker <name>               Optional request speaker or voice name.\n"
        << "  --voice-id <name>              Registered Base voice profile identifier.\n"
        << "  --instruction <utf8>           Natural-language style instruction.\n"
        << "  --reference-audio <path>       Local WAV reference for Base voice cloning.\n"
        << "  --reference-text <utf8>        Transcript of the reference audio.\n"
        << "  --x-vector-only                Clone speaker embedding without transcript.\n"
        << "  --temperature <value>          Per-request sampling temperature.\n"
        << "  --top-k <value>                Per-request top-k candidate limit.\n"
        << "  --top-p <value>                Per-request nucleus probability.\n"
        << "  --repetition-penalty <value>   Per-request repetition penalty.\n"
        << "  --sample                       Enable per-request sampling.\n"
        << "  --no-sample                    Use per-request greedy decoding.\n"
        << "  --seed <value>                 Per-request deterministic seed.\n"
        << "  --sample-rate <hz>             Requested sample rate, default: 24000.\n"
        << "  --channels <count>             Requested channel count, default: 1.\n"
        << "  --startup-timeout-ms <ms>      Worker startup timeout, default: 30000.\n"
        << "  --no-playback                  Deliver PCM without opening a WaveOut device.\n"
        << "  --mock-playback-sink           Use a deterministic timed sink with --mock.\n"
        << "  --mock-playback-fail-after <n> Inject a mock sink failure after n submissions (test only).\n"
        << "  --mock-playback-fail-stage <prepare|write>  Select the injected submission stage (test only).\n"
        << "  --playback-metrics-file <path> Write opt-in one-shot WaveOut queue metrics JSON.\n"
        << "  --playback-interruption-diagnostics-file <path> Write opt-in cursor/reset cancellation diagnostics JSON.\n"
        << "  --playback-animation-receipts-file <path> Write playback-locked animation selections as JSONL.\n"
        << "  --playback-animation-fps <n> Presentation tick rate for animation receipts, default: 60.\n"
        << "  --pcm-capture-file <path>      Write opt-in one-shot raw s16le PCM plus JSON metadata.\n"
        << "  --playback-prebuffer-chunks <n> Delay sink start until n PCM chunks arrive, default: 1.\n"
        << "  --tail                         Enable terminal fade and padding (default).\n"
        << "  --no-tail                      Disable terminal fade and padding.\n"
        << "  --tail-fade-ms <ms>            Terminal fade duration, default: 15.\n"
        << "  --tail-silence-ms <ms>         Completion silence, default: 85.\n"
        << "  --cancel-tail-silence-ms <ms>  Cancellation silence, default: 0.\n"
        << "  --mock-chunks <count>          Mock worker chunk count, default: 3.\n"
        << "  --mock-chunk-ms <ms>           Mock chunk duration, default: 100.\n"
        << "  --mock-chunk-delay <seconds>   Mock delay between chunks, default: 0.\n";
}

std::string require_value(
    int& index,
    int argc,
    wchar_t** argv,
    const std::string& option) {
    const std::string prefix = option + '=';
    const std::string current = utf8_from_wide(argv[index]);
    if (current.rfind(prefix, 0) == 0) {
        return current.substr(prefix.size());
    }
    if (index + 1 >= argc) {
        throw std::runtime_error("missing value for " + option);
    }
    ++index;
    return utf8_from_wide(argv[index]);
}

std::uint32_t parse_u32(const std::string& value, const std::string& option) {
    std::size_t parsed = 0;
    const unsigned long result = std::stoul(value, &parsed, 10);
    if (parsed != value.size() || result > std::numeric_limits<std::uint32_t>::max()) {
        throw std::runtime_error("invalid integer for " + option + ": " + value);
    }
    return static_cast<std::uint32_t>(result);
}

std::uint64_t parse_u64(const std::string& value, const std::string& option) {
    if (value.empty() || value.front() == '-') {
        throw std::runtime_error("invalid integer for " + option + ": " + value);
    }
    std::size_t parsed = 0;
    const unsigned long long result = std::stoull(value, &parsed, 10);
    if (parsed != value.size()) {
        throw std::runtime_error("invalid integer for " + option + ": " + value);
    }
    return static_cast<std::uint64_t>(result);
}

int parse_int(const std::string& value, const std::string& option) {
    std::size_t parsed = 0;
    const long result = std::stol(value, &parsed, 10);
    if (parsed != value.size() || result < (std::numeric_limits<int>::min)() ||
        result > (std::numeric_limits<int>::max)()) {
        throw std::runtime_error("invalid integer for " + option + ": " + value);
    }
    return static_cast<int>(result);
}

double parse_double(const std::string& value, const std::string& option) {
    std::size_t parsed = 0;
    const double result = std::stod(value, &parsed);
    if (parsed != value.size() || !std::isfinite(result)) {
        throw std::runtime_error("invalid number for " + option + ": " + value);
    }
    return result;
}

ProgramOptions parse_options(int argc, wchar_t** argv) {
    ProgramOptions options;
    for (int index = 1; index < argc; ++index) {
        const std::string arg = utf8_from_wide(argv[index]);
        if (arg == "--help" || arg == "-h") {
            options.help = true;
        }
        else if (arg == "--self-test-playback-lifecycle") {
            options.self_test_playback_lifecycle = true;
        }
        else if (arg == "--mock") {
            options.use_mock_worker = true;
        }
        else if (arg == "--no-playback") {
            options.playback_enabled = false;
        }
        else if (arg == "--mock-playback-sink") {
            options.use_mock_playback_sink = true;
        }
        else if (arg == "--mock-playback-fail-after" ||
                 arg.rfind("--mock-playback-fail-after=", 0) == 0) {
            options.mock_playback_fail_after_submissions = parse_u32(
                require_value(index, argc, argv, "--mock-playback-fail-after"),
                "--mock-playback-fail-after");
        }
        else if (arg == "--mock-playback-fail-stage" ||
                 arg.rfind("--mock-playback-fail-stage=", 0) == 0) {
            options.mock_playback_fail_stage = require_value(
                index, argc, argv, "--mock-playback-fail-stage");
        }
        else if (arg == "--worker" || arg.rfind("--worker=", 0) == 0) {
            options.worker_executable = require_value(index, argc, argv, "--worker");
        }
        else if (arg == "--worker-arg" || arg.rfind("--worker-arg=", 0) == 0) {
            options.worker_arguments.push_back(
                require_value(index, argc, argv, "--worker-arg"));
        }
        else if (arg == "--auto-profile") {
            options.auto_profile = true;
        }
        else if (arg == "--auto-fast-max-bytes" ||
                 arg.rfind("--auto-fast-max-bytes=", 0) == 0 ||
                 arg == "--auto-fast-max-chars" ||
                 arg.rfind("--auto-fast-max-chars=", 0) == 0) {
            options.auto_fast_max_bytes = parse_u32(
                require_value(index, argc, argv,
                    arg.find("chars") != std::string::npos
                        ? "--auto-fast-max-chars"
                        : "--auto-fast-max-bytes"),
                arg.find("chars") != std::string::npos
                    ? "--auto-fast-max-chars"
                    : "--auto-fast-max-bytes");
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
        else if (arg == "--voice-id" || arg.rfind("--voice-id=", 0) == 0) {
            options.voice_id = require_value(index, argc, argv, "--voice-id");
        }
        else if (arg == "--reference-audio" || arg.rfind("--reference-audio=", 0) == 0) {
            options.reference_audio_path = require_value(index, argc, argv, "--reference-audio");
        }
        else if (arg == "--reference-text" || arg.rfind("--reference-text=", 0) == 0) {
            options.reference_text = require_value(index, argc, argv, "--reference-text");
        }
        else if (arg == "--x-vector-only") {
            options.x_vector_only = true;
        }
        else if (arg == "--temperature" || arg.rfind("--temperature=", 0) == 0) {
            options.temperature = parse_double(
                require_value(index, argc, argv, "--temperature"), "--temperature");
        }
        else if (arg == "--top-k" || arg.rfind("--top-k=", 0) == 0) {
            options.top_k = parse_u32(
                require_value(index, argc, argv, "--top-k"), "--top-k");
        }
        else if (arg == "--top-p" || arg.rfind("--top-p=", 0) == 0) {
            options.top_p = parse_double(
                require_value(index, argc, argv, "--top-p"), "--top-p");
        }
        else if (arg == "--repetition-penalty" ||
                 arg.rfind("--repetition-penalty=", 0) == 0) {
            options.repetition_penalty = parse_double(
                require_value(index, argc, argv, "--repetition-penalty"),
                "--repetition-penalty");
        }
        else if (arg == "--sample") {
            options.do_sample = true;
        }
        else if (arg == "--no-sample") {
            options.do_sample = false;
        }
        else if (arg == "--seed" || arg.rfind("--seed=", 0) == 0) {
            options.seed = parse_u64(
                require_value(index, argc, argv, "--seed"), "--seed");
        }
        else if (arg == "--sample-rate" || arg.rfind("--sample-rate=", 0) == 0) {
            options.sample_rate = parse_u32(
                require_value(index, argc, argv, "--sample-rate"), "--sample-rate");
        }
        else if (arg == "--channels" || arg.rfind("--channels=", 0) == 0) {
            options.channels = parse_u32(
                require_value(index, argc, argv, "--channels"), "--channels");
        }
        else if (arg == "--startup-timeout-ms" ||
                 arg.rfind("--startup-timeout-ms=", 0) == 0) {
            options.startup_timeout = std::chrono::milliseconds(parse_u32(
                require_value(index, argc, argv, "--startup-timeout-ms"),
                "--startup-timeout-ms"));
        }
        else if (arg == "--playback-metrics-file" ||
                 arg.rfind("--playback-metrics-file=", 0) == 0) {
            options.playback_metrics_file = require_value(
                index, argc, argv, "--playback-metrics-file");
        }
        else if (arg == "--playback-interruption-diagnostics-file" ||
                 arg.rfind("--playback-interruption-diagnostics-file=", 0) == 0) {
            options.playback_interruption_diagnostics_file = require_value(
                index,
                argc,
                argv,
                "--playback-interruption-diagnostics-file");
        }
        else if (arg == "--playback-animation-receipts-file" ||
                 arg.rfind("--playback-animation-receipts-file=", 0) == 0) {
            options.playback_animation_receipts_file = require_value(
                index, argc, argv, "--playback-animation-receipts-file");
        }
        else if (arg == "--playback-animation-fps" ||
                 arg.rfind("--playback-animation-fps=", 0) == 0) {
            options.playback_animation_fps = parse_u32(
                require_value(index, argc, argv, "--playback-animation-fps"),
                "--playback-animation-fps");
        }
        else if (arg == "--pcm-capture-file" ||
                 arg.rfind("--pcm-capture-file=", 0) == 0) {
            options.pcm_capture_file = require_value(index, argc, argv, "--pcm-capture-file");
        }
        else if (arg == "--playback-prebuffer-chunks" ||
                 arg.rfind("--playback-prebuffer-chunks=", 0) == 0) {
            options.playback_prebuffer_chunks = parse_u32(
                require_value(index, argc, argv, "--playback-prebuffer-chunks"),
                "--playback-prebuffer-chunks");
        }
        else if (arg == "--tail") {
            options.terminal_fade_enabled = true;
        }
        else if (arg == "--no-tail") {
            options.terminal_fade_enabled = false;
        }
        else if (arg == "--tail-fade-ms" || arg.rfind("--tail-fade-ms=", 0) == 0) {
            options.terminal_fade.fade_ms = parse_u32(
                require_value(index, argc, argv, "--tail-fade-ms"),
                "--tail-fade-ms");
        }
        else if (arg == "--tail-silence-ms" || arg.rfind("--tail-silence-ms=", 0) == 0) {
            options.terminal_fade.completion_silence_ms = parse_u32(
                require_value(index, argc, argv, "--tail-silence-ms"),
                "--tail-silence-ms");
        }
        else if (arg == "--cancel-tail-silence-ms" ||
                 arg.rfind("--cancel-tail-silence-ms=", 0) == 0) {
            options.terminal_fade.cancellation_silence_ms = parse_u32(
                require_value(index, argc, argv, "--cancel-tail-silence-ms"),
                "--cancel-tail-silence-ms");
        }
        else if (arg == "--etw-playback-markers") {
            options.etw_playback_markers = true;
        }
        else if (arg == "--mock-chunks" || arg.rfind("--mock-chunks=", 0) == 0) {
            options.mock_chunks = parse_int(
                require_value(index, argc, argv, "--mock-chunks"), "--mock-chunks");
        }
        else if (arg == "--mock-chunk-ms" || arg.rfind("--mock-chunk-ms=", 0) == 0) {
            options.mock_chunk_ms = parse_int(
                require_value(index, argc, argv, "--mock-chunk-ms"), "--mock-chunk-ms");
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
    if (options.help || options.self_test_playback_lifecycle) {
        return;
    }
    if (!options.use_mock_worker && options.worker_executable.empty()) {
        throw std::runtime_error("--worker is required unless --mock is used");
    }
    if (options.auto_profile && options.use_mock_worker) {
        throw std::runtime_error("--auto-profile requires a real Qwen worker");
    }
    if (options.auto_profile && options.auto_fast_max_bytes == 0) {
        throw std::runtime_error("--auto-fast-max-bytes must be greater than zero");
    }
    if (options.sample_rate == 0 || options.channels == 0 ||
        options.channels > (std::numeric_limits<WORD>::max)()) {
        throw std::runtime_error("invalid requested PCM format");
    }
    if (options.mock_chunks <= 0 || options.mock_chunk_ms <= 0 ||
        options.mock_chunk_delay < 0.0) {
        throw std::runtime_error("invalid mock worker options");
    }
    if (options.etw_playback_markers && options.playback_metrics_file.empty()) {
        throw std::runtime_error("--etw-playback-markers requires --playback-metrics-file");
    }
    if (options.playback_prebuffer_chunks == 0) {
        throw std::runtime_error("--playback-prebuffer-chunks must be greater than zero");
    }
    if (options.playback_animation_fps == 0 ||
        options.playback_animation_fps > 1000) {
        throw std::runtime_error("--playback-animation-fps must be between 1 and 1000");
    }
#ifndef QWEN_TTS_BRIDGE_HAS_SPEECH_ANIMATION
    if (!options.playback_animation_receipts_file.empty()) {
        throw std::runtime_error(
            "playback animation receipts require QWEN_TTS_BRIDGE_BUILD_SPEECH_ANIMATION=ON");
    }
#endif
    constexpr std::uint32_t max_terminal_duration_ms = 600000;
    if (options.terminal_fade.fade_ms > max_terminal_duration_ms ||
        options.terminal_fade.completion_silence_ms > max_terminal_duration_ms ||
        options.terminal_fade.cancellation_silence_ms > max_terminal_duration_ms) {
        throw std::runtime_error("audio terminal durations must not exceed 600000 ms");
    }
    if (options.use_mock_playback_sink && !options.use_mock_worker) {
        throw std::runtime_error("--mock-playback-sink requires --mock");
    }
    if (options.use_mock_playback_sink && !options.playback_enabled) {
        throw std::runtime_error("--mock-playback-sink cannot be combined with --no-playback");
    }
    if (options.mock_playback_fail_after_submissions.has_value() &&
        !options.use_mock_playback_sink) {
        throw std::runtime_error(
            "--mock-playback-fail-after requires --mock-playback-sink");
    }
    if (options.mock_playback_fail_stage.has_value()) {
        if (!options.mock_playback_fail_after_submissions.has_value() ||
            !options.use_mock_playback_sink) {
            throw std::runtime_error(
                "--mock-playback-fail-stage requires --mock-playback-fail-after and "
                "--mock-playback-sink");
        }
        if (options.mock_playback_fail_stage.value() != "prepare" &&
            options.mock_playback_fail_stage.value() != "write") {
            throw std::runtime_error(
                "--mock-playback-fail-stage must be prepare or write");
        }
    }
    if (options.temperature.has_value() &&
        (options.temperature.value() <= 0.0 || options.temperature.value() > 2.0)) {
        throw std::runtime_error("--temperature must be in the interval (0, 2]");
    }
    if (options.top_k.has_value() && options.top_k.value() == 0) {
        throw std::runtime_error("--top-k must be greater than zero");
    }
    if (options.top_p.has_value() &&
        (options.top_p.value() <= 0.0 || options.top_p.value() > 1.0)) {
        throw std::runtime_error("--top-p must be in the interval (0, 1]");
    }
    if (options.repetition_penalty.has_value() &&
        (options.repetition_penalty.value() < 1.0 ||
         options.repetition_penalty.value() > 2.0)) {
        throw std::runtime_error("--repetition-penalty must be in the interval [1, 2]");
    }
    if (options.reference_audio_path.empty() &&
        (!options.reference_text.empty() || options.x_vector_only)) {
        throw std::runtime_error("--reference-text and --x-vector-only require --reference-audio");
    }
    if (!options.reference_audio_path.empty() &&
        options.reference_text.empty() && !options.x_vector_only) {
        throw std::runtime_error(
            "--reference-audio requires --reference-text unless --x-vector-only is set");
    }
    if (!options.voice_id.empty() &&
        (!options.reference_audio_path.empty() || !options.reference_text.empty() ||
         options.x_vector_only)) {
        throw std::runtime_error(
            "--voice-id cannot be combined with direct reference-audio options");
    }
    if (!options.playback_metrics_file.empty() && options.text.empty()) {
        throw std::runtime_error("--playback-metrics-file requires one-shot --text playback");
    }
    if (!options.pcm_capture_file.empty() && options.text.empty()) {
        throw std::runtime_error("--pcm-capture-file requires one-shot --text playback");
    }
}

void replace_worker_option(
    std::vector<std::string>& arguments,
    const std::string& option,
    const std::string& value) {
    for (std::size_t index = 0; index < arguments.size(); ++index) {
        if (arguments[index] == option) {
            if (index + 1 >= arguments.size()) {
                throw std::runtime_error("worker option is missing a value: " + option);
            }
            arguments[index + 1] = value;
            return;
        }
        const std::string prefix = option + '=';
        if (arguments[index].rfind(prefix, 0) == 0) {
            arguments[index] = prefix + value;
            return;
        }
    }
    throw std::runtime_error("--auto-profile requires worker argument " + option);
}

StdIoTransportOptions make_transport_options(
    const ProgramOptions& options,
    bool safe_profile = false) {
    StdIoTransportOptions transport_options;
    transport_options.stderr_handler = [](std::string text) {
        std::cerr << text;
    };
    if (options.use_mock_worker) {
        const std::string python_executable = QWEN_TTS_BRIDGE_EXAMPLE_PYTHON_EXECUTABLE;
        const std::string worker_dir = QWEN_TTS_BRIDGE_EXAMPLE_WORKER_DIR;
        if (python_executable.empty() || worker_dir.empty()) {
            throw std::runtime_error("--mock is unavailable because Python was not found at build time");
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
    if (safe_profile) {
        replace_worker_option(transport_options.arguments, "--runtime-profile", "cmp50hx-safe");
        replace_worker_option(transport_options.arguments, "--max-seq-len", "2048");
        replace_worker_option(transport_options.arguments, "--emit-every-frames", "8");
        replace_worker_option(transport_options.arguments, "--decode-window-frames", "33");
        for (std::size_t index = 0; index < transport_options.arguments.size(); ++index) {
            if (transport_options.arguments[index] == "--emit-chunk-schedule" &&
                index + 1 < transport_options.arguments.size()) {
                transport_options.arguments[index + 1] = "8";
            }
            else if (transport_options.arguments[index].rfind("--emit-chunk-schedule=", 0) == 0) {
                transport_options.arguments[index] = "--emit-chunk-schedule=8";
            }
        }
        // The launcher normally exports the fast profile's codec window in the
        // parent environment. Override those values for the second worker.
        transport_options.environment_overrides[
            "QTB_FASTER_CODEC_RIGHT_PADDED_DECODE_WINDOW_FRAMES"] = "33";
        transport_options.environment_overrides[
            "QTB_FASTER_CODEC_RIGHT_PADDED_MAX_DECODE_INPUT_FRAMES"] = "33";
    }
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

bool is_active_request(ActiveRequestState& state, RequestId request_id) {
    std::lock_guard<std::mutex> lock(state.mutex);
    return state.active_request_id == request_id;
}

bool clear_active_request(ActiveRequestState& state, RequestId request_id) {
    std::lock_guard<std::mutex> lock(state.mutex);
    if (state.active_request_id != request_id) {
        return false;
    }
    state.active_request_id = 0;
    state.active_client = nullptr;
    state.processors.reset();
    return true;
}

bool complete_active_request(ActiveRequestState& state, RequestId request_id) {
    std::lock_guard<std::mutex> lock(state.mutex);
    if (state.active_request_id != request_id) {
        return false;
    }
    state.active_request_id = 0;
    state.active_client = nullptr;
    state.processors.reset();
    return true;
}

void fail_playback_request(
    WaveOutPlayer& player,
    ActiveRequestState& active_state,
    RequestId request_id,
    std::uint64_t playback_epoch,
    OneShotState* one_shot_state,
    std::string message) {
    QwenTtsClient* request_client = nullptr;
    {
        std::lock_guard<std::mutex> lock(active_state.mutex);
        if (active_state.active_request_id != request_id) {
            return;
        }
        request_client = active_state.active_client;
        active_state.active_request_id = 0;
        active_state.active_client = nullptr;
        active_state.processors.reset();
    }

    if (request_client != nullptr) {
        static_cast<void>(request_client->cancel(request_id));
    }
    try {
        static_cast<void>(player.reset_if_epoch(playback_epoch));
    }
    catch (const std::exception& reset_error) {
        message += "; playback reset failed: ";
        message += reset_error.what();
    }
    player.note_request_terminal(request_id, "failed");
    mark_one_shot_terminal(one_shot_state, false, "playback failed: " + message);
    if (one_shot_state == nullptr) {
        std::cerr << "request " << request_id << " playback failed: "
                  << message << '\n';
    }
}

int run_playback_lifecycle_self_test() {
    WaveOutPlayer player(PlaybackSinkMode::Mock);
    const auto initial_epoch = player.playback_epoch();

    std::mutex reset_gate_mutex;
    std::condition_variable reset_gate_condition;
    bool reset_started = false;
    bool release_reset = false;
    player.set_reset_wait_hook_for_test([&] {
        std::unique_lock<std::mutex> lock(reset_gate_mutex);
        reset_started = true;
        reset_gate_condition.notify_all();
        reset_gate_condition.wait(lock, [&] { return release_reset; });
    });

    bool stale_reset_started = false;
    std::thread stale_reset([&] {
        stale_reset_started = player.reset_if_epoch(initial_epoch);
    });
    {
        std::unique_lock<std::mutex> lock(reset_gate_mutex);
        reset_gate_condition.wait(lock, [&] { return reset_started; });
    }

    const auto replacement_epoch = player.reset();
    PcmChunk replacement_chunk;
    replacement_chunk.request_id = 43;
    replacement_chunk.format.sample_format = "s16le";
    replacement_chunk.format.sample_rate = 24000;
    replacement_chunk.format.channels = 1;
    replacement_chunk.bytes = {std::byte{0}, std::byte{0}};
    replacement_chunk.sample_count = 1;
    player.enqueue(replacement_epoch, replacement_chunk);

    {
        std::lock_guard<std::mutex> lock(reset_gate_mutex);
        release_reset = true;
    }
    reset_gate_condition.notify_all();
    stale_reset.join();
    if (!stale_reset_started ||
        player.playback_epoch() != replacement_epoch ||
        player.buffered_chunk_count_for_test() != 1) {
        throw std::runtime_error("stale playback reset destroyed replacement playback");
    }

    WaveOutPlayer terminal_player(PlaybackSinkMode::Mock);
    ActiveRequestState terminal_state;
    {
        std::lock_guard<std::mutex> lock(terminal_state.mutex);
        terminal_state.active_request_id = 41;
    }
    const auto terminal_epoch = terminal_player.playback_epoch();
    if (!clear_active_request(terminal_state, 41)) {
        throw std::runtime_error("failed to claim terminal request in self-test");
    }
    const auto terminal_replacement_epoch = terminal_player.reset();
    terminal_player.enqueue(terminal_replacement_epoch, replacement_chunk);
    if (terminal_player.reset_if_epoch(terminal_epoch) ||
        terminal_player.interrupt_with_fade_if_epoch(terminal_epoch, 0, 41).has_value() ||
        terminal_player.buffered_chunk_count_for_test() != 1) {
        throw std::runtime_error("stale error/cancel path destroyed replacement playback");
    }

    ActiveRequestState state;
    {
        std::lock_guard<std::mutex> lock(state.mutex);
        state.active_request_id = 42;
    }
    std::mutex gate_mutex;
    std::condition_variable gate_condition;
    bool completion_released = false;
    bool completion_won = false;
    std::thread completion([&] {
        std::unique_lock<std::mutex> lock(gate_mutex);
        gate_condition.wait(lock, [&] { return completion_released; });
        completion_won = complete_active_request(state, 42);
    });
    clear_active_request(state, 42);
    {
        std::lock_guard<std::mutex> lock(gate_mutex);
        completion_released = true;
    }
    gate_condition.notify_all();
    completion.join();
    if (completion_won) {
        throw std::runtime_error("stale completion claimed success after cancellation");
    }

    {
        std::lock_guard<std::mutex> lock(state.mutex);
        state.active_request_id = 43;
    }
    if (!complete_active_request(state, 43) ||
        complete_active_request(state, 43)) {
        throw std::runtime_error("active completion transition is not exactly once");
    }

    const auto assert_injected_submission_failure = [](
        MockPlaybackFailureStage stage,
        const char* expected_operation) {
        WaveOutPlayer failure_player(
            PlaybackSinkMode::Mock,
            nullptr,
            1,
            0,
            stage);
        PcmChunk chunk;
        chunk.request_id = 44;
        chunk.format.sample_format = "s16le";
        chunk.format.sample_rate = 24000;
        chunk.format.channels = 1;
        chunk.bytes = {std::byte{0}, std::byte{0}};
        chunk.sample_count = 1;
        bool failed = false;
        try {
            failure_player.enqueue(failure_player.playback_epoch(), chunk);
        }
        catch (const std::runtime_error& error) {
            failed = std::string(error.what()).find(expected_operation) != std::string::npos;
        }
        if (!failed || failure_player.next_stream_frame_for_test() != 0 ||
            failure_player.buffered_chunk_count_for_test() != 1) {
            throw std::runtime_error("submission failure changed the committed playback frontier");
        }
        const auto retry_epoch = failure_player.reset();
        failure_player.enqueue(retry_epoch, chunk);
        if (failure_player.next_stream_frame_for_test() != 1 ||
            failure_player.buffered_chunk_count_for_test() != 1) {
            throw std::runtime_error("submission retry did not recover a clean playback queue");
        }
    };
    assert_injected_submission_failure(
        MockPlaybackFailureStage::Prepare,
        "waveOutPrepareHeader");
    assert_injected_submission_failure(
        MockPlaybackFailureStage::Write,
        "waveOutWrite");

    WaveOutPlayer partial_player(
        PlaybackSinkMode::Mock,
        nullptr,
        2,
        1,
        MockPlaybackFailureStage::Write);
    const auto partial_epoch = partial_player.playback_epoch();
    partial_player.enqueue(partial_epoch, replacement_chunk);
    bool partial_failed = false;
    try {
        partial_player.enqueue(partial_epoch, replacement_chunk);
    }
    catch (const std::runtime_error& error) {
        partial_failed = std::string(error.what()).find("waveOutWrite") != std::string::npos;
    }
    if (!partial_failed || partial_player.next_stream_frame_for_test() != 1 ||
        partial_player.buffered_chunk_count_for_test() != 2) {
        throw std::runtime_error("partial submission did not preserve committed buffers");
    }
    const auto partial_retry_epoch = partial_player.reset();
    partial_player.enqueue(partial_retry_epoch, replacement_chunk);
    partial_player.enqueue(partial_retry_epoch, replacement_chunk);
    if (partial_player.next_stream_frame_for_test() != 2 ||
        partial_player.buffered_chunk_count_for_test() != 2) {
        throw std::runtime_error("partial submission cleanup left stale buffer ownership");
    }
    return 0;
}

std::shared_ptr<AudioPostProcessorChain> make_audio_processors(
    const ProgramOptions& options) {
    auto processors = std::make_shared<AudioPostProcessorChain>();
    if (options.terminal_fade_enabled) {
        processors->add(std::make_unique<TerminalFadePostProcessor>(
            options.terminal_fade));
    }
    return processors;
}

std::uint64_t cancel_active_request(
    QwenTtsClient& client,
    WaveOutPlayer& player,
    ActiveRequestState& state,
    std::uint32_t interruption_fade_ms
#ifdef QWEN_TTS_BRIDGE_HAS_SPEECH_ANIMATION
    , qwen_tts_bridge::speech_animation::PlaybackAnimationRuntime* animation_runtime = nullptr
    , PlaybackAnimationContext* animation_context = nullptr
#endif
    ) {
    RequestId request_id = 0;
    QwenTtsClient* active_client = nullptr;
    std::shared_ptr<AudioPostProcessorChain> processors;
    {
        std::lock_guard<std::mutex> lock(state.mutex);
        request_id = state.active_request_id;
        active_client = state.active_client;
        processors = std::move(state.processors);
        state.active_request_id = 0;
        state.active_client = nullptr;
    }
    if (request_id != 0) {
        (active_client != nullptr ? *active_client : client).cancel(request_id);
    }
    // Producer-side processors must not release their newest buffered samples
    // here: those samples may already be far ahead of the physical sink.
    // The sink derives its interruption tail from the actual playout cursor.
    if (processors != nullptr) {
        processors->reset();
    }
    auto interruption = player.interrupt_with_fade(interruption_fade_ms, request_id);
    const std::uint64_t playback_epoch = interruption.first;
    if (interruption.second.has_value()) {
        player.enqueue(playback_epoch, interruption.second.value());
    }
#ifdef QWEN_TTS_BRIDGE_HAS_SPEECH_ANIMATION
    if (animation_runtime != nullptr) {
        animation_runtime->invalidate(playback_epoch);
        if (animation_context != nullptr) {
            std::lock_guard<std::mutex> lock(animation_context->mutex);
            animation_context->playback_epoch = playback_epoch;
            animation_context->request_id = 0;
        }
    }
#endif
    return playback_epoch;
}

PreparedTtsRequest prepare_request(
    QwenTtsClient& preparation_client,
    const ProgramOptions& options,
    const std::string& text) {
    PreparedTtsRequest prepared_request;
    prepared_request.request.text = text;
    prepared_request.request.language = options.language;
    prepared_request.request.speaker = options.speaker;
    prepared_request.request.instruction = options.instruction;
    prepared_request.request.voice_id = options.voice_id;
    prepared_request.request.reference_audio_path = options.reference_audio_path;
    prepared_request.request.reference_text = options.reference_text;
    prepared_request.request.x_vector_only = options.x_vector_only;
    prepared_request.request.sampling.temperature = options.temperature;
    prepared_request.request.sampling.top_k = options.top_k;
    prepared_request.request.sampling.top_p = options.top_p;
    prepared_request.request.sampling.repetition_penalty = options.repetition_penalty;
    prepared_request.request.sampling.do_sample = options.do_sample;
    if (options.seed.has_value()) {
        prepared_request.request.has_seed = true;
        prepared_request.request.seed = options.seed.value();
    }
    prepared_request.request.output = requested_audio_format(options);

    TtsError error;
    if (!preparation_client.prepare_text(
            prepared_request.request,
            prepared_request.text,
            error)) {
        throw std::runtime_error(
            error.category + "/" + error.code + ": " + error.message);
    }
    std::cout << "prepared text: utf8_bytes=" << prepared_request.text.utf8_bytes
              << ", non_space_utf8_bytes="
              << prepared_request.text.non_space_utf8_bytes
              << ", modified="
              << (prepared_request.text.was_modified ? "true" : "false")
              << '\n';
    return prepared_request;
}

RequestId submit_request(
    QwenTtsClient& client,
    WaveOutPlayer& player,
    ActiveRequestState& active_state,
    const ProgramOptions& options,
    PreparedTtsRequest prepared_request,
    OneShotState* one_shot_state = nullptr,
    PcmCapture* pcm_capture = nullptr,
    std::optional<std::uint64_t> playback_epoch_override = std::nullopt
#ifdef QWEN_TTS_BRIDGE_HAS_SPEECH_ANIMATION
    , qwen_tts_bridge::speech_animation::PlaybackAnimationRuntime* animation_runtime = nullptr
    , PlaybackAnimationContext* animation_context = nullptr
#endif
    ) {
    const std::uint64_t playback_epoch = playback_epoch_override.value_or(
        cancel_active_request(
            client,
            player,
            active_state,
            options.terminal_fade_enabled ? options.terminal_fade.fade_ms : 0
#ifdef QWEN_TTS_BRIDGE_HAS_SPEECH_ANIMATION
            , animation_runtime, animation_context
#endif
        ));

    TtsRequest request = std::move(prepared_request.request);
    std::uint64_t animation_generation = 0;
    auto processors = make_audio_processors(options);
    {
        std::lock_guard<std::mutex> lock(active_state.mutex);
        if (active_state.next_request_id == 0) {
            throw std::runtime_error(
                "request ID space exhausted; restart the worker session");
        }
        request.id = active_state.next_request_id;
        if (request.id == std::numeric_limits<RequestId>::max()) {
            active_state.next_request_id = 0;
        }
        else {
            ++active_state.next_request_id;
        }
        active_state.active_request_id = request.id;
        active_state.active_client = &client;
        active_state.processors = processors;
    }

    const RequestId request_id = request.id;
    player.note_request_started(request_id);
#ifdef QWEN_TTS_BRIDGE_HAS_SPEECH_ANIMATION
    if (animation_runtime != nullptr) {
        if (animation_context != nullptr) {
            std::lock_guard<std::mutex> lock(animation_context->mutex);
            animation_context->playback_epoch = playback_epoch;
            animation_context->request_id = request_id;
        }
        animation_generation = animation_runtime->begin(
            playback_epoch,
            request_id,
            options.sample_rate);
    }
#endif
    TtsCallbacks callbacks;
    callbacks.on_audio = [&player, &active_state, processors, playback_epoch, request_id,
        one_shot_state, pcm_capture
#ifdef QWEN_TTS_BRIDGE_HAS_SPEECH_ANIMATION
        , animation_runtime, animation_generation
#endif
        ](const PcmChunk& chunk) {
        if (!is_active_request(active_state, request_id)) {
            return;
        }
        try {
            if (pcm_capture != nullptr) {
                pcm_capture->append(chunk);
            }
            for (const PcmChunk& processed : processors->process(chunk)) {
                player.enqueue(playback_epoch, processed);
#ifdef QWEN_TTS_BRIDGE_HAS_SPEECH_ANIMATION
                if (animation_runtime != nullptr) {
                    animation_runtime->push_audio(
                        playback_epoch,
                        animation_generation,
                        processed);
                }
#endif
            }
        }
        catch (const std::exception& exc) {
            fail_playback_request(
                player,
                active_state,
                request_id,
                playback_epoch,
                one_shot_state,
                exc.what());
        }
    };
    callbacks.on_completed = [&player, &active_state, processors, playback_epoch,
        one_shot_state, request_id
#ifdef QWEN_TTS_BRIDGE_HAS_SPEECH_ANIMATION
        , animation_runtime, animation_generation
#endif
        ] {
        if (!is_active_request(active_state, request_id)) {
            return;
        }
        try {
            for (const PcmChunk& processed :
                 processors->finish(AudioTerminalReason::Completed)) {
                player.enqueue(playback_epoch, processed);
#ifdef QWEN_TTS_BRIDGE_HAS_SPEECH_ANIMATION
                if (animation_runtime != nullptr) {
                    animation_runtime->push_audio(
                        playback_epoch,
                        animation_generation,
                        processed);
                }
#endif
            }
        }
        catch (const std::exception& exc) {
            fail_playback_request(
                player,
                active_state,
                request_id,
                playback_epoch,
                one_shot_state,
                exc.what());
            return;
        }
        if (!complete_active_request(active_state, request_id)) {
            return;
        }
        player.note_request_terminal(request_id, "completed");
        if (one_shot_state != nullptr) {
            mark_one_shot_terminal(one_shot_state, true);
        }
        else {
            std::cout << "completed request " << request_id << '\n';
        }
    };
    const std::uint32_t interruption_fade_ms =
        options.terminal_fade_enabled ? options.terminal_fade.fade_ms : 0;
    callbacks.on_cancelled = [
        &player,
        &active_state,
        processors,
        playback_epoch,
        one_shot_state,
        request_id,
        interruption_fade_ms] {
        if (clear_active_request(active_state, request_id)) {
            try {
                processors->reset();
                const auto interruption = player.interrupt_with_fade_if_epoch(
                    playback_epoch,
                    interruption_fade_ms,
                    request_id);
                if (interruption.has_value() && interruption->second.has_value()) {
                    player.enqueue(interruption->first, interruption->second.value());
                }
            }
            catch (const std::exception& exc) {
                std::cerr << "audio post-processing error: " << exc.what() << '\n';
            }
        }
        player.note_request_terminal(request_id, "cancelled");
        mark_one_shot_terminal(one_shot_state, false, "request cancelled");
    };
    callbacks.on_error = [
        &player,
        &active_state,
        processors,
        playback_epoch,
        one_shot_state,
        request_id](const TtsError& error) {
        if (clear_active_request(active_state, request_id)) {
            try {
                processors->reset();
                static_cast<void>(player.reset_if_epoch(playback_epoch));
            }
            catch (const std::exception& exc) {
                std::cerr << "audio post-processing error: " << exc.what() << '\n';
            }
        }
        player.note_request_terminal(request_id, "failed");
        mark_one_shot_terminal(
            one_shot_state,
            false,
            error.category + "/" + error.code + ": " + error.message);
        if (one_shot_state == nullptr) {
            std::cerr << "request " << request_id << " failed: " << error.category
                      << '/' << error.code << ": " << error.message << '\n';
        }
    };

#ifdef QWEN_TTS_BRIDGE_HAS_SPEECH_ANIMATION
    if (animation_runtime != nullptr) {
        callbacks = animation_runtime->make_callbacks(std::move(callbacks), false);
    }
#endif

    prepared_request.request = std::move(request);
    if (client.synthesize_async(
            std::move(prepared_request), std::move(callbacks)) != request_id) {
        clear_active_request(active_state, request_id);
        throw std::runtime_error("failed to enqueue synthesis request");
    }
    return request_id;
}

QwenTtsClient& client_for_text(
    const ProgramOptions& options,
    const PreparedText& prepared_text,
    QwenTtsClient& fast_client,
    QwenTtsClient* safe_client) {
    if (!options.auto_profile) {
        return fast_client;
    }
    if (safe_client == nullptr) {
        throw std::runtime_error("automatic profile routing has no safe worker");
    }
    const std::size_t estimated_bytes = prepared_text.non_space_utf8_bytes;
    const bool use_fast = estimated_bytes <= options.auto_fast_max_bytes;
    std::cout << "auto profile: " << (use_fast ? "cmp50hx-fastest" : "cmp50hx-safe")
              << " (non-space UTF-8 bytes=" << estimated_bytes << ")\n";
    return use_fast ? fast_client : *safe_client;
}

bool wait_for_one_shot(OneShotState& state, std::chrono::milliseconds timeout) {
    std::unique_lock<std::mutex> lock(state.mutex);
    return state.condition.wait_for(lock, timeout, [&state] { return state.terminal; });
}

void print_interactive_status(const ProgramOptions& options) {
    if (options.auto_profile) {
        std::cout << "profile=auto (fast <= " << options.auto_fast_max_bytes
                  << " non-space UTF-8 bytes, safe above)\n";
    }
    std::cout << "speaker=" << (options.speaker.empty() ? "<worker default>" : options.speaker)
              << ", voice_id=" << (options.voice_id.empty() ? "<none>" : options.voice_id)
              << ", language=" << options.language
              << ", style=" << (options.instruction.empty() ? "<none>" : options.instruction)
              << "\n";
    std::cout << "sampling: temperature="
              << (options.temperature.has_value() ? std::to_string(options.temperature.value()) : "<worker default>")
              << ", top_k="
              << (options.top_k.has_value() ? std::to_string(options.top_k.value()) : "<worker default>")
              << ", top_p="
              << (options.top_p.has_value() ? std::to_string(options.top_p.value()) : "<worker default>")
              << ", repetition_penalty="
              << (options.repetition_penalty.has_value() ? std::to_string(options.repetition_penalty.value()) : "<worker default>")
              << ", do_sample=";
    if (!options.do_sample.has_value()) {
        std::cout << "<worker default>";
    }
    else {
        std::cout << (options.do_sample.value() ? "on" : "off");
    }
    std::cout << ", seed="
              << (options.seed.has_value() ? std::to_string(options.seed.value()) : "<worker default>")
              << '\n';
    std::cout << "worker capabilities: sampling_overrides="
              << (options.sampling_overrides_supported ? "true" : "false")
              << ", deterministic_seed="
              << (options.deterministic_seed_supported ? "true" : "false")
              << ", voice_clone="
              << (options.voice_clone_supported ? "true" : "false")
              << ", voice_profiles="
              << (options.voice_profiles_supported ? "true" : "false")
              << '\n';
    if (!options.reference_audio_path.empty()) {
        std::cout << "voice clone: reference_audio=" << options.reference_audio_path
                  << ", mode=" << (options.x_vector_only ? "x_vector_only" : "icl")
                  << '\n';
    }
}

bool has_sampling_overrides(const ProgramOptions& options) {
    return options.temperature.has_value() ||
           options.top_k.has_value() ||
           options.top_p.has_value() ||
           options.repetition_penalty.has_value() ||
           options.do_sample.has_value();
}

void require_sampling_overrides_supported(const ProgramOptions& options) {
    if (!options.sampling_overrides_supported) {
        throw std::runtime_error(
            "sampling overrides are disabled by the active worker profile; "
            "use the StyleExperiment launcher profile");
    }
}

void require_deterministic_seed_supported(const ProgramOptions& options) {
    if (!options.deterministic_seed_supported) {
        throw std::runtime_error(
            "the active worker profile does not guarantee deterministic explicit seeds");
    }
}

bool apply_interactive_command(ProgramOptions& options, const std::string& line) {
    const auto split = line.find(' ');
    const std::string command = line.substr(0, split);
    const std::string value = split == std::string::npos ? "" : line.substr(split + 1);

    if (command == "/voice") {
        if (value.empty()) {
            std::cerr << "usage: /voice <name>\n";
        }
        else if (options.voice_profiles_supported) {
            options.voice_id = value;
            options.speaker.clear();
            print_interactive_status(options);
        }
        else {
            options.speaker = value;
            options.voice_id.clear();
            print_interactive_status(options);
        }
        return true;
    }
    if (command == "/voices") {
        if (!options.voice_profiles_supported) {
            std::cout << "the active worker has no registered voice profiles\n";
        }
        else if (options.voice_ids.empty()) {
            std::cout << "the voice registry is empty\n";
        }
        else {
            std::cout << "registered voice profiles:\n";
            for (const std::string& voice_id : options.voice_ids) {
                std::cout << "  " << voice_id << '\n';
            }
        }
        return true;
    }
    if (command == "/language") {
        if (value.empty()) {
            std::cerr << "usage: /language <name>\n";
        }
        else {
            options.language = value;
            print_interactive_status(options);
        }
        return true;
    }
    if (command == "/style") {
        options.instruction = value;
        print_interactive_status(options);
        return true;
    }
    if (command == "/temperature") {
        if (value == "default") {
            options.temperature.reset();
        }
        else {
            require_sampling_overrides_supported(options);
            const double temperature = parse_double(value, "/temperature");
            if (temperature <= 0.0 || temperature > 2.0) {
                throw std::runtime_error("/temperature must be in the interval (0, 2]");
            }
            options.temperature = temperature;
        }
        print_interactive_status(options);
        return true;
    }
    if (command == "/top-k") {
        if (value == "default") {
            options.top_k.reset();
        }
        else {
            require_sampling_overrides_supported(options);
            const std::uint32_t top_k = parse_u32(value, "/top-k");
            if (top_k == 0) {
                throw std::runtime_error("/top-k must be greater than zero");
            }
            options.top_k = top_k;
        }
        print_interactive_status(options);
        return true;
    }
    if (command == "/top-p") {
        if (value == "default") {
            options.top_p.reset();
        }
        else {
            require_sampling_overrides_supported(options);
            const double top_p = parse_double(value, "/top-p");
            if (top_p <= 0.0 || top_p > 1.0) {
                throw std::runtime_error("/top-p must be in the interval (0, 1]");
            }
            options.top_p = top_p;
        }
        print_interactive_status(options);
        return true;
    }
    if (command == "/repetition-penalty") {
        if (value == "default") {
            options.repetition_penalty.reset();
        }
        else {
            require_sampling_overrides_supported(options);
            const double repetition_penalty = parse_double(value, "/repetition-penalty");
            if (repetition_penalty < 1.0 || repetition_penalty > 2.0) {
                throw std::runtime_error("/repetition-penalty must be in the interval [1, 2]");
            }
            options.repetition_penalty = repetition_penalty;
        }
        print_interactive_status(options);
        return true;
    }
    if (command == "/sample") {
        if (value == "on") {
            require_sampling_overrides_supported(options);
            options.do_sample = true;
        }
        else if (value == "off") {
            require_sampling_overrides_supported(options);
            options.do_sample = false;
        }
        else if (value == "default") {
            options.do_sample.reset();
        }
        else {
            std::cerr << "usage: /sample <on|off|default>\n";
            return true;
        }
        print_interactive_status(options);
        return true;
    }
    if (command == "/seed") {
        if (value == "default" || value == "off") {
            options.seed.reset();
        }
        else {
            require_deterministic_seed_supported(options);
            options.seed = parse_u64(value, "/seed");
        }
        print_interactive_status(options);
        return true;
    }
    if (command == "/sampling") {
        print_interactive_status(options);
        return true;
    }
    return false;
}

std::string utf8_from_wide(const std::wstring& value) {
    if (value.empty()) {
        return {};
    }

    const int byte_count = WideCharToMultiByte(
        CP_UTF8,
        WC_ERR_INVALID_CHARS,
        value.data(),
        static_cast<int>(value.size()),
        nullptr,
        0,
        nullptr,
        nullptr);
    if (byte_count <= 0) {
        throw std::runtime_error("failed to convert console input to UTF-8");
    }

    std::string utf8(static_cast<std::size_t>(byte_count), '\0');
    if (WideCharToMultiByte(
            CP_UTF8,
            WC_ERR_INVALID_CHARS,
            value.data(),
            static_cast<int>(value.size()),
            utf8.data(),
            byte_count,
            nullptr,
            nullptr) <= 0) {
        throw std::runtime_error("failed to convert console input to UTF-8");
    }
    return utf8;
}

bool read_interactive_line(std::string& line) {
    const HANDLE input = GetStdHandle(STD_INPUT_HANDLE);
    DWORD console_mode = 0;
    if (input == INVALID_HANDLE_VALUE ||
        input == nullptr ||
        !GetConsoleMode(input, &console_mode)) {
        return static_cast<bool>(std::getline(std::cin, line));
    }

    std::array<wchar_t, 4096> wide_buffer{};
    DWORD characters_read = 0;
    if (!ReadConsoleW(
            input,
            wide_buffer.data(),
            static_cast<DWORD>(wide_buffer.size() - 1),
            &characters_read,
            nullptr)) {
        return false;
    }

    std::wstring wide_line(wide_buffer.data(), characters_read);
    while (!wide_line.empty() &&
           (wide_line.back() == L'\r' || wide_line.back() == L'\n')) {
        wide_line.pop_back();
    }
    line = utf8_from_wide(wide_line);
    return true;
}

} // namespace

int wmain(int argc, wchar_t** argv) {
    try {
        ConsoleCodePageGuard console_code_page_guard;
        ProgramOptions options = parse_options(argc, argv);
        validate_options(options);
        if (options.help) {
            print_usage(std::cout, utf8_from_wide(argv[0]));
            return 0;
        }
        if (options.self_test_playback_lifecycle) {
            return run_playback_lifecycle_self_test();
        }

        QwenTtsClientOptions client_options;
        client_options.session.startup_timeout = options.startup_timeout;

        QwenTtsClient client;
        if (!client.start(make_transport_options(options), client_options)) {
            throw std::runtime_error("failed to start Qwen TTS worker");
        }
        std::unique_ptr<QwenTtsClient> safe_client;
        if (options.auto_profile) {
            safe_client = std::make_unique<QwenTtsClient>();
            if (!safe_client->start(make_transport_options(options, true), client_options)) {
                client.stop();
                throw std::runtime_error("failed to start automatic safe Qwen TTS worker");
            }
        }
        ReadyMessage ready;
        if (!client.ready_message(ready)) {
            if (safe_client != nullptr) {
                safe_client->stop();
            }
            client.stop();
            throw std::runtime_error("worker did not expose a ready payload");
        }
        if (safe_client != nullptr) {
            ReadyMessage safe_ready;
            if (!safe_client->ready_message(safe_ready)) {
                client.stop();
                safe_client->stop();
                throw std::runtime_error("safe worker did not expose a ready payload");
            }
            if (safe_ready.capabilities.voice_clone != ready.capabilities.voice_clone ||
                safe_ready.capabilities.voice_profiles != ready.capabilities.voice_profiles) {
                client.stop();
                safe_client->stop();
                throw std::runtime_error("automatic profile workers expose incompatible capabilities");
            }
        }
        options.sampling_overrides_supported = ready.capabilities.sampling_overrides;
        options.deterministic_seed_supported = ready.capabilities.deterministic_seed;
        options.voice_clone_supported = ready.capabilities.voice_clone;
        options.voice_profiles_supported = ready.capabilities.voice_profiles;
        options.voice_ids = ready.voice_ids;
        if (!options.reference_audio_path.empty() && !options.voice_clone_supported) {
            client.stop();
            throw std::runtime_error(
                "the active worker does not advertise voice clone support; "
                "launch a Qwen Base model with --reference-audio");
        }
        if (!options.voice_id.empty() && !options.voice_profiles_supported) {
            client.stop();
            throw std::runtime_error(
                "the active worker has no registered voice-profile registry; "
                "launch it with --voice-registry-path");
        }
        if (has_sampling_overrides(options) && !options.sampling_overrides_supported) {
            client.stop();
            throw std::runtime_error(
                "sampling overrides are disabled by the active worker profile; "
                "use the StyleExperiment launcher profile");
        }
        if (options.seed.has_value() && !options.deterministic_seed_supported) {
            client.stop();
            throw std::runtime_error(
                "the active worker profile does not guarantee deterministic explicit seeds");
        }

        std::unique_ptr<WprPlaybackMarkers> etw_playback_markers;
        if (options.etw_playback_markers) {
            etw_playback_markers = std::make_unique<WprPlaybackMarkers>();
        }
        std::unique_ptr<PlaybackMetrics> playback_metrics;
        if (!options.playback_metrics_file.empty()) {
            playback_metrics = std::make_unique<PlaybackMetrics>(etw_playback_markers.get());
        }
        const PlaybackSinkMode playback_sink_mode = !options.playback_enabled
            ? PlaybackSinkMode::Disabled
            : (options.use_mock_playback_sink
                    ? PlaybackSinkMode::Mock
                    : PlaybackSinkMode::WaveOut);
        std::unique_ptr<PcmCapture> pcm_capture;
        if (!options.pcm_capture_file.empty()) {
            pcm_capture = std::make_unique<PcmCapture>(options.pcm_capture_file);
        }
        std::optional<MockPlaybackFailureStage> mock_failure_stage;
        if (options.mock_playback_fail_stage.has_value()) {
            mock_failure_stage = options.mock_playback_fail_stage.value() == "prepare"
                ? MockPlaybackFailureStage::Prepare
                : MockPlaybackFailureStage::Write;
        }
        WaveOutPlayer player(
            playback_sink_mode,
            playback_metrics.get(),
            options.playback_prebuffer_chunks,
            options.mock_playback_fail_after_submissions,
            mock_failure_stage);
        ActiveRequestState active_state;

#ifdef QWEN_TTS_BRIDGE_HAS_SPEECH_ANIMATION
        std::shared_ptr<PlaybackAnimationContext> animation_context;
        std::shared_ptr<std::mutex> animation_receipt_mutex;
        std::shared_ptr<std::ofstream> animation_receipt_output;
        std::shared_ptr<PlaybackAnimationDiagnosticQueue> animation_diagnostics;
        std::unique_ptr<qwen_tts_bridge::speech_animation::PlaybackAnimationRuntime>
            animation_runtime;
        PlaybackAnimationLoop animation_loop;
        if (!options.playback_animation_receipts_file.empty()) {
            const auto receipt_path = std::filesystem::u8path(
                options.playback_animation_receipts_file);
            if (std::filesystem::exists(receipt_path)) {
                throw std::runtime_error(
                    "refusing to overwrite existing playback animation receipts file: " +
                    options.playback_animation_receipts_file);
            }
            animation_receipt_output = std::make_shared<std::ofstream>(
                receipt_path,
                std::ios::binary | std::ios::trunc);
            if (!*animation_receipt_output) {
                throw std::runtime_error(
                    "failed to open playback animation receipts file: " +
                    options.playback_animation_receipts_file);
            }
            animation_context = std::make_shared<PlaybackAnimationContext>();
            {
                std::lock_guard<std::mutex> lock(animation_context->mutex);
                // The animation loop can tick before the first request is
                // submitted. Start it on the player's current epoch so an
                // early diagnostic/selection cannot publish epoch zero.
                animation_context->playback_epoch = player.playback_epoch();
            }
            animation_receipt_mutex = std::make_shared<std::mutex>();
            animation_diagnostics =
                std::make_shared<PlaybackAnimationDiagnosticQueue>();
            animation_runtime = std::make_unique<
                qwen_tts_bridge::speech_animation::PlaybackAnimationRuntime>(
                [&player, animation_context] {
                    std::lock_guard<std::mutex> lock(animation_context->mutex);
                    const auto snapshot = player.playback_cursor_snapshot(
                        animation_context->playback_epoch,
                        animation_context->request_id);
                    return ::speech_animation::integration::PlaybackCursorSnapshot{
                        snapshot.playback_epoch,
                        snapshot.request_id,
                        snapshot.utterance_sample,
                        snapshot.sample_rate,
                        snapshot.position_available};
                },
                [animation_receipt_output, animation_receipt_mutex](
                    const auto& selection) {
                    std::lock_guard<std::mutex> lock(*animation_receipt_mutex);
                    *animation_receipt_output << selection.to_json() << '\n';
                    animation_receipt_output->flush();
                },
                [animation_diagnostics](const auto& diagnostic) {
                    std::lock_guard<std::mutex> lock(animation_diagnostics->mutex);
                    animation_diagnostics->records.push_back(diagnostic);
                });
            animation_runtime->initialize_epoch(player.playback_epoch());
            animation_loop.start(
                [&animation_runtime,
                 animation_diagnostics,
                 animation_receipt_output,
                 animation_receipt_mutex] {
                    static_cast<void>(animation_runtime->tick());
                    std::deque<PlaybackAnimationDiagnostic> diagnostics;
                    {
                        std::lock_guard<std::mutex> lock(animation_diagnostics->mutex);
                        diagnostics.swap(animation_diagnostics->records);
                    }
                    if (!diagnostics.empty()) {
                        std::lock_guard<std::mutex> lock(*animation_receipt_mutex);
                        for (const auto& diagnostic : diagnostics) {
                            *animation_receipt_output
                                << "{\"type\":\"diagnostic\",\"request_id\":"
                                << diagnostic.request_id
                                << ",\"code\":\""
                                << json_escape(diagnostic.code)
                                << "\",\"message\":\""
                                << json_escape(diagnostic.message) << "\"}\n";
                        }
                        animation_receipt_output->flush();
                    }
                },
                options.playback_animation_fps);
        }
#endif

        if (!options.text.empty()) {
            OneShotState state;
            if (playback_metrics != nullptr) {
                playback_metrics->begin_request();
            }
            auto prepared_request = prepare_request(client, options, options.text);
            submit_request(
                client_for_text(
                    options,
                    prepared_request.text,
                    client,
                    safe_client.get()),
                player,
                active_state,
                options,
                std::move(prepared_request),
                &state,
                pcm_capture.get(),
                std::nullopt
#ifdef QWEN_TTS_BRIDGE_HAS_SPEECH_ANIMATION
                , animation_runtime.get(), animation_context.get()
#endif
            );
            if (!wait_for_one_shot(state, std::chrono::minutes(5))) {
                cancel_active_request(
                    client,
                    player,
                    active_state,
                    options.terminal_fade_enabled ? options.terminal_fade.fade_ms : 0
#ifdef QWEN_TTS_BRIDGE_HAS_SPEECH_ANIMATION
                    , animation_runtime.get(), animation_context.get()
#endif
                );
                if (safe_client != nullptr) {
                    safe_client->stop();
                }
                client.stop();
                throw std::runtime_error("one-shot synthesis timed out");
            }
            if (!state.success) {
                if (safe_client != nullptr) {
                    safe_client->stop();
                }
                client.stop();
                throw std::runtime_error(state.message.empty() ? "one-shot synthesis failed" : state.message);
            }
            player.wait_until_idle(std::chrono::minutes(5));
            if (pcm_capture != nullptr) {
                pcm_capture->finalize();
            }
            if (playback_metrics != nullptr) {
                playback_metrics->mark_playback_completed();
                playback_metrics->write_json_file(options.playback_metrics_file);
            }
            client.stop();
            if (safe_client != nullptr) {
                safe_client->stop();
            }
            if (!options.playback_interruption_diagnostics_file.empty()) {
                player.write_interruption_diagnostics_file(
                    options.playback_interruption_diagnostics_file);
            }
            return 0;
        }

        print_usage(std::cout, utf8_from_wide(argv[0]));
        print_interactive_status(options);
        for (std::string line; std::cout << "> " && read_interactive_line(line);) {
            if (line.empty()) {
                continue;
            }
            if (line == "/quit" || line == "/exit") {
                break;
            }
            if (line == "/help") {
                print_usage(std::cout, utf8_from_wide(argv[0]));
                continue;
            }
            if (line == "/cancel") {
                cancel_active_request(
                    client,
                    player,
                    active_state,
                    options.terminal_fade_enabled ? options.terminal_fade.fade_ms : 0
#ifdef QWEN_TTS_BRIDGE_HAS_SPEECH_ANIMATION
                    , animation_runtime.get(), animation_context.get()
#endif
                );
                std::cout << "cancelled active request\n";
                continue;
            }
            if (line.front() == '/') {
                try {
                    if (!apply_interactive_command(options, line)) {
                        std::cerr << "unknown command; use /help\n";
                    }
                }
                catch (const std::exception& exc) {
                    std::cerr << "command error: " << exc.what() << '\n';
                }
                continue;
            }
            const std::uint64_t playback_epoch = cancel_active_request(
                client,
                player,
                active_state,
                options.terminal_fade_enabled ? options.terminal_fade.fade_ms : 0
#ifdef QWEN_TTS_BRIDGE_HAS_SPEECH_ANIMATION
                , animation_runtime.get(), animation_context.get()
#endif
            );
            PreparedTtsRequest prepared_request;
            try {
                prepared_request = prepare_request(client, options, line);
            }
            catch (const std::exception& exc) {
                std::cerr << "text preparation failed: " << exc.what() << '\n';
                continue;
            }
            submit_request(
                client_for_text(
                    options,
                    prepared_request.text,
                    client,
                    safe_client.get()),
                player,
                active_state,
                options,
                std::move(prepared_request),
                nullptr,
                nullptr,
                playback_epoch
#ifdef QWEN_TTS_BRIDGE_HAS_SPEECH_ANIMATION
                , animation_runtime.get(), animation_context.get()
#endif
            );
        }

        cancel_active_request(
            client,
            player,
            active_state,
            options.terminal_fade_enabled ? options.terminal_fade.fade_ms : 0
#ifdef QWEN_TTS_BRIDGE_HAS_SPEECH_ANIMATION
            , animation_runtime.get(), animation_context.get()
#endif
        );
        client.stop();
        if (safe_client != nullptr) {
            safe_client->stop();
        }
        if (!options.playback_interruption_diagnostics_file.empty()) {
            player.write_interruption_diagnostics_file(
                options.playback_interruption_diagnostics_file);
        }
        return 0;
    }
    catch (const std::exception& exc) {
        std::cerr << "qwen_tts_play: " << exc.what() << '\n';
        std::cerr << "Run with --help for usage.\n";
        return 1;
    }
}
