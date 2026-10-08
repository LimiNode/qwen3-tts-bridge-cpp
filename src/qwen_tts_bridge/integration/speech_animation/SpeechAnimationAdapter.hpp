#pragma once

/// \file SpeechAnimationAdapter.hpp
/// \brief Optional adapter from Qwen bridge callbacks to speech-animation.

#include "../../client/client_types.hpp"

#include <functional>
#include <memory>
#include <vector>

#include <speech_animation/integration.hpp>

namespace qwen_tts_bridge::speech_animation {

/// \brief Connects bridge PCM/lifecycle callbacks to a speech-animation pipeline.
///
/// The adapter is intentionally optional. It preserves the bridge's audio
/// callback for playback and only enqueues a converted float PCM copy into the
/// bounded speech-animation pipeline. Analyzer work runs when
/// process_available() is called by the consumer, never in the audio callback.
class SpeechAnimationAdapter final {
public:
    using Pipeline = ::speech_animation::integration::SpeechAnimationPipeline;
    using Receipt = ::speech_animation::integration::SpeechAnimationReceipt;
    using QueuePushResult = ::speech_animation::integration::QueuePushResult;
    using ReceiptHandler = std::function<void(const Receipt&)>;

    /// \brief Creates an adapter for an already configured pipeline.
    /// \param pipeline Shared pipeline owned by the integration/application layer.
    /// \param on_receipt Optional consumer callback invoked by process_available().
    explicit SpeechAnimationAdapter(
        std::shared_ptr<Pipeline> pipeline,
        ReceiptHandler on_receipt = {});

    /// \brief Establishes request metadata before synthesis begins.
    ///
    /// Call this immediately after assigning an explicit request ID and before
    /// submitting the request when an utterance may complete without PCM.
    QueuePushResult begin(
        RequestId request_id,
        std::uint64_t first_sample,
        std::uint32_t sample_rate);

    /// \brief Wraps bridge callbacks while preserving playback callbacks.
    ///
    /// The returned callbacks forward on_audio/on_timing/text/terminal events
    /// to `downstream`. PCM is also copied into the speech-animation queue.
    TtsCallbacks make_callbacks(TtsCallbacks downstream = {}) const;

    /// \brief Runs analyzer work on the consumer side and returns receipts.
    ///
    /// Call this from the integration/animation consumer thread, not from the
    /// bridge audio callback. At most one consumer may call this concurrently.
    std::vector<Receipt> process_available() const;

    /// \brief Returns whether the underlying pipeline reached a terminal state.
    bool terminal() const noexcept;

private:
    struct State;
    std::shared_ptr<State> state_;
};

} // namespace qwen_tts_bridge::speech_animation
