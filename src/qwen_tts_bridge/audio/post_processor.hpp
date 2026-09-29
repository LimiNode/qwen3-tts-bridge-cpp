#pragma once

/// \file post_processor.hpp
/// \brief Streaming PCM post-processing interfaces and callback adapter.

#include <memory>
#include <mutex>
#include <vector>

#include "../client/client_types.hpp"

namespace qwen_tts_bridge::audio {

/// \enum AudioTerminalReason
/// \brief Describes why a PCM stream reached its terminal boundary.
enum class AudioTerminalReason {
    Completed,
    Cancelled,
    Error
};

/// \class IAudioPostProcessor
/// \brief Stateful transform from streaming PCM chunks to zero or more chunks.
///
/// One processor instance belongs to one synthesis stream. Implementations may
/// buffer audio between calls. They must release any buffered data from
/// finish(), choosing terminal-specific behaviour where appropriate.
class IAudioPostProcessor {
public:
    virtual ~IAudioPostProcessor() = default;

    /// \brief Processes one PCM chunk.
    /// \return Zero or more output chunks in playback order.
    virtual std::vector<PcmChunk> process(PcmChunk chunk) = 0;

    /// \brief Finalizes the stream and releases buffered output.
    /// \return Zero or more final chunks in playback order.
    virtual std::vector<PcmChunk> finish(AudioTerminalReason reason) = 0;

    /// \brief Discards all stream state so the instance can be reused.
    virtual void reset() noexcept = 0;
};

/// \class AudioPostProcessorChain
/// \brief Thread-safe ordered pipeline of streaming PCM post-processors.
///
/// Calls are serialized so an application may finish a stream from a control
/// thread while PCM arrives on the callback thread. A terminal call is
/// idempotent; late PCM is discarded until reset().
class AudioPostProcessorChain final {
public:
    AudioPostProcessorChain() = default;
    ~AudioPostProcessorChain() = default;

    AudioPostProcessorChain(const AudioPostProcessorChain&) = delete;
    AudioPostProcessorChain& operator=(const AudioPostProcessorChain&) = delete;

    /// \brief Appends a processor before the stream starts.
    void add(std::unique_ptr<IAudioPostProcessor> processor);

    /// \brief Processes one input chunk through every configured stage.
    std::vector<PcmChunk> process(PcmChunk chunk);

    /// \brief Finalizes every stage and returns all remaining output.
    std::vector<PcmChunk> finish(AudioTerminalReason reason);

    /// \brief Discards buffered state and makes the chain reusable.
    void reset();

    /// \brief Returns whether the chain contains no stages.
    [[nodiscard]] bool empty() const;

private:
    static std::vector<PcmChunk> process_range(
        std::vector<std::unique_ptr<IAudioPostProcessor>>& processors,
        std::size_t first,
        std::vector<PcmChunk> chunks);

    mutable std::mutex mutex_;
    std::vector<std::unique_ptr<IAudioPostProcessor>> processors_;
    bool started_ = false;
    bool finished_ = false;
};

/// \brief Wraps callbacks with a client-side PCM post-processing pipeline.
///
/// Audio emitted while finalizing is delivered before the corresponding
/// terminal callback. Completion metadata passes through unchanged.
TtsCallbacks with_audio_post_processing(
    std::shared_ptr<AudioPostProcessorChain> processors,
    TtsCallbacks downstream);

} // namespace qwen_tts_bridge::audio
