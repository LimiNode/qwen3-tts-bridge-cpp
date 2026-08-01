#pragma once

/// \file ClientTypes.hpp
/// \brief Public request, callback, and error DTOs for QwenTtsClient.

#include <cstddef>
#include <cstdint>
#include <functional>
#include <optional>
#include <string>
#include <vector>

namespace qwen_tts_bridge {

/// \struct TtsSamplingOptions
/// \brief Optional per-request decoding controls.
///
/// Unset fields preserve the worker runtime profile's defaults. These controls
/// are model-dependent and may be rejected by a worker that cannot honour them.
struct TtsSamplingOptions {
    /// \brief Optional sampling temperature; must be finite and greater than zero.
    std::optional<double> temperature; ///< Optional sampling temperature.

    /// \brief Optional top-k candidate limit; must be positive.
    std::optional<std::uint32_t> top_k; ///< Optional top-k candidate limit.

    /// \brief Optional nucleus-sampling probability in the interval (0, 1].
    std::optional<double> top_p; ///< Optional nucleus-sampling probability.

    /// \brief Optional repetition penalty in the interval [1, 2].
    std::optional<double> repetition_penalty; ///< Optional repetition penalty.

    /// \brief Optional sampling-mode override; false requests greedy decoding.
    std::optional<bool> do_sample; ///< Optional sampling-mode override.
};

/// \struct TtsRequest
/// \brief User-facing synthesis request.
struct TtsRequest {
    /// \brief Optional request identifier. Zero asks the client to assign one.
    RequestId id = 0; ///< Optional request ID; zero asks the client to assign one.

    /// \brief Spoken UTF-8 text.
    std::string text; ///< Spoken UTF-8 text.

    /// \brief Natural-language or engine language name.
    std::string language = "auto"; ///< Natural-language or engine language name.

    /// \brief Optional worker speaker identifier or voice name.
    ///
    /// Empty means no explicit speaker was selected by the application. Some
    /// engines may choose a default voice, while Qwen CustomVoice models may
    /// require a concrete speaker name.
    std::string speaker; ///< Optional worker speaker identifier or voice name.

    /// \brief Natural-language style, emotion, or prosody instruction.
    std::string instruction; ///< Natural-language style, emotion, or prosody instruction.

    /// \brief Optional deterministic seed for reproducible engine diagnostics.
    ///
    /// The worker may reject this control when its selected engine does not
    /// support deterministic request-level seeding.
    bool has_seed = false; ///< Whether seed contains a deterministic request seed.
    std::uint64_t seed = 0; ///< Optional deterministic seed for engine diagnostics.

    /// \brief Optional decoding controls for this request.
    TtsSamplingOptions sampling; ///< Optional per-request decoding controls.

    /// \brief Requested PCM output format.
    AudioFormat output; ///< Requested PCM output format.
};

/// \struct PcmChunk
/// \brief User-facing PCM audio chunk routed to a request callback.
struct PcmChunk {
    /// \brief Request that produced this audio.
    RequestId request_id = 0; ///< Request that produced this audio.

    /// \brief PCM format for the chunk.
    AudioFormat format; ///< PCM format for this chunk.

    /// \brief Raw PCM bytes.
    std::vector<std::byte> bytes; ///< Raw PCM bytes.
};

/// \struct TtsError
/// \brief User-facing worker, protocol, transport, or session error.
struct TtsError {
    /// \brief Related request, or zero for session-level failures.
    RequestId request_id = 0; ///< Related request, or zero for a session failure.

    /// \brief Error category.
    std::string category; ///< Broad error category.

    /// \brief Stable error code within the category when available.
    std::string code; ///< Stable error code when available.

    /// \brief Human-readable diagnostic message.
    std::string message; ///< Human-readable diagnostic message.
};

/// \struct TtsCallbacks
/// \brief Callback set for one synthesis request.
struct TtsCallbacks {
    /// \brief Called for each PCM chunk.
    std::function<void(const PcmChunk&)> on_audio; ///< Called for each PCM chunk.

    /// \brief Called exactly once when synthesis completes successfully.
    std::function<void()> on_completed; ///< Called exactly once after completion.

    /// \brief Called exactly once when synthesis is cancelled.
    std::function<void()> on_cancelled; ///< Called exactly once after cancellation.

    /// \brief Called exactly once when synthesis fails.
    std::function<void(const TtsError&)> on_error; ///< Called exactly once after failure.
};

} // namespace qwen_tts_bridge
