#pragma once

/// \file ControlMessages.hpp
/// \brief DTOs for protocol v1 JSON control and error payloads.

#include <cstddef>
#include <cstdint>
#include <optional>
#include <string>
#include <variant>
#include <vector>

namespace qwen_tts_bridge {

/// \enum ControlMessageDirection
/// \brief Expected wire direction for a control_json payload.
enum class ControlMessageDirection {
    ClientToWorker, ///< Payload sent by the C++ client to the worker.
    WorkerToClient  ///< Payload sent by the worker to the C++ client.
};

/// \enum ControlMessageType
/// \brief Known protocol v1 control message names.
enum class ControlMessageType {
    Hello,       ///< Client session handshake.
    Synthesize,  ///< Client synthesis request.
    Cancel,      ///< Client request cancellation.
    Ping,        ///< Client heartbeat probe.
    Shutdown,    ///< Client graceful shutdown request.
    Ready,       ///< Worker readiness handshake.
    Queued,      ///< Worker advisory queue event.
    Started,     ///< Worker synthesis start event.
    Completed,   ///< Worker terminal success event.
    Cancelled,   ///< Worker terminal cancellation event.
    Pong,        ///< Worker heartbeat response.
    ShutdownAck  ///< Worker graceful shutdown acknowledgement.
};

/// \enum ControlCodecError
/// \brief JSON-level codec errors for control and error payloads.
enum class ControlCodecError {
    None,                    ///< Payload is valid.
    InvalidJson,             ///< Payload cannot be decoded as JSON.
    PayloadNotObject,        ///< Top-level JSON value is not an object.
    MissingMessageType,      ///< Required message_type field is absent.
    InvalidMessageType,      ///< message_type field has an invalid type.
    UnknownMessageType,      ///< message_type is not known to protocol v1.
    InvalidMessageDirection, ///< Message is invalid in this wire direction.
    MissingRequiredField,    ///< A required message field is absent.
    InvalidFieldType,        ///< A message field has an invalid JSON type.
    ForbiddenField,          ///< A message contains a forbidden field.
    UnknownField,            ///< A nested object contains an unknown field.
    EncodeFailed             ///< A valid message could not be encoded.
};

/// \brief Returns the protocol error code string for a codec error.
/// \param error Codec error category.
/// \return Stable protocol error code string.
const char* control_codec_error_code(ControlCodecError error);

/// \struct AudioFormat
/// \brief PCM format announced or requested by control messages.
struct AudioFormat {
    std::string sample_format = "s16le"; ///< PCM sample encoding.
    std::uint32_t sample_rate = 24000; ///< PCM samples per second.
    std::uint32_t channels = 1; ///< Number of interleaved PCM channels.
};

/// \struct WorkerCapabilities
/// \brief Worker feature flags announced by the ready message.
struct WorkerCapabilities {
    bool streaming = false; ///< Worker supports streaming PCM events.
    bool cancellation = false; ///< Worker supports request cancellation.
    bool instructions = false; ///< Worker accepts style instructions.
    bool voice_clone = false; ///< Worker advertises voice-cloning support.
    bool sampling_overrides = false; ///< Worker accepts request-level sampling controls.
    bool deterministic_seed = false; ///< Worker can strictly apply explicit RNG seeds.
    bool voice_clone_streaming = false; ///< Worker can stream clone PCM before completion.
    bool voice_profiles = false; ///< Worker has a configured registered-voice registry.
};

/// \struct HelloMessage
/// \brief Client-to-worker session handshake message.
struct HelloMessage {
    std::string client_name; ///< C++ client implementation name.
    std::string client_version; ///< C++ client implementation version.
};

/// \struct SynthesisSamplingOptions
/// \brief Optional decoding controls carried by a synthesize message.
struct SynthesisSamplingOptions {
    std::optional<double> temperature; ///< Optional sampling temperature.
    std::optional<std::uint32_t> top_k; ///< Optional top-k candidate limit.
    std::optional<double> top_p; ///< Optional nucleus-sampling probability.
    std::optional<double> repetition_penalty; ///< Optional repetition penalty.
    std::optional<bool> do_sample; ///< Optional sampling-mode override.
};

/// \struct SynthesizeMessage
/// \brief Client-to-worker synthesis request payload.
struct SynthesizeMessage {
    std::string text; ///< Spoken UTF-8 text.
    std::string language = "auto"; ///< Requested language or auto detection.
    std::string speaker; ///< Optional worker speaker or voice identifier.
    std::string instruction; ///< Natural-language style instruction.
    std::string voice_id; ///< Optional registered Base voice profile identifier.
    std::string reference_audio_path; ///< Local reference-audio path for Base voice cloning.
    std::string reference_text; ///< Reference-audio transcript for ICL voice cloning.
    bool x_vector_only = false; ///< Whether the Base clone uses speaker embedding only.
    bool has_seed = false; ///< Whether seed contains a deterministic seed.
    std::uint64_t seed = 0; ///< Optional deterministic engine seed.
    SynthesisSamplingOptions sampling; ///< Optional per-request decoding controls.
    AudioFormat output; ///< Requested output PCM format.
};

/// \struct CancelMessage
/// \brief Client-to-worker request cancellation payload.
struct CancelMessage {};

/// \struct PingMessage
/// \brief Client-to-worker heartbeat payload.
struct PingMessage {
    bool has_sequence = false; ///< Whether sequence is present.
    std::uint64_t sequence = 0; ///< Optional heartbeat sequence number.
};

/// \struct ShutdownMessage
/// \brief Client-to-worker graceful shutdown payload.
struct ShutdownMessage {
    std::string mode = "cancel"; ///< Requested graceful shutdown mode.
};

/// \struct ReadyMessage
/// \brief Worker-to-client readiness handshake payload.
struct ReadyMessage {
    std::string worker_version; ///< Worker implementation version.
    std::string session_id; ///< Worker-generated session identifier.
    bool has_warmed_up = false; ///< Whether warmed_up was reported.
    bool warmed_up = false; ///< Whether model warmup completed.
    WorkerCapabilities capabilities; ///< Advertised worker features.
    std::vector<std::string> voice_ids; ///< Registered Base voice profile identifiers.
};

/// \struct QueuedMessage
/// \brief Worker-to-client advisory request queue event.
struct QueuedMessage {
    bool has_position = false; ///< Whether position was reported.
    std::uint32_t position = 0; ///< Advisory queue position.
};

/// \struct StartedMessage
/// \brief Worker-to-client request start event.
struct StartedMessage {
    AudioFormat audio_format; ///< PCM format used for subsequent audio frames.
};

/// \struct CompletedMessage
/// \brief Worker-to-client terminal success event.
struct CompletedMessage {};

/// \struct CancelledMessage
/// \brief Worker-to-client terminal cancellation event.
struct CancelledMessage {};

/// \struct PongMessage
/// \brief Worker-to-client heartbeat response payload.
struct PongMessage {
    bool has_sequence = false; ///< Whether sequence was echoed.
    std::uint64_t sequence = 0; ///< Echoed heartbeat sequence number.
};

/// \struct ShutdownAckMessage
/// \brief Worker-to-client graceful shutdown acknowledgement.
struct ShutdownAckMessage {};

/// \brief Variant containing one known control_json message payload.
using ControlMessage = std::variant<
    HelloMessage,
    SynthesizeMessage,
    CancelMessage,
    PingMessage,
    ShutdownMessage,
    ReadyMessage,
    QueuedMessage,
    StartedMessage,
    CompletedMessage,
    CancelledMessage,
    PongMessage,
    ShutdownAckMessage>;

/// \brief Returns the message type represented by a control message variant.
/// \param message Control message payload.
/// \return Message type discriminator.
ControlMessageType control_message_type(const ControlMessage& message);

/// \struct ErrorMessage
/// \brief Worker-to-client error_json payload.
///
/// Category and code are kept as strings for forward-compatible protocol
/// extensions. The control codec validates that they are present and non-empty,
/// but it does not enforce a closed set of known wire values.
struct ErrorMessage {
    std::string category; ///< Broad forward-compatible error category.
    std::string code; ///< Forward-compatible stable error code.
    std::string message; ///< Human-readable error diagnostic.
};

/// \struct ControlDecodeResult
/// \brief Result returned when decoding a control_json payload.
struct [[nodiscard]] ControlDecodeResult {
    ControlMessage message; ///< Decoded payload when error is None.
    ControlCodecError error = ControlCodecError::None; ///< Decode outcome.
    std::string diagnostic; ///< Detail for a failed decode.

    /// \brief Returns true when decoding succeeded.
    explicit operator bool() const noexcept {
        return error == ControlCodecError::None;
    }
};

/// \struct ErrorDecodeResult
/// \brief Result returned when decoding an error_json payload.
struct [[nodiscard]] ErrorDecodeResult {
    ErrorMessage message; ///< Decoded payload when error is None.
    ControlCodecError error = ControlCodecError::None; ///< Decode outcome.
    std::string diagnostic; ///< Detail for a failed decode.

    /// \brief Returns true when decoding succeeded.
    explicit operator bool() const noexcept {
        return error == ControlCodecError::None;
    }
};

/// \struct JsonPayloadEncodeResult
/// \brief Result returned when encoding a JSON payload.
struct [[nodiscard]] JsonPayloadEncodeResult {
    std::vector<std::byte> payload; ///< Encoded UTF-8 JSON payload.
    ControlCodecError error = ControlCodecError::None; ///< Encode outcome.
    std::string diagnostic; ///< Detail for a failed encode.

    /// \brief Returns true when encoding succeeded.
    explicit operator bool() const noexcept {
        return error == ControlCodecError::None;
    }
};

} // namespace qwen_tts_bridge
