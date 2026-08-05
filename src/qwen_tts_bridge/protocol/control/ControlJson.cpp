#include "ControlCodecInternal.hpp"

#include <algorithm>
#include <cmath>
#include <initializer_list>
#include <limits>
#include <utility>

namespace qwen_tts_bridge::control_detail {

std::string bytes_to_string(const std::byte* data, std::size_t size) {
    if (data == nullptr || size == 0) {
        return {};
    }

    return std::string(reinterpret_cast<const char*>(data), size);
}

std::vector<std::byte> string_to_bytes(const std::string& value) {
    std::vector<std::byte> bytes;
    bytes.reserve(value.size());
    for (const char ch : value) {
        bytes.push_back(static_cast<std::byte>(static_cast<unsigned char>(ch)));
    }
    return bytes;
}

ControlDecodeResult control_error(
    ControlCodecError error,
    std::string diagnostic) {
    ControlDecodeResult result;
    result.error = error;
    result.diagnostic = std::move(diagnostic);
    return result;
}

ErrorDecodeResult error_error(
    ControlCodecError error,
    std::string diagnostic) {
    ErrorDecodeResult result;
    result.error = error;
    result.diagnostic = std::move(diagnostic);
    return result;
}

JsonPayloadEncodeResult encode_error(
    ControlCodecError error,
    std::string diagnostic) {
    JsonPayloadEncodeResult result;
    result.error = error;
    result.diagnostic = std::move(diagnostic);
    return result;
}

bool has_forbidden_header_field(const Json& object) {
    return object.contains(kProtocolVersion) || object.contains(kRequestId);
}

bool reject_unknown_fields(
    const Json& object,
    std::initializer_list<const char*> allowed,
    const char* object_name,
    std::string& diagnostic,
    ControlCodecError& error) {
    for (const auto& entry : object.items()) {
        const bool known = std::any_of(
            allowed.begin(),
            allowed.end(),
            [&entry](const char* name) { return entry.key() == name; });
        if (!known) {
            error = ControlCodecError::UnknownField;
            diagnostic = std::string(object_name) + " contains unknown field: " + entry.key();
            return false;
        }
    }
    return true;
}

const Json* find_field(const Json& object, const char* name) {
    const auto it = object.find(name);
    if (it == object.end()) {
        return nullptr;
    }
    return &(*it);
}

bool read_required_string(
    const Json& object,
    const char* name,
    std::string& out,
    std::string& diagnostic,
    ControlCodecError& error) {
    const Json* value = find_field(object, name);
    if (value == nullptr) {
        error = ControlCodecError::MissingRequiredField;
        diagnostic = std::string("missing required field: ") + name;
        return false;
    }
    if (!value->is_string()) {
        error = ControlCodecError::InvalidFieldType;
        diagnostic = std::string("field must be a string: ") + name;
        return false;
    }

    out = value->get<std::string>();
    return true;
}

bool read_optional_string(
    const Json& object,
    const char* name,
    std::string& out,
    std::string& diagnostic,
    ControlCodecError& error) {
    const Json* value = find_field(object, name);
    if (value == nullptr) {
        return true;
    }
    if (!value->is_string()) {
        error = ControlCodecError::InvalidFieldType;
        diagnostic = std::string("field must be a string: ") + name;
        return false;
    }

    out = value->get<std::string>();
    return true;
}

bool read_optional_string_array(
    const Json& object,
    const char* name,
    std::vector<std::string>& out,
    std::string& diagnostic,
    ControlCodecError& error) {
    const Json* value = find_field(object, name);
    if (value == nullptr) {
        return true;
    }
    if (!value->is_array()) {
        error = ControlCodecError::InvalidFieldType;
        diagnostic = std::string("field must be an array: ") + name;
        return false;
    }
    std::vector<std::string> items;
    items.reserve(value->size());
    for (const Json& item : *value) {
        if (!item.is_string() || item.get<std::string>().empty()) {
            error = ControlCodecError::InvalidFieldType;
            diagnostic = std::string("field must contain non-empty strings: ") + name;
            return false;
        }
        items.push_back(item.get<std::string>());
    }
    out = std::move(items);
    return true;
}

bool read_optional_bool(
    const Json& object,
    const char* name,
    bool& out,
    bool& present,
    std::string& diagnostic,
    ControlCodecError& error) {
    const Json* value = find_field(object, name);
    if (value == nullptr) {
        present = false;
        return true;
    }
    if (!value->is_boolean()) {
        error = ControlCodecError::InvalidFieldType;
        diagnostic = std::string("field must be a bool: ") + name;
        return false;
    }

    present = true;
    out = value->get<bool>();
    return true;
}

bool read_required_bool(
    const Json& object,
    const char* name,
    bool& out,
    std::string& diagnostic,
    ControlCodecError& error) {
    const Json* value = find_field(object, name);
    if (value == nullptr) {
        error = ControlCodecError::MissingRequiredField;
        diagnostic = std::string("missing required field: ") + name;
        return false;
    }
    if (!value->is_boolean()) {
        error = ControlCodecError::InvalidFieldType;
        diagnostic = std::string("field must be a bool: ") + name;
        return false;
    }

    out = value->get<bool>();
    return true;
}

bool json_to_u64(const Json& value, std::uint64_t& out) {
    if (value.is_number_unsigned()) {
        out = value.get<std::uint64_t>();
        return true;
    }
    if (!value.is_number_integer()) {
        return false;
    }

    const auto signed_value = value.get<std::int64_t>();
    if (signed_value < 0) {
        return false;
    }

    out = static_cast<std::uint64_t>(signed_value);
    return true;
}

bool read_optional_u64(
    const Json& object,
    const char* name,
    std::uint64_t& out,
    bool& present,
    std::string& diagnostic,
    ControlCodecError& error) {
    const Json* value = find_field(object, name);
    if (value == nullptr) {
        present = false;
        return true;
    }

    if (!json_to_u64(*value, out)) {
        error = ControlCodecError::InvalidFieldType;
        diagnostic = std::string("field must be a non-negative integer: ") + name;
        return false;
    }

    present = true;
    return true;
}

bool read_optional_u32(
    const Json& object,
    const char* name,
    std::uint32_t& out,
    bool& present,
    std::string& diagnostic,
    ControlCodecError& error) {
    std::uint64_t value = 0;
    if (!read_optional_u64(object, name, value, present, diagnostic, error)) {
        return false;
    }
    if (!present) {
        return true;
    }
    if (value > std::numeric_limits<std::uint32_t>::max()) {
        error = ControlCodecError::InvalidFieldType;
        diagnostic = std::string("field exceeds uint32 range: ") + name;
        return false;
    }

    out = static_cast<std::uint32_t>(value);
    return true;
}

bool read_required_u32(
    const Json& object,
    const char* name,
    std::uint32_t& out,
    std::string& diagnostic,
    ControlCodecError& error) {
    bool present = false;
    if (!read_optional_u32(object, name, out, present, diagnostic, error)) {
        return false;
    }
    if (!present) {
        error = ControlCodecError::MissingRequiredField;
        diagnostic = std::string("missing required field: ") + name;
        return false;
    }
    return true;
}

bool read_audio_format(
    const Json& object,
    AudioFormat& out,
    std::string& diagnostic,
    ControlCodecError& error) {
    if (!object.is_object()) {
        error = ControlCodecError::InvalidFieldType;
        diagnostic = "audio format must be an object";
        return false;
    }

    if (!read_required_string(object, "sample_format", out.sample_format, diagnostic, error)) {
        return false;
    }
    if (!read_required_u32(object, "sample_rate", out.sample_rate, diagnostic, error)) {
        return false;
    }
    if (!read_required_u32(object, "channels", out.channels, diagnostic, error)) {
        return false;
    }

    error = validate_audio_format(out, "audio_format", diagnostic);
    if (error != ControlCodecError::None) {
        return false;
    }

    return true;
}

bool read_optional_audio_format(
    const Json& object,
    const char* name,
    AudioFormat& out,
    std::string& diagnostic,
    ControlCodecError& error) {
    const Json* value = find_field(object, name);
    if (value == nullptr) {
        return true;
    }

    return read_audio_format(*value, out, diagnostic, error);
}

bool read_required_audio_format(
    const Json& object,
    const char* name,
    AudioFormat& out,
    std::string& diagnostic,
    ControlCodecError& error) {
    const Json* value = find_field(object, name);
    if (value == nullptr) {
        error = ControlCodecError::MissingRequiredField;
        diagnostic = std::string("missing required field: ") + name;
        return false;
    }

    return read_audio_format(*value, out, diagnostic, error);
}

bool read_required_u64(
    const Json& object,
    const char* name,
    std::uint64_t& out,
    std::string& diagnostic,
    ControlCodecError& error) {
    const Json* value = find_field(object, name);
    if (value == nullptr) {
        diagnostic = std::string("missing required field: ") + name;
        error = ControlCodecError::MissingRequiredField;
        return false;
    }
    if (!value->is_number_unsigned()) {
        diagnostic = std::string("field must be an unsigned integer: ") + name;
        error = ControlCodecError::InvalidFieldType;
        return false;
    }
    out = value->get<std::uint64_t>();
    return true;
}

bool read_optional_finite_double(
    const Json& object,
    const char* name,
    std::optional<double>& out,
    std::string& diagnostic,
    ControlCodecError& error) {
    const Json* value = find_field(object, name);
    if (value == nullptr) {
        out.reset();
        return true;
    }
    if (!value->is_number()) {
        error = ControlCodecError::InvalidFieldType;
        diagnostic = std::string("field must be a finite number: ") + name;
        return false;
    }
    const double number = value->get<double>();
    if (!std::isfinite(number)) {
        error = ControlCodecError::InvalidFieldType;
        diagnostic = std::string("field must be a finite number: ") + name;
        return false;
    }
    out = number;
    return true;
}

bool read_optional_synthesis_sampling(
    const Json& object,
    const char* name,
    SynthesisSamplingOptions& out,
    std::string& diagnostic,
    ControlCodecError& error) {
    const Json* value = find_field(object, name);
    if (value == nullptr) {
        out = {};
        return true;
    }
    if (!value->is_object()) {
        error = ControlCodecError::InvalidFieldType;
        diagnostic = std::string("field must be an object: ") + name;
        return false;
    }
    if (!reject_unknown_fields(
            *value,
            {"temperature", "top_k", "top_p", "repetition_penalty", "do_sample"},
            name,
            diagnostic,
            error)) {
        return false;
    }
    std::uint32_t top_k = 0;
    bool top_k_present = false;
    bool do_sample = false;
    bool do_sample_present = false;
    if (!read_optional_finite_double(*value, "temperature", out.temperature, diagnostic, error) ||
        !read_optional_u32(*value, "top_k", top_k, top_k_present, diagnostic, error) ||
        !read_optional_finite_double(*value, "top_p", out.top_p, diagnostic, error) ||
        !read_optional_finite_double(*value, "repetition_penalty", out.repetition_penalty, diagnostic, error) ||
        !read_optional_bool(*value, "do_sample", do_sample, do_sample_present, diagnostic, error)) {
        return false;
    }
    out.top_k = top_k_present ? std::optional<std::uint32_t>(top_k) : std::nullopt;
    out.do_sample = do_sample_present ? std::optional<bool>(do_sample) : std::nullopt;
    return true;
}

bool read_completed_message(
    const Json& object,
    CompletedMessage& out,
    std::string& diagnostic,
    ControlCodecError& error) {
    if (!read_optional_string(
            object,
            "execution_outcome",
            out.execution_outcome,
            diagnostic,
            error)) {
        return false;
    }
    out.has_execution_outcome = find_field(object, "execution_outcome") != nullptr;

    const Json* trace = find_field(object, "generation_trace");
    if (trace == nullptr) {
        return true;
    }
    if (!trace->is_object()) {
        diagnostic = "generation_trace must be an object";
        error = ControlCodecError::InvalidFieldType;
        return false;
    }

    if (!read_required_string(
            *trace,
            "termination_reason",
            out.generation_trace.termination_reason,
            diagnostic,
            error) ||
        !read_required_bool(
            *trace,
            "hit_eos",
            out.generation_trace.hit_eos,
            diagnostic,
            error) ||
        !read_required_bool(
            *trace,
            "hit_max_seq_len",
            out.generation_trace.hit_max_seq_len,
            diagnostic,
            error) ||
        !read_required_bool(
            *trace,
            "hit_max_new_tokens",
            out.generation_trace.hit_max_new_tokens,
            diagnostic,
            error) ||
        !read_required_u64(
            *trace,
            "codec_frame_count",
            out.generation_trace.codec_frame_count,
            diagnostic,
            error) ||
        !read_required_u64(
            *trace,
            "generated_steps",
            out.generation_trace.generated_steps,
            diagnostic,
            error) ||
        !read_required_u64(
            *trace,
            "emitted_steps",
            out.generation_trace.emitted_steps,
            diagnostic,
            error) ||
        !read_required_u64(
            *trace,
            "terminal_step_index",
            out.generation_trace.terminal_step_index,
            diagnostic,
            error)) {
        return false;
    }
    out.has_generation_trace = true;
    return true;
}

bool read_capabilities(
    const Json& object,
    WorkerCapabilities& out,
    std::string& diagnostic,
    ControlCodecError& error) {
    const Json* value = find_field(object, "capabilities");
    if (value == nullptr) {
        error = ControlCodecError::MissingRequiredField;
        diagnostic = "missing required field: capabilities";
        return false;
    }
    if (!value->is_object()) {
        error = ControlCodecError::InvalidFieldType;
        diagnostic = "field must be an object: capabilities";
        return false;
    }

    if (!read_required_bool(*value, "streaming", out.streaming, diagnostic, error)) {
        return false;
    }
    if (!read_required_bool(*value, "cancellation", out.cancellation, diagnostic, error)) {
        return false;
    }
    if (!read_required_bool(*value, "instructions", out.instructions, diagnostic, error)) {
        return false;
    }
    if (!read_required_bool(*value, "voice_clone", out.voice_clone, diagnostic, error)) {
        return false;
    }
    bool sampling_overrides_present = false;
    if (!read_optional_bool(
            *value,
            "sampling_overrides",
            out.sampling_overrides,
            sampling_overrides_present,
            diagnostic,
            error)) {
        return false;
    }
    bool deterministic_seed_present = false;
    if (!read_optional_bool(
            *value,
            "deterministic_seed",
            out.deterministic_seed,
            deterministic_seed_present,
            diagnostic,
            error)) {
        return false;
    }
    bool voice_clone_streaming_present = false;
    if (!read_optional_bool(
            *value,
            "voice_clone_streaming",
            out.voice_clone_streaming,
            voice_clone_streaming_present,
            diagnostic,
            error)) {
        return false;
    }
    bool voice_profiles_present = false;
    if (!read_optional_bool(
            *value,
            "voice_profiles",
            out.voice_profiles,
            voice_profiles_present,
            diagnostic,
            error)) {
        return false;
    }

    return true;
}

Json audio_format_to_json(const AudioFormat& format) {
    return Json{
        {"sample_format", format.sample_format},
        {"sample_rate", format.sample_rate},
        {"channels", format.channels}
    };
}

Json synthesis_sampling_to_json(const SynthesisSamplingOptions& options) {
    Json out = Json::object();
    if (options.temperature.has_value()) {
        out["temperature"] = options.temperature.value();
    }
    if (options.top_k.has_value()) {
        out["top_k"] = options.top_k.value();
    }
    if (options.top_p.has_value()) {
        out["top_p"] = options.top_p.value();
    }
    if (options.repetition_penalty.has_value()) {
        out["repetition_penalty"] = options.repetition_penalty.value();
    }
    if (options.do_sample.has_value()) {
        out["do_sample"] = options.do_sample.value();
    }
    return out;
}

Json capabilities_to_json(const WorkerCapabilities& capabilities) {
    return Json{
        {"streaming", capabilities.streaming},
        {"cancellation", capabilities.cancellation},
        {"instructions", capabilities.instructions},
        {"voice_clone", capabilities.voice_clone},
        {"sampling_overrides", capabilities.sampling_overrides},
        {"deterministic_seed", capabilities.deterministic_seed},
        {"voice_clone_streaming", capabilities.voice_clone_streaming},
        {"voice_profiles", capabilities.voice_profiles}
    };
}

JsonPayloadEncodeResult encode_json_payload(const Json& value) {
    try {
        JsonPayloadEncodeResult result;
        result.payload = string_to_bytes(value.dump());
        return result;
    }
    catch (const std::exception& exc) {
        return encode_error(ControlCodecError::EncodeFailed, exc.what());
    }
    catch (...) {
        return encode_error(ControlCodecError::EncodeFailed, "unknown JSON encode error");
    }
}

} // namespace qwen_tts_bridge::control_detail
