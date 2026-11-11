#include <qwen_tts_bridge/audio.hpp>

#include "play.hpp"

#include "common/cli_parsing.hpp"

#include <algorithm>
#include <cctype>
#include <filesystem>
#include <iostream>
#include <stdexcept>
#include <system_error>

#ifndef QWEN_TTS_BRIDGE_EXAMPLE_PYTHON_EXECUTABLE
#define QWEN_TTS_BRIDGE_EXAMPLE_PYTHON_EXECUTABLE ""
#endif

#ifndef QWEN_TTS_BRIDGE_EXAMPLE_WORKER_DIR
#define QWEN_TTS_BRIDGE_EXAMPLE_WORKER_DIR ""
#endif


namespace qwen_tts_examples::play {

using qwen_tts_examples::cli::parse_double;
using qwen_tts_examples::cli::parse_int;
using qwen_tts_examples::cli::parse_u32;
using qwen_tts_examples::cli::parse_u64;
using qwen_tts_bridge::StdIoTransportOptions;
using qwen_tts_bridge::AudioFormat;

bool uses_mock_worker(const ProgramOptions& options) {
    return options.use_mock_worker || std::find(
        options.worker_arguments.begin(),
        options.worker_arguments.end(),
        "mock") != options.worker_arguments.end();
}

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
        << "  --request-timeout-ms <ms>      One-shot request/playback timeout, default: 300000.\n"
        << "  --allow-non-natural-eos        Diagnostic opt-out from the natural-EOS gate.\n"
        << "  --no-playback                  Deliver PCM without opening a WaveOut device.\n"
        << "  --mock-playback-sink           Use a deterministic timed sink with --mock.\n"
        << "  --mock-playback-fail-after <n> Inject a mock sink failure after n submissions (test only).\n"
        << "  --mock-playback-fail-stage <prepare|write>  Select the injected submission stage (test only).\n"
        << "  --playback-metrics-file <path> Write opt-in one-shot WaveOut queue metrics JSON.\n"
        << "  --playback-interruption-diagnostics-file <path> Write opt-in cursor/reset cancellation diagnostics JSON.\n"
        << "  --playback-animation-receipts-file <path> Write playback-locked animation selections as JSONL.\n"
        << "  --playback-animation-fps <n> Presentation tick rate for animation receipts, default: 60.\n"
        << "  --pcm-capture-file <path>      Write opt-in one-shot raw s16le PCM plus JSON metadata.\n"
        << "  --wav-capture-file <path>      Write opt-in one-shot post-processed PCM as RIFF/WAVE.\n"
        << "  --mock-wav-capture-failure    Inject an optional WAV capture writer failure (test only).\n"
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

ProgramOptions parse_options(int argc, wchar_t** argv) {
    ProgramOptions options;
    for (int index = 1; index < argc; ++index) {
        const std::string arg = utf8_from_wide(argv[index]);
        const auto require_value = [&](int& value_index, int argument_count,
                                       wchar_t**, const std::string& option) {
            const auto argument_at = [&](int argument_index) {
                return utf8_from_wide(argv[argument_index]);
            };
            return qwen_tts_examples::cli::require_value(
                value_index, argument_count, arg, argument_at, option);
        };
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
        else if (arg == "--request-timeout-ms" ||
                 arg.rfind("--request-timeout-ms=", 0) == 0) {
            options.request_timeout = std::chrono::milliseconds(parse_u32(
                require_value(index, argc, argv, "--request-timeout-ms"),
                "--request-timeout-ms"));
        }
        else if (arg == "--allow-non-natural-eos") {
            options.require_natural_eos = false;
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
        else if (arg == "--wav-capture-file" ||
                 arg.rfind("--wav-capture-file=", 0) == 0) {
            options.wav_capture_file = require_value(index, argc, argv, "--wav-capture-file");
        }
        else if (arg == "--mock-wav-capture-failure") {
            options.mock_wav_capture_failure = true;
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

bool capture_paths_alias(const std::string& left, const std::string& right) {
    const auto normalized = [](const std::string& value) {
        auto result = std::filesystem::absolute(
            std::filesystem::u8path(value)).lexically_normal().generic_u8string();
#ifdef _WIN32
        std::transform(result.begin(), result.end(), result.begin(), [](char character) {
            return static_cast<char>(std::tolower(static_cast<unsigned char>(character)));
        });
#endif
        return result;
    };
    if (normalized(left) == normalized(right)) {
        return true;
    }
    const auto left_path = std::filesystem::u8path(left);
    const auto right_path = std::filesystem::u8path(right);
    std::error_code error;
    if (!std::filesystem::exists(left_path, error) || error) {
        return false;
    }
    error.clear();
    if (!std::filesystem::exists(right_path, error) || error) {
        return false;
    }
    error.clear();
    return std::filesystem::equivalent(left_path, right_path, error) && !error;
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
    if (options.startup_timeout.count() <= 0 || options.request_timeout.count() <= 0) {
        throw std::runtime_error("timeouts must be greater than zero");
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
    if (options.use_mock_playback_sink && !uses_mock_worker(options)) {
        throw std::runtime_error(
            "--mock-playback-sink requires a mock worker (use --mock or worker argument mock)");
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
    if (!options.wav_capture_file.empty() && options.text.empty()) {
        throw std::runtime_error("--wav-capture-file requires one-shot --text playback");
    }
    if (options.mock_wav_capture_failure) {
        if (!uses_mock_worker(options) || !options.use_mock_playback_sink) {
            throw std::runtime_error(
                "--mock-wav-capture-failure requires --mock and --mock-playback-sink");
        }
        if (options.wav_capture_file.empty()) {
            throw std::runtime_error(
                "--mock-wav-capture-failure requires --wav-capture-file");
        }
    }
    if (!options.pcm_capture_file.empty() &&
        !options.wav_capture_file.empty() &&
        capture_paths_alias(options.pcm_capture_file, options.wav_capture_file)) {
        throw std::runtime_error(
            "--pcm-capture-file and --wav-capture-file must use different paths");
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
    bool safe_profile) {
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

} // namespace qwen_tts_examples::play
