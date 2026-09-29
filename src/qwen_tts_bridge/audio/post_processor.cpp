#include <qwen_tts_bridge/audio/post_processor.hpp>

#include <iterator>
#include <stdexcept>
#include <utility>

namespace qwen_tts_bridge::audio {
namespace {

void emit_chunks(TtsCallbacks& callbacks, std::vector<PcmChunk> chunks) {
    if (!callbacks.on_audio) {
        return;
    }
    for (const PcmChunk& chunk : chunks) {
        callbacks.on_audio(chunk);
    }
}

} // namespace

void AudioPostProcessorChain::add(
    std::unique_ptr<IAudioPostProcessor> processor) {
    if (!processor) {
        throw std::invalid_argument("audio post-processor is null");
    }
    std::lock_guard<std::mutex> lock(mutex_);
    if (started_) {
        throw std::logic_error(
            "audio post-processors cannot be added after streaming starts");
    }
    processors_.push_back(std::move(processor));
}

std::vector<PcmChunk> AudioPostProcessorChain::process(PcmChunk chunk) {
    std::lock_guard<std::mutex> lock(mutex_);
    started_ = true;
    if (finished_) {
        return {};
    }
    std::vector<PcmChunk> chunks;
    chunks.push_back(std::move(chunk));
    return process_range(processors_, 0, std::move(chunks));
}

std::vector<PcmChunk> AudioPostProcessorChain::finish(
    AudioTerminalReason reason) {
    std::lock_guard<std::mutex> lock(mutex_);
    started_ = true;
    if (finished_) {
        return {};
    }
    finished_ = true;

    std::vector<PcmChunk> output;
    for (std::size_t index = 0; index < processors_.size(); ++index) {
        std::vector<PcmChunk> chunks = processors_[index]->finish(reason);
        chunks = process_range(processors_, index + 1, std::move(chunks));
        output.insert(
            output.end(),
            std::make_move_iterator(chunks.begin()),
            std::make_move_iterator(chunks.end()));
    }
    return output;
}

void AudioPostProcessorChain::reset() {
    std::lock_guard<std::mutex> lock(mutex_);
    for (const std::unique_ptr<IAudioPostProcessor>& processor : processors_) {
        processor->reset();
    }
    started_ = false;
    finished_ = false;
}

bool AudioPostProcessorChain::empty() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return processors_.empty();
}

std::vector<PcmChunk> AudioPostProcessorChain::process_range(
    std::vector<std::unique_ptr<IAudioPostProcessor>>& processors,
    std::size_t first,
    std::vector<PcmChunk> chunks) {
    for (std::size_t index = first; index < processors.size(); ++index) {
        std::vector<PcmChunk> next;
        for (PcmChunk& chunk : chunks) {
            std::vector<PcmChunk> emitted =
                processors[index]->process(std::move(chunk));
            next.insert(
                next.end(),
                std::make_move_iterator(emitted.begin()),
                std::make_move_iterator(emitted.end()));
        }
        chunks = std::move(next);
    }
    return chunks;
}

TtsCallbacks with_audio_post_processing(
    std::shared_ptr<AudioPostProcessorChain> processors,
    TtsCallbacks downstream) {
    if (!processors) {
        throw std::invalid_argument("audio post-processor chain is null");
    }

    auto callbacks = std::make_shared<TtsCallbacks>(std::move(downstream));
    TtsCallbacks wrapped;
    wrapped.on_audio = [processors, callbacks](const PcmChunk& chunk) {
        emit_chunks(*callbacks, processors->process(chunk));
    };
    wrapped.on_completed = [processors, callbacks]() {
        emit_chunks(
            *callbacks,
            processors->finish(AudioTerminalReason::Completed));
        if (callbacks->on_completed) {
            callbacks->on_completed();
        }
    };
    wrapped.on_completion_metadata = [callbacks](const TtsCompletion& completion) {
        if (callbacks->on_completion_metadata) {
            callbacks->on_completion_metadata(completion);
        }
    };
    wrapped.on_cancelled = [processors, callbacks]() {
        emit_chunks(
            *callbacks,
            processors->finish(AudioTerminalReason::Cancelled));
        if (callbacks->on_cancelled) {
            callbacks->on_cancelled();
        }
    };
    wrapped.on_error = [processors, callbacks](const TtsError& error) {
        emit_chunks(*callbacks, processors->finish(AudioTerminalReason::Error));
        if (callbacks->on_error) {
            callbacks->on_error(error);
        }
    };
    return wrapped;
}

} // namespace qwen_tts_bridge::audio
