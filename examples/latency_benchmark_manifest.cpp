#include <qwen_tts_bridge/client.hpp>

#include "latency_benchmark.hpp"

#include <algorithm>
#include <fstream>
#include <stdexcept>

namespace qwen_tts_examples::benchmark {

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

} // namespace qwen_tts_examples::benchmark
