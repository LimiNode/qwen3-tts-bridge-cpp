#include "ControlCodecInternal.hpp"

#include <cmath>
#include <type_traits>
#include <utility>

namespace qwen_tts_bridge::control_detail {

ControlCodecError validate_non_empty_string(
    const std::string& value,
    const char* name,
    std::string& diagnostic) {
    if (!value.empty()) {
        return ControlCodecError::None;
    }

    diagnostic = std::string("field must not be empty: ") + name;
    return ControlCodecError::InvalidFieldType;
}

ControlCodecError validate_audio_format(
    const AudioFormat& format,
    const char* name,
    std::string& diagnostic) {
    const std::string prefix = std::string(name) + '.';
    const std::string sample_format_name = prefix + "sample_format";
    if (const auto error = validate_non_empty_string(
            format.sample_format,
            sample_format_name.c_str(),
            diagnostic);
        error != ControlCodecError::None) {
        return error;
    }
    if (format.sample_rate == 0) {
        diagnostic = prefix + "sample_rate must be greater than zero";
        return ControlCodecError::InvalidFieldType;
    }
    if (format.channels == 0) {
        diagnostic = prefix + "channels must be greater than zero";
        return ControlCodecError::InvalidFieldType;
    }

    return ControlCodecError::None;
}

ControlCodecError validate_synthesis_sampling(
    const SynthesisSamplingOptions& options,
    std::string& diagnostic) {
    if (options.temperature.has_value() &&
        (!std::isfinite(options.temperature.value()) ||
         options.temperature.value() <= 0.0 ||
         options.temperature.value() > 2.0)) {
        diagnostic = "sampling.temperature must be finite and in the interval (0, 2]";
        return ControlCodecError::InvalidFieldType;
    }
    if (options.top_k.has_value() && options.top_k.value() == 0) {
        diagnostic = "sampling.top_k must be greater than zero";
        return ControlCodecError::InvalidFieldType;
    }
    if (options.top_p.has_value() &&
        (!std::isfinite(options.top_p.value()) ||
         options.top_p.value() <= 0.0 ||
         options.top_p.value() > 1.0)) {
        diagnostic = "sampling.top_p must be finite and in the interval (0, 1]";
        return ControlCodecError::InvalidFieldType;
    }
    if (options.repetition_penalty.has_value() &&
        (!std::isfinite(options.repetition_penalty.value()) ||
         options.repetition_penalty.value() < 1.0 ||
         options.repetition_penalty.value() > 2.0)) {
        diagnostic = "sampling.repetition_penalty must be finite and in the interval [1, 2]";
        return ControlCodecError::InvalidFieldType;
    }
    return ControlCodecError::None;
}

template <typename Message>
ControlCodecError validate_control_payload(
    const Message& value,
    std::string& diagnostic) {
    if constexpr (std::is_same_v<Message, HelloMessage>) {
        if (const auto error = validate_non_empty_string(
                value.client_name,
                "client_name",
                diagnostic);
            error != ControlCodecError::None) {
            return error;
        }
        return validate_non_empty_string(
            value.client_version,
            "client_version",
            diagnostic);
    }
    else if constexpr (std::is_same_v<Message, SynthesizeMessage>) {
        if (const auto error = validate_non_empty_string(value.text, "text", diagnostic);
            error != ControlCodecError::None) {
            return error;
        }
        if (const auto error = validate_synthesis_sampling(value.sampling, diagnostic);
            error != ControlCodecError::None) {
            return error;
        }
        return validate_audio_format(value.output, "output", diagnostic);
    }
    else if constexpr (std::is_same_v<Message, ShutdownMessage>) {
        if (value.mode == "cancel") {
            return ControlCodecError::None;
        }
        diagnostic = "unsupported shutdown mode";
        return ControlCodecError::InvalidFieldType;
    }
    else if constexpr (std::is_same_v<Message, ReadyMessage>) {
        if (const auto error = validate_non_empty_string(
                value.worker_version,
                "worker_version",
                diagnostic);
            error != ControlCodecError::None) {
            return error;
        }
        return validate_non_empty_string(value.session_id, "session_id", diagnostic);
    }
    else if constexpr (std::is_same_v<Message, QueuedMessage>) {
        if (!value.has_position || value.position > 0) {
            return ControlCodecError::None;
        }
        diagnostic = "position must be greater than zero";
        return ControlCodecError::InvalidFieldType;
    }
    else if constexpr (std::is_same_v<Message, StartedMessage>) {
        return validate_audio_format(value.audio_format, "audio_format", diagnostic);
    }
    else {
        return ControlCodecError::None;
    }
}

ControlCodecError validate_control_message(
    const ControlMessage& message,
    std::string& diagnostic) {
    return std::visit(
        [&diagnostic](const auto& value) {
            return validate_control_payload(value, diagnostic);
        },
        message);
}

ControlCodecError validate_error_message(
    const ErrorMessage& message,
    std::string& diagnostic) {
    if (const auto error = validate_non_empty_string(
            message.category,
            "category",
            diagnostic);
        error != ControlCodecError::None) {
        return error;
    }
    if (const auto error = validate_non_empty_string(message.code, "code", diagnostic);
        error != ControlCodecError::None) {
        return error;
    }
    return validate_non_empty_string(message.message, "message", diagnostic);
}

} // namespace qwen_tts_bridge::control_detail
