#pragma once

/// \file client_types.hpp
/// \brief Public request, callback, and error DTOs for QwenTtsClient.

#include <cstddef>
#include <cstdint>
#include <functional>
#include <optional>
#include <string>
#include <vector>

#include "../data/protocol_types.hpp"
#include "../protocol/control/control_messages.hpp"

namespace qwen_tts_bridge {

/// \struct TextPreparationWarning
/// \brief Warning preserved from an optional text frontend.
struct TextPreparationWarning {
    std::string code; ///< Stable frontend warning code.
    std::string message; ///< Human-readable warning text.
    std::size_t offset = 0; ///< UTF-8 byte offset in the source text.
    std::size_t length = 0; ///< UTF-8 byte length of the source span.
};

/// \struct TextStressDecision
/// \brief Semantic stress decision preserved from an optional text frontend.
struct TextStressDecision {
    std::string word; ///< Token or phrase associated with the decision.
    std::optional<std::size_t> stressed_vowel; ///< Zero-based vowel ordinal.
    bool from_dictionary = false; ///< Whether the decision came from a dictionary.
    std::string reason; ///< Stable or human-readable decision source.
};

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

    /// \brief Registered Base voice profile selected for this request.
    std::string voice_id; ///< Optional registered Base voice profile identifier.

    /// \brief Local reference-audio path for a Base voice-clone request.
    std::string reference_audio_path; ///< Local voice-clone reference-audio path.

    /// \brief Transcript of reference_audio_path for ICL voice cloning.
    std::string reference_text; ///< Reference-audio transcript for voice cloning.

    /// \brief Use only a speaker embedding and omit ICL reference speech codes.
    bool x_vector_only = false; ///< Whether the clone request uses x-vector-only mode.

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

/// \struct PreparedText
/// \brief Deterministic result of request-text preparation.
///
/// The effective text is the exact UTF-8 payload that will be sent to the
/// worker.  The byte measurements are intentionally backend-neutral and are
/// suitable for routing policies; model-token counts remain backend-specific.
struct PreparedText {
    std::string original_text; ///< Source text before preprocessing.
    std::string effective_text; ///< Exact text that synthesis will send.
    std::size_t utf8_bytes = 0; ///< Total UTF-8 bytes in effective_text.
    std::size_t non_space_utf8_bytes = 0; ///< UTF-8 bytes belonging to non-space code points.
    bool was_modified = false; ///< Whether effective_text differs from original_text.

    /// \brief Text stages produced by a model-agnostic frontend, when present.
    std::string frontend_normalized_text;
    std::string frontend_pronunciation_text;
    std::vector<TextPreparationWarning> frontend_warnings;
    std::vector<TextStressDecision> frontend_stress_decisions;
    bool frontend_has_uncertainty = false;
};

/// \struct PreparedTtsRequest
/// \brief Request paired with text prepared exactly once.
///
/// Passing this object to the prepared overload of `synthesize_async()` skips
/// the configured text preprocessor and sends `text.effective_text` verbatim.
struct PreparedTtsRequest {
    TtsRequest request; ///< Original request metadata and options.
    PreparedText text; ///< Prepared spoken text and routing measurements.
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

    /// \brief Zero-based position of the first interleaved sample frame.
    ///
    /// This is the canonical media-clock position for the utterance. It is
    /// derived from PCM accounting and is independent of callback arrival
    /// time or worker scheduling.
    std::uint64_t first_sample = 0; ///< First sample-frame position in the utterance.

    /// \brief Number of interleaved sample frames in `bytes`.
    std::uint32_t sample_count = 0; ///< Number of sample frames in this chunk.
};

/// \struct SpeechTimingChunk
/// \brief Sample-addressed sideband event for downstream speech analysis.
///
/// The timing stream deliberately contains no viseme or phoneme decision. It
/// is a lightweight, canonical media-clock feed that can be consumed by an
/// optional speech-animation layer without delaying PCM delivery.
struct SpeechTimingChunk {
    RequestId request_id = 0; ///< Utterance/request that produced this timing.
    std::uint64_t first_sample = 0; ///< First sample-frame position in the utterance.
    std::uint32_t sample_count = 0; ///< Number of sample frames in the chunk.
    std::uint32_t sample_rate = 0; ///< Samples per second for the timeline.
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

/// \struct TtsCompletion
/// \brief Optional terminal metadata reported with a completed synthesis request.
struct TtsCompletion {
    std::string execution_outcome; ///< Worker-reported terminal outcome when available.
    bool has_generation_trace = false; ///< Whether EOS and decoder trace fields are available.
    std::string termination_reason; ///< Model terminal reason such as ``eos``.
    bool hit_eos = false; ///< Whether the model emitted natural EOS.
    bool hit_max_seq_len = false; ///< Whether the model reached its sequence limit.
    bool hit_max_new_tokens = false; ///< Whether the model reached its token limit.
    std::uint64_t codec_frame_count = 0; ///< Generated codec-frame count.
    std::uint64_t generated_steps = 0; ///< Generated decoder step count.
    std::uint64_t emitted_steps = 0; ///< Emitted decoder step count.
    std::uint64_t terminal_step_index = 0; ///< Terminal decoder-step index.
};

/// \struct TtsCallbacks
/// \brief Callback set for one synthesis request.
struct TtsCallbacks {
    /// \brief Called once before audio when prepared frontend context exists.
    ///
    /// The callback receives the exact original, normalized, pronunciation,
    /// and stress metadata produced by the preparation stage. The bridge does
    /// not run normalization or G2P a second time downstream.
    std::function<void(const PreparedText&)> on_text_prepared;

    /// \brief Called for each PCM chunk.
    std::function<void(const PcmChunk&)> on_audio; ///< Called for each PCM chunk.

    /// \brief Called for each emitted audio chunk with sample-clock metadata.
    ///
    /// This callback is informational and must not block PCM delivery. It is
    /// intentionally generic; viseme and animation policy belong downstream.
    std::function<void(const SpeechTimingChunk&)> on_timing;

    /// \brief Called exactly once when synthesis completes successfully.
    std::function<void()> on_completed; ///< Called exactly once after completion.

    /// \brief Called exactly once with optional worker terminal metadata.
    std::function<void(const TtsCompletion&)> on_completion_metadata; ///< Completed metadata callback.

    /// \brief Called exactly once when synthesis is cancelled.
    std::function<void()> on_cancelled; ///< Called exactly once after cancellation.

    /// \brief Called exactly once when synthesis fails.
    std::function<void(const TtsError&)> on_error; ///< Called exactly once after failure.
};

} // namespace qwen_tts_bridge
