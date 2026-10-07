#include <qwen_tts_bridge/audio/TerminalFadePostProcessor.hpp>

#include <algorithm>
#include <cmath>
#include <cstring>
#include <iterator>
#include <limits>
#include <stdexcept>
#include <utility>

namespace qwen_tts_bridge::audio {
namespace {

constexpr std::uint32_t kMaxDurationMs = 600000;

bool formats_match(const AudioFormat& left, const AudioFormat& right) {
    return left.sample_format == right.sample_format &&
           left.sample_rate == right.sample_rate &&
           left.channels == right.channels;
}

std::size_t checked_duration_bytes(
    const AudioFormat& format,
    std::size_t frame_bytes,
    std::uint32_t duration_ms) {
    const std::uint64_t samples =
        (static_cast<std::uint64_t>(format.sample_rate) * duration_ms + 500u) /
        1000u;
    if (frame_bytes != 0 &&
        samples > std::numeric_limits<std::uint64_t>::max() / frame_bytes) {
        throw std::runtime_error("audio terminal duration is too large");
    }
    const std::uint64_t bytes = samples * frame_bytes;
    if (bytes > std::numeric_limits<std::size_t>::max()) {
        throw std::runtime_error("audio terminal buffer is too large");
    }
    return static_cast<std::size_t>(bytes);
}

} // namespace

TerminalFadePostProcessor::TerminalFadePostProcessor(
    TerminalFadeOptions options)
    : options_(options) {
    if (options_.fade_ms > kMaxDurationMs ||
        options_.completion_silence_ms > kMaxDurationMs ||
        options_.cancellation_silence_ms > kMaxDurationMs) {
        throw std::invalid_argument(
            "audio terminal durations must not exceed 600000 ms");
    }
}

std::vector<PcmChunk> TerminalFadePostProcessor::process(PcmChunk chunk) {
    if (finished_) {
        return {};
    }
    if (!format_.has_value()) {
        configure(chunk);
    }
    else {
        validate_chunk(chunk);
    }
    if (chunk.bytes.empty()) {
        return {};
    }

    received_audio_ = true;
    if (pending_.empty()) {
        pending_first_sample_ = chunk.first_sample;
    }
    const std::uint64_t chunk_samples = chunk.sample_count != 0
        ? chunk.sample_count
        : static_cast<std::uint64_t>(chunk.bytes.size() / frame_bytes_);
    pending_sample_count_ += chunk_samples;
    pending_.insert(
        pending_.end(),
        std::make_move_iterator(chunk.bytes.begin()),
        std::make_move_iterator(chunk.bytes.end()));
    if (pending_.size() <= hold_bytes_) {
        return {};
    }

    const std::size_t emitted_bytes = pending_.size() - hold_bytes_;
    PcmChunk output;
    output.request_id = request_id_;
    output.format = format_.value();
    output.first_sample = pending_first_sample_;
    output.sample_count = static_cast<std::uint32_t>(
        emitted_bytes / frame_bytes_);
    output.bytes.insert(
        output.bytes.end(),
        std::make_move_iterator(pending_.begin()),
        std::make_move_iterator(pending_.begin() + emitted_bytes));
    pending_.erase(pending_.begin(), pending_.begin() + emitted_bytes);
    pending_first_sample_ += output.sample_count;
    pending_sample_count_ -= std::min<std::uint64_t>(
        pending_sample_count_, output.sample_count);
    return {std::move(output)};
}

std::vector<PcmChunk> TerminalFadePostProcessor::finish(
    AudioTerminalReason reason) {
    if (finished_) {
        return {};
    }
    finished_ = true;
    if (!received_audio_ || !format_.has_value()) {
        pending_.clear();
        return {};
    }

    std::uint32_t silence_ms = 0;
    if (reason != AudioTerminalReason::Error) {
        apply_fade();
        silence_ms = reason == AudioTerminalReason::Completed
            ? options_.completion_silence_ms
            : options_.cancellation_silence_ms;
    }

    const std::size_t padding = silence_bytes(silence_ms);
    pending_.insert(pending_.end(), padding, std::byte{0});
    PcmChunk output;
    output.request_id = request_id_;
    output.format = format_.value();
    output.first_sample = pending_first_sample_;
    output.sample_count = static_cast<std::uint32_t>(
        pending_.size() / frame_bytes_);
    output.bytes = std::move(pending_);
    return output.bytes.empty()
        ? std::vector<PcmChunk>{}
        : std::vector<PcmChunk>{std::move(output)};
}

void TerminalFadePostProcessor::reset() noexcept {
    format_.reset();
    request_id_ = 0;
    frame_bytes_ = 0;
    hold_bytes_ = 0;
    pending_first_sample_ = 0;
    pending_sample_count_ = 0;
    received_audio_ = false;
    finished_ = false;
    pending_.clear();
}

void TerminalFadePostProcessor::configure(const PcmChunk& chunk) {
    if (chunk.format.sample_format != "s16le") {
        throw std::runtime_error(
            "terminal fade post-processor supports only s16le PCM");
    }
    if (chunk.format.sample_rate == 0 || chunk.format.channels == 0) {
        throw std::runtime_error(
            "terminal fade post-processor requires a valid PCM format");
    }
    const std::uint64_t frame_bytes =
        static_cast<std::uint64_t>(chunk.format.channels) * sizeof(std::int16_t);
    if (frame_bytes > std::numeric_limits<std::size_t>::max()) {
        throw std::runtime_error("PCM frame size is too large");
    }
    format_ = chunk.format;
    request_id_ = chunk.request_id;
    frame_bytes_ = static_cast<std::size_t>(frame_bytes);
    hold_bytes_ = checked_duration_bytes(
        format_.value(),
        frame_bytes_,
        options_.fade_ms);
    validate_chunk(chunk);
}

void TerminalFadePostProcessor::validate_chunk(const PcmChunk& chunk) const {
    if (!formats_match(format_.value(), chunk.format)) {
        throw std::runtime_error(
            "audio format changed inside a post-processed stream");
    }
    if (request_id_ != chunk.request_id) {
        throw std::runtime_error(
            "request ID changed inside a post-processed stream");
    }
    if (chunk.bytes.size() % frame_bytes_ != 0) {
        throw std::runtime_error(
            "PCM chunk does not contain complete sample frames");
    }
    const auto expected_samples = static_cast<std::uint64_t>(
        chunk.bytes.size() / frame_bytes_);
    if (chunk.sample_count != 0 &&
        chunk.sample_count != expected_samples) {
        throw std::runtime_error(
            "PCM chunk sample_count does not match its payload");
    }
    if (received_audio_ && chunk.sample_count != 0 &&
        chunk.first_sample != pending_first_sample_ + pending_sample_count_) {
        throw std::runtime_error(
            "PCM chunk sample timeline is not contiguous");
    }
}

void TerminalFadePostProcessor::apply_fade() {
    if (pending_.empty() || options_.fade_ms == 0) {
        return;
    }
    const std::size_t frames = pending_.size() / frame_bytes_;
    for (std::size_t frame = 0; frame < frames; ++frame) {
        const double gain = frames == 1
            ? 0.0
            : static_cast<double>(frames - 1 - frame) /
                  static_cast<double>(frames - 1);
        for (std::size_t channel = 0; channel < format_->channels; ++channel) {
            const std::size_t offset =
                frame * frame_bytes_ + channel * sizeof(std::int16_t);
            std::int16_t sample = 0;
            std::memcpy(&sample, pending_.data() + offset, sizeof(sample));
            const auto shaped = static_cast<long>(std::lround(
                static_cast<double>(sample) * gain));
            sample = static_cast<std::int16_t>(std::clamp<long>(
                shaped,
                std::numeric_limits<std::int16_t>::min(),
                std::numeric_limits<std::int16_t>::max()));
            std::memcpy(pending_.data() + offset, &sample, sizeof(sample));
        }
    }
}

std::size_t TerminalFadePostProcessor::silence_bytes(
    std::uint32_t duration_ms) const {
    return checked_duration_bytes(format_.value(), frame_bytes_, duration_ms);
}

} // namespace qwen_tts_bridge::audio
