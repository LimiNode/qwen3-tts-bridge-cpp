#include "PlaybackAnimationRuntime.hpp"

#include <mutex>
#include <stdexcept>
#include <utility>

namespace qwen_tts_bridge::speech_animation {

struct PlaybackAnimationRuntime::State {
    explicit State(SnapshotProvider provider, SelectionHandler handler)
        : snapshot_provider(std::move(provider)), on_selection(std::move(handler)) {
        if (!snapshot_provider) {
            throw std::invalid_argument("playback animation snapshot provider is empty");
        }
    }

    mutable std::mutex mutex;
    SnapshotProvider snapshot_provider;
    SelectionHandler on_selection;
    DiagnosticHandler on_diagnostic;
    PipelineConfig pipeline_config;
    std::shared_ptr<SpeechAnimationAdapter::Pipeline> pipeline;
    std::shared_ptr<SpeechAnimationAdapter> adapter;
    ::speech_animation::integration::PlaybackLockedCueSelector selector;
    std::uint64_t playback_epoch = 0;
    RequestId request_id = 0;
    std::uint64_t generation = 0;
    bool cue_history_degraded = false;
};

PlaybackAnimationRuntime::PlaybackAnimationRuntime(
    SnapshotProvider snapshot_provider,
    SelectionHandler on_selection,
    DiagnosticHandler on_diagnostic,
    PipelineConfig pipeline_config)
    : state_(std::make_shared<State>(
          std::move(snapshot_provider),
          std::move(on_selection))) {
    state_->on_diagnostic = std::move(on_diagnostic);
    state_->pipeline_config = std::move(pipeline_config);
}

PlaybackAnimationRuntime::~PlaybackAnimationRuntime() = default;

std::uint64_t PlaybackAnimationRuntime::begin(
    std::uint64_t playback_epoch,
    RequestId request_id,
    std::uint32_t sample_rate) {
    auto pipeline = std::make_shared<SpeechAnimationAdapter::Pipeline>(
        state_->pipeline_config);
    if (pipeline->begin(request_id, 0, sample_rate) !=
        SpeechAnimationAdapter::QueuePushResult::Accepted) {
        throw std::runtime_error("failed to begin playback animation pipeline");
    }
    auto state = state_;
    std::lock_guard<std::mutex> lock(state_->mutex);
    const std::uint64_t generation = ++state_->generation;
    auto adapter = std::make_shared<SpeechAnimationAdapter>(
        pipeline,
        [state, generation, playback_epoch, request_id](
            const SpeechAnimationAdapter::Receipt& receipt) {
            DiagnosticHandler handler;
            SpeechAnimationAdapter::AdapterDiagnostic diagnostic;
            {
                std::lock_guard<std::mutex> lock(state->mutex);
                if (generation != state->generation ||
                    state->playback_epoch != playback_epoch ||
                    state->request_id != request_id ||
                    state->cue_history_degraded) {
                    return;
                }
                if (state->selector.append(receipt)) {
                    return;
                }
                state->cue_history_degraded = true;
                // Keep presentation neutral and prevent later receipts from
                // being interpreted against a partial bounded history.
                state->selector.reset(playback_epoch, 0);
                handler = state->on_diagnostic;
                diagnostic.request_id = request_id;
                diagnostic.code = "speech_animation_cue_history_overflow";
                diagnostic.message =
                    "playback cue history rejected a receipt; presentation degraded to neutral";
            }
            if (handler) {
                handler(diagnostic);
            }
        },
        [state, generation, playback_epoch](
            const SpeechAnimationAdapter::AdapterDiagnostic& diagnostic) {
            DiagnosticHandler handler;
            {
                std::lock_guard<std::mutex> lock(state->mutex);
                if (generation != state->generation ||
                    state->playback_epoch != playback_epoch) {
                    return;
                }
                handler = state->on_diagnostic;
            }
            if (handler) {
                handler(diagnostic);
            }
        });
    state_->playback_epoch = playback_epoch;
    state_->request_id = request_id;
    state_->cue_history_degraded = false;
    state_->selector.reset(playback_epoch, request_id);
    state_->pipeline = std::move(pipeline);
    state_->adapter = std::move(adapter);
    return generation;
}

TtsCallbacks PlaybackAnimationRuntime::make_callbacks(
    TtsCallbacks downstream,
    bool observe_audio) const {
    std::shared_ptr<SpeechAnimationAdapter> adapter;
    {
        std::lock_guard<std::mutex> lock(state_->mutex);
        adapter = state_->adapter;
    }
    return adapter
        ? adapter->make_callbacks(std::move(downstream), observe_audio)
        : std::move(downstream);
}

PlaybackAnimationRuntime::Selection PlaybackAnimationRuntime::tick() {
    Snapshot snapshot = state_->snapshot_provider();
    std::shared_ptr<SpeechAnimationAdapter> adapter;
    {
        std::lock_guard<std::mutex> lock(state_->mutex);
        adapter = state_->adapter;
    }
    if (adapter) {
        adapter->process_available();
    }
    Selection selection;
    SelectionHandler handler;
    {
        std::lock_guard<std::mutex> lock(state_->mutex);
        selection = state_->selector.select(snapshot);
        handler = state_->on_selection;
    }
    if (handler) {
        handler(selection);
    }
    return selection;
}

bool PlaybackAnimationRuntime::push_audio(
    std::uint64_t playback_epoch,
    std::uint64_t generation,
    const PcmChunk& chunk) const {
    std::shared_ptr<SpeechAnimationAdapter> adapter;
    {
        std::lock_guard<std::mutex> lock(state_->mutex);
        if (state_->generation != generation ||
            state_->playback_epoch != playback_epoch ||
            state_->request_id != chunk.request_id) {
            return false;
        }
        adapter = state_->adapter;
    }
    if (adapter) {
        adapter->push_audio(chunk);
        return true;
    }
    return false;
}

void PlaybackAnimationRuntime::invalidate(std::uint64_t playback_epoch) {
    std::lock_guard<std::mutex> lock(state_->mutex);
    ++state_->generation;
    state_->playback_epoch = playback_epoch;
    state_->request_id = 0;
    state_->pipeline.reset();
    state_->adapter.reset();
    state_->selector.reset(playback_epoch, 0);
}

} // namespace qwen_tts_bridge::speech_animation
