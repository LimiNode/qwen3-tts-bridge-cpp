#include "latency_benchmark.hpp"

#include <iostream>
#include <sstream>
#include <stdexcept>

namespace {
using namespace qwen_tts_examples::benchmark;

void require(bool condition, const char* message) {
    if (!condition) {
        throw std::runtime_error(message);
    }
}

void check_report() {
    ProgramOptions options;
    options.text = "quote\" newline\n UTF-8: \xc3\xa9";
    RequestResult accepted;
    accepted.request_id = 42;
    accepted.success = true;
    accepted.first_audio_ms = 12.0;
    accepted.completion_execution_outcome = "natural_eos";
    qwen_tts_bridge::TtsCompletion completion;
    completion.execution_outcome = "natural_eos";
    accepted.completion_metadata = completion;
    std::ostringstream output;
    write_results_json(output, options, 2.0, {}, {accepted});
    const auto report = nlohmann::json::parse(output.str());
    require(report.at("config").at("text") == options.text, "report text/escaping changed");
    require(report.at("startup_ms") == 2.0, "startup value changed");
    require(report.at("warmups").empty(), "empty warmups changed");
    const auto& result = report.at("requests").at(0);
    require(result.at("completed_ms").is_null(), "missing timings must remain null");
    require(result.at("request_id") == 42, "report request ID changed");
    require(result.at("completion_metadata").at("execution_outcome") == "natural_eos",
        "completion evidence lost");
    require(report.at("summary").at("first_audio_ms").at("median") == 12.0,
        "metric summary changed");
    accepted.acceptance_valid = false;
    std::ostringstream excluded;
    write_results_json(excluded, options, 2.0, {}, {accepted});
    const auto excluded_report = nlohmann::json::parse(excluded.str());
    require(excluded_report.at("summary").at("first_audio_ms").is_null(),
        "invalid result leaked into aggregate metrics");
}

void check_acceptance() {
    RequestResult expected_error;
    expected_error.error_category = "request_error";
    expected_error.error_code = "invalid_request";
    expected_error.allowed_errors = {{"request_error", "invalid_request"}};
    validate_generic_acceptance(expected_error);
    require(expected_error.acceptance_valid, "allowed negative outcome rejected");
    auto unexpected_error = expected_error;
    unexpected_error.error_code = "different_error";
    validate_generic_acceptance(unexpected_error);
    require(!unexpected_error.acceptance_valid, "unexpected error accepted");
    auto late_error = expected_error;
    late_error.late_audio_after_terminal_count = 1;
    validate_generic_acceptance(late_error);
    require(!late_error.acceptance_valid, "late PCM accepted");

    RequestResult missing_telemetry;
    missing_telemetry.success = true;
    missing_telemetry.expected_prefill_length = 16;
    missing_telemetry.expected_chunk_schedule = {8};
    validate_request_contract(missing_telemetry);
    require(missing_telemetry.contract_checked && !missing_telemetry.contract_valid,
        "missing contract evidence accepted");
}
} // namespace

int main(int argc, char** argv) {
    try {
        require(argc == 3, "expected valid and invalid manifest fixture paths");
        std::vector<std::string> arguments = {"benchmark", "--mock", "--requests=2",
            "--warmups", "0", "--terminal-quiet-ms=5"};
        std::vector<char*> pointers;
        for (auto& argument : arguments) {
            pointers.push_back(argument.data());
        }
        auto options = parse_options(static_cast<int>(pointers.size()), pointers.data());
        validate_options(options);
        require(options.requests == 2 && options.warmups == 0 &&
            options.terminal_quiet.count() == 5, "parsed options changed");
        options.request_manifest = argv[1];
        const auto specs = load_request_manifest(options);
        require(specs.size() == 2 && specs[0].cancel_after_first_pcm &&
            specs[0].allowed_terminal_outcomes == std::vector<std::string>{"cancelled"},
            "manifest cancellation semantics changed");
        options.request_manifest = argv[2];
        bool rejected = false;
        try {
            load_request_manifest(options);
        }
        catch (const std::runtime_error& error) {
            rejected = std::string(error.what()).find("invalid expected_* contract") !=
                std::string::npos;
        }
        require(rejected, "invalid manifest contract was accepted or error changed");
        check_acceptance();
        check_report();
        return 0;
    }
    catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
