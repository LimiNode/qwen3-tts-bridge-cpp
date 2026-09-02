#include <qwen_tts_bridge/protocol/control.hpp>

#include <cstddef>
#include <cstdlib>
#include <iostream>
#include <string>
#include <variant>
#include <vector>

#define CHECK(expr)                                                            \
    do {                                                                       \
        if (!(expr)) {                                                         \
            std::cerr << "CHECK failed: " #expr << " at " << __FILE__ << ':'  \
                      << __LINE__ << '\n';                                     \
            std::exit(EXIT_FAILURE);                                           \
        }                                                                      \
    } while (false)

namespace {

using namespace qwen_tts_bridge;

std::vector<std::byte> bytes_from_string(const std::string& value) {
    std::vector<std::byte> bytes;
    bytes.reserve(value.size());
    for (const char ch : value) {
        bytes.push_back(static_cast<std::byte>(static_cast<unsigned char>(ch)));
    }
    return bytes;
}

std::string string_from_bytes(const std::vector<std::byte>& bytes) {
    std::string value;
    value.reserve(bytes.size());
    for (const auto byte : bytes) {
        value.push_back(static_cast<char>(std::to_integer<unsigned char>(byte)));
    }
    return value;
}

ControlDecodeResult decode_client(const std::string& payload) {
    return decode_control_message(
        bytes_from_string(payload),
        ControlMessageDirection::ClientToWorker);
}

ControlDecodeResult decode_worker(const std::string& payload) {
    return decode_control_message(
        bytes_from_string(payload),
        ControlMessageDirection::WorkerToClient);
}

void test_decode_hello() {
    const auto result = decode_client(
        "{\"message_type\":\"hello\","
        "\"client_name\":\"qwen-tts-bridge-cpp\","
        "\"client_version\":\"0.2.0\"}");

    CHECK(result);
    CHECK(control_message_type(result.message) == ControlMessageType::Hello);
    const auto& hello = std::get<HelloMessage>(result.message);
    CHECK(hello.client_name == "qwen-tts-bridge-cpp");
    CHECK(hello.client_version == "0.2.0");
}

void test_decode_synthesize_with_instruction_and_output() {
    const auto result = decode_client(
        "{\"message_type\":\"synthesize\","
        "\"text\":\"I thought you were not coming.\","
        "\"language\":\"English\","
        "\"speaker\":\"Alice\","
        "\"instruction\":\"Speak with relief.\","
        "\"output\":{"
        "\"sample_format\":\"s16le\","
        "\"sample_rate\":24000,"
        "\"channels\":1"
        "}}");

    CHECK(result);
    CHECK(control_message_type(result.message) == ControlMessageType::Synthesize);
    const auto& message = std::get<SynthesizeMessage>(result.message);
    CHECK(message.text == "I thought you were not coming.");
    CHECK(message.language == "English");
    CHECK(message.speaker == "Alice");
    CHECK(message.instruction == "Speak with relief.");
    CHECK(message.output.sample_format == "s16le");
    CHECK(message.output.sample_rate == 24000);
    CHECK(message.output.channels == 1);
}

void test_decode_synthesize_without_speaker() {
    const auto result = decode_client(
        "{\"message_type\":\"synthesize\","
        "\"text\":\"No explicit speaker.\"}");

    CHECK(result);
    const auto& message = std::get<SynthesizeMessage>(result.message);
    CHECK(message.text == "No explicit speaker.");
    CHECK(message.speaker.empty());
}

void test_synthesize_seed_round_trip() {
    SynthesizeMessage message;
    message.text = "Seeded synthesis.";
    message.has_seed = true;
    message.seed = 4242;

    const auto encoded = encode_control_message(ControlMessage{message});
    CHECK(encoded);
    CHECK(string_from_bytes(encoded.payload).find("\"seed\":4242") != std::string::npos);

    const auto decoded = decode_control_message(
        encoded.payload,
        ControlMessageDirection::ClientToWorker);
    CHECK(decoded);
    const auto& seeded = std::get<SynthesizeMessage>(decoded.message);
    CHECK(seeded.has_seed);
    CHECK(seeded.seed == 4242);
}

void test_synthesize_sampling_round_trip() {
    SynthesizeMessage message;
    message.text = "Controlled synthesis.";
    message.sampling.temperature = 0.4;
    message.sampling.top_k = 40;
    message.sampling.top_p = 0.92;
    message.sampling.repetition_penalty = 1.1;
    message.sampling.do_sample = true;

    const auto encoded = encode_control_message(ControlMessage{message});
    CHECK(encoded);
    const std::string payload = string_from_bytes(encoded.payload);
    CHECK(payload.find("\"sampling\"") != std::string::npos);
    CHECK(payload.find("\"temperature\":0.4") != std::string::npos);

    const auto decoded = decode_control_message(
        encoded.payload,
        ControlMessageDirection::ClientToWorker);
    CHECK(decoded);
    const auto& sampling = std::get<SynthesizeMessage>(decoded.message).sampling;
    CHECK(sampling.temperature.has_value());
    CHECK(sampling.temperature.value() == 0.4);
    CHECK(sampling.top_k == 40);
    CHECK(sampling.top_p == 0.92);
    CHECK(sampling.repetition_penalty == 1.1);
    CHECK(sampling.do_sample == true);
}

void test_synthesize_voice_clone_round_trip() {
    SynthesizeMessage message;
    message.text = "Clone this voice.";
    message.reference_audio_path = "C:/tmp/reference.wav";
    message.reference_text = "Reference transcript.";
    message.x_vector_only = true;

    const auto encoded = encode_control_message(ControlMessage{message});
    CHECK(encoded);
    const auto decoded = decode_control_message(
        encoded.payload,
        ControlMessageDirection::ClientToWorker);
    CHECK(decoded);
    const auto& clone = std::get<SynthesizeMessage>(decoded.message);
    CHECK(clone.reference_audio_path == "C:/tmp/reference.wav");
    CHECK(clone.reference_text == "Reference transcript.");
    CHECK(clone.x_vector_only);
}

void test_synthesize_voice_profile_round_trip() {
    SynthesizeMessage message;
    message.text = "Use a registered voice.";
    message.voice_id = "kraftwerk_robot_ru";

    const auto encoded = encode_control_message(ControlMessage{message});
    CHECK(encoded);
    const auto decoded = decode_control_message(
        encoded.payload,
        ControlMessageDirection::ClientToWorker);
    CHECK(decoded);
    const auto& profile = std::get<SynthesizeMessage>(decoded.message);
    CHECK(profile.voice_id == "kraftwerk_robot_ru");
}

void test_synthesize_rejects_mixed_voice_profile_and_reference() {
    const auto result = decode_client(
        "{\"message_type\":\"synthesize\","
        "\"text\":\"Invalid mixed voice.\","
        "\"voice_id\":\"robot\","
        "\"reference_audio_path\":\"reference.wav\"}");

    CHECK(!result);
    CHECK(result.error == ControlCodecError::InvalidFieldType);
}

void test_synthesize_rejects_orphaned_voice_clone_fields() {
    const auto result = decode_client(
        "{\"message_type\":\"synthesize\","
        "\"text\":\"Missing reference.\","
        "\"reference_text\":\"Transcript.\"}");

    CHECK(!result);
    CHECK(result.error == ControlCodecError::InvalidFieldType);
}

void test_synthesize_rejects_invalid_sampling() {
    const auto result = decode_client(
        "{\"message_type\":\"synthesize\","
        "\"text\":\"Invalid sampling.\","
        "\"sampling\":{\"temperature\":0}}");

    CHECK(!result);
    CHECK(result.error == ControlCodecError::InvalidFieldType);
}

void test_synthesize_rejects_unknown_sampling_field() {
    const auto result = decode_client(
        "{\"message_type\":\"synthesize\","
        "\"text\":\"Unknown sampling.\","
        "\"sampling\":{\"temprature\":0.4}}");

    CHECK(!result);
    CHECK(result.error == ControlCodecError::UnknownField);
    CHECK(std::string(control_codec_error_code(result.error)) == "unknown_field");
}

void test_encode_synthesize_omits_unspecified_speaker() {
    SynthesizeMessage message;
    message.text = "No explicit speaker.";

    const auto encoded = encode_control_message(ControlMessage{message});
    CHECK(encoded);

    const std::string payload = string_from_bytes(encoded.payload);
    CHECK(payload.find("\"message_type\":\"synthesize\"") != std::string::npos);
    CHECK(payload.find("\"speaker\"") == std::string::npos);
}

void test_encode_synthesize_with_explicit_speaker() {
    SynthesizeMessage message;
    message.text = "Explicit speaker.";
    message.speaker = "Alice";

    const auto encoded = encode_control_message(ControlMessage{message});
    CHECK(encoded);

    const std::string payload = string_from_bytes(encoded.payload);
    CHECK(payload.find("\"speaker\":\"Alice\"") != std::string::npos);
}

void test_decode_ready() {
    const auto result = decode_worker(
        "{\"message_type\":\"ready\","
        "\"worker_version\":\"0.2.0\","
        "\"session_id\":\"session-1\","
        "\"warmed_up\":true,"
        "\"capabilities\":{"
        "\"streaming\":true,"
        "\"cancellation\":true,"
        "\"instructions\":true,"
        "\"voice_clone\":false,"
        "\"voice_clone_streaming\":false,"
        "\"voice_profiles\":true,"
        "\"sampling_overrides\":true,"
        "\"deterministic_seed\":true"
        "},"
        "\"voice_ids\":[\"kraftwerk_robot_ru\"]}");

    CHECK(result);
    CHECK(control_message_type(result.message) == ControlMessageType::Ready);
    const auto& ready = std::get<ReadyMessage>(result.message);
    CHECK(ready.worker_version == "0.2.0");
    CHECK(ready.session_id == "session-1");
    CHECK(ready.has_warmed_up);
    CHECK(ready.warmed_up);
    CHECK(ready.capabilities.streaming);
    CHECK(ready.capabilities.cancellation);
    CHECK(ready.capabilities.instructions);
    CHECK(!ready.capabilities.voice_clone);
    CHECK(!ready.capabilities.voice_clone_streaming);
    CHECK(ready.capabilities.voice_profiles);
    CHECK(ready.capabilities.sampling_overrides);
    CHECK(ready.capabilities.deterministic_seed);
    CHECK(ready.voice_ids.size() == 1);
    CHECK(ready.voice_ids.front() == "kraftwerk_robot_ru");
}

void test_decode_completed_generation_trace() {
    const auto result = decode_worker(
        "{\"message_type\":\"completed\","
        "\"execution_outcome\":\"completed\","
        "\"generation_trace\":{"
        "\"termination_reason\":\"eos\","
        "\"hit_eos\":true,"
        "\"hit_max_seq_len\":false,"
        "\"hit_max_new_tokens\":false,"
        "\"codec_frame_count\":8,"
        "\"generated_steps\":8,"
        "\"emitted_steps\":8,"
        "\"terminal_step_index\":8}}"
    );

    CHECK(result);
    const auto& completed = std::get<CompletedMessage>(result.message);
    CHECK(completed.has_execution_outcome);
    CHECK(completed.execution_outcome == "completed");
    CHECK(completed.has_generation_trace);
    CHECK(completed.generation_trace.termination_reason == "eos");
    CHECK(completed.generation_trace.hit_eos);
    CHECK(!completed.generation_trace.hit_max_seq_len);
    CHECK(!completed.generation_trace.hit_max_new_tokens);
    CHECK(completed.generation_trace.codec_frame_count == 8);
    CHECK(completed.generation_trace.generated_steps == 8);
    CHECK(completed.generation_trace.emitted_steps == 8);
    CHECK(completed.generation_trace.terminal_step_index == 8);
}

void test_decode_ready_without_optional_sampling_capabilities() {
    const auto result = decode_worker(
        "{\"message_type\":\"ready\","
        "\"worker_version\":\"0.2.0\","
        "\"session_id\":\"session-legacy\","
        "\"capabilities\":{"
        "\"streaming\":true,"
        "\"cancellation\":true,"
        "\"instructions\":true,"
        "\"voice_clone\":false"
        "}}");

    CHECK(result);
    const auto& ready = std::get<ReadyMessage>(result.message);
    CHECK(!ready.capabilities.sampling_overrides);
    CHECK(!ready.capabilities.deterministic_seed);
}

void test_encode_ping_round_trip() {
    PingMessage ping;
    ping.has_sequence = true;
    ping.sequence = 17;

    const auto encoded = encode_control_message(ControlMessage{ping});
    CHECK(encoded);

    const std::string payload = string_from_bytes(encoded.payload);
    CHECK(payload.find("\"message_type\":\"ping\"") != std::string::npos);
    CHECK(payload.find("\"sequence\":17") != std::string::npos);
    CHECK(payload.find("request_id") == std::string::npos);
    CHECK(payload.find("protocol_version") == std::string::npos);

    const auto decoded = decode_control_message(
        encoded.payload,
        ControlMessageDirection::ClientToWorker);
    CHECK(decoded);
    const auto& decoded_ping = std::get<PingMessage>(decoded.message);
    CHECK(decoded_ping.has_sequence);
    CHECK(decoded_ping.sequence == 17);
}

void test_decode_started_audio_format() {
    const auto result = decode_worker(
        "{\"message_type\":\"started\","
        "\"audio_format\":{"
        "\"sample_format\":\"s16le\","
        "\"sample_rate\":24000,"
        "\"channels\":1"
        "}}");

    CHECK(result);
    CHECK(control_message_type(result.message) == ControlMessageType::Started);
    const auto& started = std::get<StartedMessage>(result.message);
    CHECK(started.audio_format.sample_format == "s16le");
    CHECK(started.audio_format.sample_rate == 24000);
    CHECK(started.audio_format.channels == 1);
}

void test_decode_error_json() {
    const auto result = decode_error_message(bytes_from_string(
        "{\"message_type\":\"error\","
        "\"category\":\"request_error\","
        "\"code\":\"unsupported_audio_format\","
        "\"message\":\"Unsupported format.\"}"));

    CHECK(result);
    CHECK(result.message.category == "request_error");
    CHECK(result.message.code == "unsupported_audio_format");
    CHECK(result.message.message == "Unsupported format.");
}

void test_encode_error_json() {
    ErrorMessage message;
    message.category = "model_error";
    message.code = "synthesis_failed";
    message.message = "Failure details.";

    const auto encoded = encode_error_message(message);
    CHECK(encoded);

    const auto decoded = decode_error_message(encoded.payload);
    CHECK(decoded);
    CHECK(decoded.message.category == message.category);
    CHECK(decoded.message.code == message.code);
    CHECK(decoded.message.message == message.message);
}

void test_reject_invalid_json() {
    const auto result = decode_client("{");
    CHECK(!result);
    CHECK(result.error == ControlCodecError::InvalidJson);
    CHECK(std::string(control_codec_error_code(result.error)) == "invalid_json");
}

void test_reject_non_object_payload() {
    const auto result = decode_client("[]");
    CHECK(!result);
    CHECK(result.error == ControlCodecError::PayloadNotObject);
    CHECK(std::string(control_codec_error_code(result.error)) == "payload_not_object");
}

void test_reject_missing_message_type() {
    const auto result = decode_client("{}");
    CHECK(!result);
    CHECK(result.error == ControlCodecError::MissingMessageType);
}

void test_reject_invalid_message_type() {
    const auto result = decode_client("{\"message_type\":42}");
    CHECK(!result);
    CHECK(result.error == ControlCodecError::InvalidMessageType);
}

void test_reject_unknown_message_type() {
    const auto result = decode_client("{\"message_type\":\"mystery\"}");
    CHECK(!result);
    CHECK(result.error == ControlCodecError::UnknownMessageType);
}

void test_reject_invalid_direction() {
    const auto result = decode_worker(
        "{\"message_type\":\"ping\",\"sequence\":17}");
    CHECK(!result);
    CHECK(result.error == ControlCodecError::InvalidMessageDirection);
    CHECK(std::string(control_codec_error_code(result.error)) == "invalid_message_direction");
}

void test_reject_header_fields_in_json() {
    const auto result = decode_client(
        "{\"message_type\":\"ping\","
        "\"request_id\":7}");
    CHECK(!result);
    CHECK(result.error == ControlCodecError::ForbiddenField);
}

void test_reject_missing_required_field() {
    const auto result = decode_client(
        "{\"message_type\":\"hello\","
        "\"client_name\":\"client\"}");
    CHECK(!result);
    CHECK(result.error == ControlCodecError::MissingRequiredField);
}

void test_reject_invalid_field_type() {
    const auto result = decode_client(
        "{\"message_type\":\"synthesize\","
        "\"text\":\"hello\","
        "\"language\":7}");
    CHECK(!result);
    CHECK(result.error == ControlCodecError::InvalidFieldType);
}

void test_reject_invalid_shutdown_mode() {
    const auto result = decode_client(
        "{\"message_type\":\"shutdown\","
        "\"mode\":\"wait\"}");
    CHECK(!result);
    CHECK(result.error == ControlCodecError::InvalidFieldType);
}

void test_reject_started_audio_format_without_sample_format() {
    const auto result = decode_worker(
        "{\"message_type\":\"started\","
        "\"audio_format\":{"
        "\"sample_rate\":24000,"
        "\"channels\":1"
        "}}");
    CHECK(!result);
    CHECK(result.error == ControlCodecError::MissingRequiredField);
}

void test_reject_audio_format_empty_or_zero_values() {
    const auto empty_format = decode_worker(
        "{\"message_type\":\"started\","
        "\"audio_format\":{"
        "\"sample_format\":\"\","
        "\"sample_rate\":24000,"
        "\"channels\":1"
        "}}");
    CHECK(!empty_format);
    CHECK(empty_format.error == ControlCodecError::InvalidFieldType);

    const auto zero_rate = decode_worker(
        "{\"message_type\":\"started\","
        "\"audio_format\":{"
        "\"sample_format\":\"s16le\","
        "\"sample_rate\":0,"
        "\"channels\":1"
        "}}");
    CHECK(!zero_rate);
    CHECK(zero_rate.error == ControlCodecError::InvalidFieldType);

    const auto zero_channels = decode_worker(
        "{\"message_type\":\"started\","
        "\"audio_format\":{"
        "\"sample_format\":\"s16le\","
        "\"sample_rate\":24000,"
        "\"channels\":0"
        "}}");
    CHECK(!zero_channels);
    CHECK(zero_channels.error == ControlCodecError::InvalidFieldType);
}

void test_reject_synthesize_output_without_sample_format() {
    const auto result = decode_client(
        "{\"message_type\":\"synthesize\","
        "\"text\":\"hello\","
        "\"output\":{"
        "\"sample_rate\":24000,"
        "\"channels\":1"
        "}}");
    CHECK(!result);
    CHECK(result.error == ControlCodecError::MissingRequiredField);
}

void test_reject_queued_position_zero() {
    const auto decoded = decode_worker(
        "{\"message_type\":\"queued\","
        "\"position\":0}");
    CHECK(!decoded);
    CHECK(decoded.error == ControlCodecError::InvalidFieldType);

    QueuedMessage queued;
    queued.has_position = true;
    queued.position = 0;
    const auto encoded = encode_control_message(ControlMessage{queued});
    CHECK(!encoded);
    CHECK(encoded.error == ControlCodecError::InvalidFieldType);
}

void test_reject_invalid_control_dto_encode() {
    ShutdownMessage shutdown;
    shutdown.mode = "wait";
    const auto invalid_shutdown = encode_control_message(ControlMessage{shutdown});
    CHECK(!invalid_shutdown);
    CHECK(invalid_shutdown.error == ControlCodecError::InvalidFieldType);

    StartedMessage started;
    started.audio_format.channels = 0;
    const auto invalid_format = encode_control_message(ControlMessage{started});
    CHECK(!invalid_format);
    CHECK(invalid_format.error == ControlCodecError::InvalidFieldType);
}

void test_reject_empty_required_strings() {
    HelloMessage hello;
    hello.client_name = "";
    hello.client_version = "0.2.0";
    const auto invalid_hello = encode_control_message(ControlMessage{hello});
    CHECK(!invalid_hello);
    CHECK(invalid_hello.error == ControlCodecError::InvalidFieldType);

    const auto invalid_text = decode_client(
        "{\"message_type\":\"synthesize\","
        "\"text\":\"\"}");
    CHECK(!invalid_text);
    CHECK(invalid_text.error == ControlCodecError::InvalidFieldType);

    ErrorMessage error;
    error.category = "request_error";
    error.code = "";
    error.message = "bad request";
    const auto invalid_error = encode_error_message(error);
    CHECK(!invalid_error);
    CHECK(invalid_error.error == ControlCodecError::InvalidFieldType);
}

void test_reject_error_json_header_fields() {
    const auto result = decode_error_message(bytes_from_string(
        "{\"message_type\":\"error\","
        "\"request_id\":1,"
        "\"category\":\"request_error\","
        "\"code\":\"unknown_request_id\","
        "\"message\":\"bad id\"}"));
    CHECK(!result);
    CHECK(result.error == ControlCodecError::ForbiddenField);
}

} // namespace

