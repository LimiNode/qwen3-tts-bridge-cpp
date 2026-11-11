#include <qwen_tts_bridge/client.hpp>

#include "latency_benchmark.hpp"

#include <algorithm>
#include <iostream>

namespace qwen_tts_examples::benchmark {

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

} // namespace qwen_tts_examples::benchmark
