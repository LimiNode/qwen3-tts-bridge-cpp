#include <qwen_tts_bridge/audio/post_processor.hpp>

#include <iterator>
#include <exception>
#include <string>
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

struct AdapterState {
    std::mutex mutex;
    bool terminal = false;
    RequestId request_id = 0;
};

std::string exception_message(std::exception_ptr exception) noexcept {
    try {
        if (exception) {
            std::rethrow_exception(exception);
        }
    }
    catch (const std::exception& error) {
        return error.what();
    }
    catch (...) {
        return "unknown exception";
    }
    return "unknown exception";
}

TtsError make_post_processing_error(
    const AdapterState& state,
    std::exception_ptr exception,
    RequestId fallback_request_id) {
    TtsError error;
    error.request_id = state.request_id != 0
        ? state.request_id
        : fallback_request_id;
    error.category = "client_error";
    error.code = "audio_post_processing_failed";
    error.message = "audio post-processing failed: " +
        exception_message(std::move(exception));
    return error;
}

void emit_post_processing_error(
    TtsCallbacks& callbacks,
    TtsError error) {
    if (callbacks.on_error) {
        callbacks.on_error(error);
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
    auto state = std::make_shared<AdapterState>();
    TtsCallbacks wrapped;
    wrapped.on_audio = [processors, callbacks, state](const PcmChunk& chunk) {
        std::unique_lock<std::mutex> lock(state->mutex);
        if (state->terminal) {
            return;
        }
        if (state->request_id == 0) {
            state->request_id = chunk.request_id;
        }
        std::vector<PcmChunk> output;
        try {
            output = processors->process(chunk);
        }
        catch (...) {
            const TtsError error = make_post_processing_error(
                *state,
                std::current_exception(),
                chunk.request_id);
            state->terminal = true;
            lock.unlock();
            emit_post_processing_error(*callbacks, error);
            return;
        }
        emit_chunks(*callbacks, std::move(output));
    };
    wrapped.on_completed = [processors, callbacks, state]() {
        std::unique_lock<std::mutex> lock(state->mutex);
        if (state->terminal) {
            return;
        }
        std::vector<PcmChunk> output;
        try {
            output = processors->finish(AudioTerminalReason::Completed);
        }
        catch (...) {
            const TtsError error = make_post_processing_error(
                *state,
                std::current_exception(),
                state->request_id);
            state->terminal = true;
            lock.unlock();
            emit_post_processing_error(*callbacks, error);
            return;
        }
        state->terminal = true;
        emit_chunks(*callbacks, std::move(output));
        if (callbacks->on_completed) {
            callbacks->on_completed();
        }
    };
    wrapped.on_completion_metadata = [callbacks, state](const TtsCompletion& completion) {
        std::lock_guard<std::mutex> lock(state->mutex);
        if (state->terminal) {
            return;
        }
        if (callbacks->on_completion_metadata) {
            callbacks->on_completion_metadata(completion);
        }
    };
    wrapped.on_cancelled = [processors, callbacks, state]() {
        std::unique_lock<std::mutex> lock(state->mutex);
        if (state->terminal) {
            return;
        }
        std::vector<PcmChunk> output;
        try {
            output = processors->finish(AudioTerminalReason::Cancelled);
        }
        catch (...) {
            const TtsError error = make_post_processing_error(
                *state,
                std::current_exception(),
                state->request_id);
            state->terminal = true;
            lock.unlock();
            emit_post_processing_error(*callbacks, error);
            return;
        }
        state->terminal = true;
        emit_chunks(*callbacks, std::move(output));
        if (callbacks->on_cancelled) {
            callbacks->on_cancelled();
        }
    };
    wrapped.on_error = [processors, callbacks, state](const TtsError& error) {
        std::unique_lock<std::mutex> lock(state->mutex);
        if (state->terminal) {
            return;
        }
        if (state->request_id == 0) {
            state->request_id = error.request_id;
        }
        std::vector<PcmChunk> output;
        try {
            output = processors->finish(AudioTerminalReason::Error);
        }
        catch (...) {
            const TtsError post_processing_error = make_post_processing_error(
                *state,
                std::current_exception(),
                error.request_id);
            state->terminal = true;
            lock.unlock();
            emit_post_processing_error(*callbacks, post_processing_error);
            return;
        }
        state->terminal = true;
        emit_chunks(*callbacks, std::move(output));
        if (callbacks->on_error) {
            callbacks->on_error(error);
        }
    };
    return wrapped;
}

} // namespace qwen_tts_bridge::audio