int main() {
    test_decode_hello();
    test_decode_synthesize_with_instruction_and_output();
    test_decode_synthesize_without_speaker();
    test_synthesize_seed_round_trip();
    test_synthesize_sampling_round_trip();
    test_synthesize_voice_clone_round_trip();
    test_synthesize_voice_profile_round_trip();
    test_synthesize_rejects_mixed_voice_profile_and_reference();
    test_synthesize_rejects_orphaned_voice_clone_fields();
    test_synthesize_rejects_invalid_sampling();
    test_synthesize_rejects_unknown_sampling_field();
    test_encode_synthesize_omits_unspecified_speaker();
    test_encode_synthesize_with_explicit_speaker();
    test_decode_ready();
    test_decode_completed_generation_trace();
    test_decode_ready_without_optional_sampling_capabilities();
    test_encode_ping_round_trip();
    test_decode_started_audio_format();
    test_decode_error_json();
    test_encode_error_json();
    test_reject_invalid_json();
    test_reject_non_object_payload();
    test_reject_missing_message_type();
    test_reject_invalid_message_type();
    test_reject_unknown_message_type();
    test_reject_invalid_direction();
    test_reject_header_fields_in_json();
    test_reject_missing_required_field();
    test_reject_invalid_field_type();
    test_reject_invalid_shutdown_mode();
    test_reject_started_audio_format_without_sample_format();
    test_reject_audio_format_empty_or_zero_values();
    test_reject_synthesize_output_without_sample_format();
    test_reject_queued_position_zero();
    test_reject_invalid_control_dto_encode();
    test_reject_empty_required_strings();
    test_reject_error_json_header_fields();
    return 0;
}
