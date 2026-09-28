#include <qwen_tts_bridge/audio/save_wav_callbacks.hpp>
#include <qwen_tts_bridge/audio/WavWriter.hpp>

#include <algorithm>
#include <cmath>
#include <cstring>
#include <limits>
#include <memory>
#include <stdexcept>
#include <utility>
#include <vector>

namespace qwen_tts_bridge::audio {
namespace {

bool is_terminal(SaveWavState& state) {
    std::lock_guard<std::mutex> lock(state.mutex);
    return state.terminal;
}

bool matches_format(const PcmChunk& chunk, const AudioFormat& expected) {
    return chunk.format.sample_format == expected.sample_format &&
           chunk.format.sample_rate == expected.sample_rate &&
           chunk.format.channels == expected.channels;
}

class TerminalTail {
public:
    TerminalTail(const AudioFormat& format, AudioTailOptions options)
        : format_(format), options_(options) {
        if (!options_.enabled) {
            return;
        }
        if (format_.sample_format != "s16le") {
            throw std::runtime_error(
                "audio tail currently supports only s16le PCM");
        }
        if (format_.sample_rate == 0 || format_.channels == 0) {
            throw std::runtime_error("audio tail requires a valid PCM format");
        }

        const std::uint64_t fade_samples =
            (static_cast<std::uint64_t>(format_.sample_rate) * options_.fade_ms + 500u) /
            1000u;
        const std::uint64_t frame_bytes =
            static_cast<std::uint64_t>(format_.channels) * sizeof(std::int16_t);
        if (frame_bytes != 0 &&
            fade_samples > std::numeric_limits<std::uint64_t>::max() / frame_bytes) {
            throw std::runtime_error("audio tail fade size is too large");
        }
        const std::uint64_t hold_bytes = fade_samples * frame_bytes;
        if (hold_bytes > std::numeric_limits<std::size_t>::max()) {
            throw std::runtime_error("audio tail buffer size is too large");
        }
        hold_bytes_ = static_cast<std::size_t>(hold_bytes);
        frame_bytes_ = static_cast<std::size_t>(frame_bytes);
    }

    [[nodiscard]] bool enabled() const noexcept {
        return options_.enabled;
    }

    std::size_t append_and_write(
        WavWriter& writer,
        const std::byte* data,
        std::size_t size) {
        if (!enabled()) {
            writer.write_pcm(data, size);
            return size;
        }
        if (size % frame_bytes_ != 0) {
            throw std::runtime_error(
                "audio tail received an incomplete PCM sample frame");
        }

        if (size != 0) {
            received_audio_ = true;
            pending_.insert(pending_.end(), data, data + size);
        }
        if (pending_.size() <= hold_bytes_) {
            return 0;
        }

        const std::size_t flush_size = pending_.size() - hold_bytes_;
        writer.write_pcm(pending_.data(), flush_size);
        pending_.erase(pending_.begin(), pending_.begin() + flush_size);
        return flush_size;
    }

    std::size_t finish(
        WavWriter& writer,
        std::uint32_t silence_ms) {
        if (!enabled()) {
            return 0;
        }
        if (!received_audio_) {
            return 0;
        }

        apply_fade();
        std::size_t written = 0;
        if (!pending_.empty()) {
            writer.write_pcm(pending_.data(), pending_.size());
            written += pending_.size();
            pending_.clear();
        }

        const std::uint64_t silence_samples =
            (static_cast<std::uint64_t>(format_.sample_rate) * silence_ms + 500u) /
            1000u;
        if (frame_bytes_ != 0 &&
            silence_samples > std::numeric_limits<std::uint64_t>::max() / frame_bytes_) {
            throw std::runtime_error("audio tail silence size is too large");
        }
        const std::uint64_t silence_bytes = silence_samples * frame_bytes_;
        if (silence_bytes > std::numeric_limits<std::size_t>::max()) {
            throw std::runtime_error("audio tail silence size is too large");
        }
        const std::size_t bytes = static_cast<std::size_t>(silence_bytes);
        if (bytes != 0) {
            silence_.assign(bytes, std::byte{0});
            writer.write_pcm(silence_.data(), silence_.size());
            written += silence_.size();
        }
        return written;
    }

private:
    void apply_fade() {
        if (pending_.empty() || options_.fade_ms == 0) {
            return;
        }

        const std::size_t frames = pending_.size() / frame_bytes_;
        if (frames == 0) {
            return;
        }
        for (std::size_t frame = 0; frame < frames; ++frame) {
            const double gain = frames == 1
                ? 0.0
                : static_cast<double>(frames - 1 - frame) /
                      static_cast<double>(frames - 1);
            for (std::size_t channel = 0; channel < format_.channels; ++channel) {
                const std::size_t offset =
                    frame * frame_bytes_ + channel * sizeof(std::int16_t);
                std::int16_t sample = 0;
                std::memcpy(&sample, pending_.data() + offset, sizeof(sample));
                const auto shaped = static_cast<long>(std::lround(
                    static_cast<double>(sample) * gain));
                const auto clamped = std::clamp<long>(
                    shaped,
                    std::numeric_limits<std::int16_t>::min(),
                    std::numeric_limits<std::int16_t>::max());
                sample = static_cast<std::int16_t>(clamped);
                std::memcpy(pending_.data() + offset, &sample, sizeof(sample));
            }
        }
    }

