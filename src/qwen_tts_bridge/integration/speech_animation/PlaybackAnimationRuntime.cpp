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
    std::shared_ptr<SpeechAnimationAdapter::Pipeline> pipeline;
    std::shared_ptr<SpeechAnimationAdapter> adapter;
    ::speech_animation::integration::PlaybackLockedCueSelector selector;
    std::uint64_t playback_epoch = 0;
    RequestId request_id = 0;
};

PlaybackAnimationRuntime::PlaybackAnimationRuntime(
    SnapshotProvider snapshot_provider,
    SelectionHandler on_selection)
    : state_(std::make_shared<State>(
          std::move(snapshot_provider),
          std::move(on_selection))) {}

PlaybackAnimationRuntime::~PlaybackAnimationRuntime() = default;

void PlaybackAnimationRuntime::begin(
    std::uint64_t playback_epoch,
    RequestId request_id,
    std::uint32_t sample_rate) {
    auto pipeline = std::make_shared<SpeechAnimationAdapter::Pipeline>();
    if (pipeline->begin(request_id, 0, sample_rate) !=
        SpeechAnimationAdapter::QueuePushResult::Accepted) {
        throw std::runtime_error("failed to begin playback animation pipeline");
    }
    auto state = state_;
    auto adapter = std::make_shared<SpeechAnimationAdapter>(
        pipeline,
        [state](const SpeechAnimationAdapter::Receipt& receipt) {
            std::lock_guard<std::mutex> lock(state->mutex);
            static_cast<void>(state->selector.append(receipt));
        });
    std::lock_guard<std::mutex> lock(state_->mutex);
    state_->playback_epoch = playback_epoch;
    state_->request_id = request_id;
    state_->selector.reset(playback_epoch, request_id);
    state_->pipeline = std::move(pipeline);
    state_->adapter = std::move(adapter);
}

TtsCallbacks PlaybackAnimationRuntime::make_callbacks(TtsCallbacks downstream) const {
    std::shared_ptr<SpeechAnimationAdapter> adapter;
    {
        std::lock_guard<std::mutex> lock(state_->mutex);
        adapter = state_->adapter;
    }
    return adapter ? adapter->make_callbacks(std::move(downstream)) : std::move(downstream);
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

void PlaybackAnimationRuntime::invalidate(std::uint64_t playback_epoch) {
    std::lock_guard<std::mutex> lock(state_->mutex);
    state_->playback_epoch = playback_epoch;
    state_->request_id = 0;
    state_->pipeline.reset();
    state_->adapter.reset();
    state_->selector.reset(playback_epoch, 0);
}

} // namespace qwen_tts_bridge::speech_animation
