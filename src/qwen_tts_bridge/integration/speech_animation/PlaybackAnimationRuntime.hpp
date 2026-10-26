#pragma once

#include "SpeechAnimationAdapter.hpp"

#include <speech_animation/playback.hpp>

#include <functional>
#include <cstdint>
#include <memory>

namespace qwen_tts_bridge::speech_animation {

/// \brief Presentation-side consumer for playback-locked animation.
///
/// The caller supplies a physical sink cursor on every presentation tick.
/// Analyzer work and cue selection stay outside the bridge audio callback.
class PlaybackAnimationRuntime final {
public:
    using Snapshot = ::speech_animation::integration::PlaybackCursorSnapshot;
    using Selection = ::speech_animation::integration::PlaybackAnimationSelection;
    using PipelineConfig = ::speech_animation::integration::PipelineConfig;
    using AdapterDiagnostic = SpeechAnimationAdapter::AdapterDiagnostic;
    using SnapshotProvider = std::function<Snapshot()>;
    using SelectionHandler = std::function<void(const Selection&)>;
    using DiagnosticHandler = std::function<void(const AdapterDiagnostic&)>;

    PlaybackAnimationRuntime(
        SnapshotProvider snapshot_provider,
        SelectionHandler on_selection = {},
        DiagnosticHandler on_diagnostic = {},
        PipelineConfig pipeline_config = {});
    ~PlaybackAnimationRuntime();

    PlaybackAnimationRuntime(const PlaybackAnimationRuntime&) = delete;
    PlaybackAnimationRuntime& operator=(const PlaybackAnimationRuntime&) = delete;

    /// Initializes the playback epoch before the presentation loop starts.
    ///
    /// This is required when the presentation loop may tick before the first
    /// request is submitted. The epoch must be non-zero and initialization
    /// must happen before the first call to begin().
    void initialize_epoch(std::uint64_t playback_epoch);

    /// Starts a new request/epoch and invalidates all previous cues.
    /// Returns the generation token assigned to this playback request.
    std::uint64_t begin(
        std::uint64_t playback_epoch,
        RequestId request_id,
        std::uint32_t sample_rate);

    /// Wraps bridge callbacks with the current optional animation pipeline.
    TtsCallbacks make_callbacks(
        TtsCallbacks downstream = {},
        bool observe_audio = true) const;

    /// Drains adapter receipts and selects the cue at the current sink cursor.
    /// Call this from one presentation/animation consumer thread.
    Selection tick();

    /// Pushes the exact PCM submitted to the playback sink when it belongs to
    /// the active playback epoch and request.
    ///
    /// Returns false when the chunk is stale and was discarded before reaching
    /// the animation pipeline.
    bool push_audio(
        std::uint64_t playback_epoch,
        std::uint64_t generation,
        const PcmChunk& chunk) const;

    /// Invalidates the current request after interruption/reset.
    void invalidate(std::uint64_t playback_epoch);

private:
    struct State;
    std::shared_ptr<State> state_;
};

} // namespace qwen_tts_bridge::speech_animation
