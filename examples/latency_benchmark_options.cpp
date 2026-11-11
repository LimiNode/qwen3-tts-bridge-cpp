#include <qwen_tts_bridge/client.hpp>

#include "latency_benchmark.hpp"

#include "common/cli_parsing.hpp"

#include <algorithm>
#include <limits>
#include <ostream>
#include <stdexcept>

using qwen_tts_examples::cli::parse_double;
using qwen_tts_examples::cli::parse_int;
using qwen_tts_examples::cli::parse_u32;
using qwen_tts_examples::cli::parse_u64;

namespace qwen_tts_examples::benchmark {

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

ProgramOptions parse_options(int argc, char** argv) {
    ProgramOptions options;
    for (int index = 1; index < argc; ++index) {
        const std::string arg = argv[index];
        const auto require_value = [&](int& value_index, int argument_count,
                                       char**, const std::string& option) {
            const auto argument_at = [&](int argument_index) {
                return std::string(argv[argument_index]);
            };
            return qwen_tts_examples::cli::require_value(
                value_index, argument_count, arg, argument_at, option);
        };

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

} // namespace qwen_tts_examples::benchmark