    AudioFormat format_;
    AudioTailOptions options_;
    std::size_t frame_bytes_ = 0;
    std::size_t hold_bytes_ = 0;
    bool received_audio_ = false;
    std::vector<std::byte> pending_;
    std::vector<std::byte> silence_;
};

void close_writer_ignoring_errors(
    SaveWavState& state,
    WavWriter& writer) noexcept {
    try {
        std::lock_guard<std::mutex> writer_lock(state.writer_mutex);
        writer.close();
    }
    catch (...) {
    }
}

} // namespace

void mark_save_wav_finished(
    SaveWavState& state,
    bool success,
    std::string message) {
    {
        std::lock_guard<std::mutex> lock(state.mutex);
        if (state.terminal) {
            return;
        }
        state.terminal = true;
        state.success = success;
        state.message = std::move(message);
    }
    state.condition.notify_all();
}

bool wait_for_save_wav_terminal(
    SaveWavState& state,
    std::chrono::milliseconds timeout) {
    std::unique_lock<std::mutex> lock(state.mutex);
    if (timeout.count() == 0) {
        state.condition.wait(lock, [&state]() {
            return state.terminal;
        });
        return true;
    }

    return state.condition.wait_for(lock, timeout, [&state]() {
        return state.terminal;
    });
}

TtsCallbacks make_save_wav_callbacks(
    SaveWavState& state,
    WavWriter& writer,
    const AudioFormat& expected_format,
    AudioTailOptions tail_options) {
    TtsCallbacks callbacks;
    auto tail = std::make_shared<TerminalTail>(expected_format, tail_options);

    callbacks.on_audio = [&state, &writer, expected_format, tail](const PcmChunk& chunk) {
        if (is_terminal(state)) {
            return;
        }

        try {
            if (!matches_format(chunk, expected_format)) {
                throw std::runtime_error("worker produced an unexpected PCM format");
            }

            {
                std::lock_guard<std::mutex> writer_lock(state.writer_mutex);
                if (is_terminal(state)) {
                    return;
                }
                const std::size_t written = tail->append_and_write(
                    writer,
                    chunk.bytes.data(),
                    chunk.bytes.size());
                if (written != 0) {
                    std::lock_guard<std::mutex> state_lock(state.mutex);
                    if (!state.terminal) {
                        state.audio_bytes += written;
                    }
                }
            }

            {
                std::lock_guard<std::mutex> state_lock(state.mutex);
                if (!state.terminal) {
                    ++state.audio_chunks;
                }
            }
        }
        catch (const std::exception& exc) {
            mark_save_wav_finished(state, false, exc.what());
        }
        catch (...) {
            mark_save_wav_finished(state, false, "unknown audio callback failure");
        }
    };

    callbacks.on_completed = [&state, &writer, tail, tail_options]() {
        if (is_terminal(state)) {
            return;
        }

        try {
            {
                std::lock_guard<std::mutex> writer_lock(state.writer_mutex);
                const std::size_t written = tail->finish(
                    writer,
                    tail_options.completion_silence_ms);
                if (written != 0) {
                    std::lock_guard<std::mutex> state_lock(state.mutex);
                    state.audio_bytes += written;
                }
                writer.close();
            }
            mark_save_wav_finished(state, true, "completed");
        }
        catch (const std::exception& exc) {
            mark_save_wav_finished(state, false, exc.what());
        }
        catch (...) {
            mark_save_wav_finished(state, false, "unknown completion callback failure");
        }
    };

    callbacks.on_cancelled = [&state, &writer, tail, tail_options]() {
        if (is_terminal(state)) {
            return;
        }
        try {
            {
                std::lock_guard<std::mutex> writer_lock(state.writer_mutex);
                const std::size_t written = tail->finish(
                    writer,
                    tail_options.cancellation_silence_ms);
                if (written != 0) {
                    std::lock_guard<std::mutex> state_lock(state.mutex);
                    state.audio_bytes += written;
                }
                writer.close();
            }
        }
        catch (...) {
            close_writer_ignoring_errors(state, writer);
        }
        mark_save_wav_finished(state, false, "request was cancelled");
    };

    callbacks.on_error = [&state, &writer](const TtsError& error) {
        close_writer_ignoring_errors(state, writer);
        mark_save_wav_finished(
            state,
            false,
            error.category + "/" + error.code + ": " + error.message);
    };

    return callbacks;
}

} // namespace qwen_tts_bridge::audio
