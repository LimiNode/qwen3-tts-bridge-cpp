#pragma once

// Private to the benchmark executable, not an installed SDK surface.
#include <qwen_tts_bridge/client.hpp>
#include <qwen_tts_bridge/transport.hpp>
#include <nlohmann/json.hpp>

#include "latency_benchmark/types.hpp"

#include <iosfwd>

namespace qwen_tts_examples::benchmark {

void print_usage(std::ostream& out, const char* executable_name);
ProgramOptions parse_options(int argc, char** argv);
void validate_options(const ProgramOptions& options);
std::vector<RequestSpec> load_request_manifest(const ProgramOptions& options);
void validate_request_contract(RequestResult& result);
void validate_generic_acceptance(RequestResult& result);
bool has_contract_failures(const std::vector<RequestResult>& results);
bool has_acceptance_failures(const std::vector<RequestResult>& results);
int run_eos_contract_self_test();
void write_results_json(std::ostream& out, const ProgramOptions& options,
    double startup_ms, const std::vector<RequestResult>& warmups,
    const std::vector<RequestResult>& measured);

} // namespace qwen_tts_examples::benchmark
