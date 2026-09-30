#include <qwen_tts_bridge/audio/playout_cursor.hpp>

#include <algorithm>
#include <cmath>
#include <cstring>
#include <limits>
#include <stdexcept>

namespace qwen_tts_bridge::audio {
namespace {

bool formats_match(const AudioFormat& left, const AudioFormat& right) {
    return left.sample_format == right.sample_format &&
           left.sample_rate == right.sample_rate &&
           left.channels == right.channels;
}

std::size_t frame_bytes(const AudioFormat& format) {
    if (format.sample_format != "s16le" ||
        format.sample_rate == 0 ||
        format.channels == 0) {
        throw std::invalid_argument("playout cursor fade requires valid s16le PCM");
    }
    const std::uint64_t bytes =
        static_cast<std::uint64_t>(format.channels) * sizeof(std::int16_t);
    if (bytes > std::numeric_limits<std::size_t>::max()) {
        throw std::invalid_argument("playout cursor frame size is too large");
    }
    return static_cast<std::size_t>(bytes);
}

} // namespace

std::optional<PcmChunk> make_playout_cursor_fade(
    const std::vector<PlayoutBuffer>& buffers,
    std::uint64_t cursor_frame,
    std::uint32_t fade_ms) {
    if (buffers.empty() || fade_ms == 0) {
        return std::nullopt;
    }

    const AudioFormat& format = buffers.front().chunk.format;
    const std::size_t bytes_per_frame = frame_bytes(format);
    const std::uint64_t fade_frames =
        (static_cast<std::uint64_t>(format.sample_rate) * fade_ms + 999u) /
        1000u;
    if (fade_frames == 0) {
        return std::nullopt;
    }

    for (const PlayoutBuffer& buffer : buffers) {
        if (!formats_match(format, buffer.chunk.format) ||
            buffer.chunk.bytes.size() % bytes_per_frame != 0) {
            throw std::invalid_argument(
                "playout cursor buffers must share a complete PCM format");
        }
    }

    std::size_t first_index = buffers.size();
    std::uint64_t first_offset = 0;
    for (std::size_t index = 0; index < buffers.size(); ++index) {
        const PlayoutBuffer& buffer = buffers[index];
        const std::uint64_t count =
            static_cast<std::uint64_t>(buffer.chunk.bytes.size() / bytes_per_frame);
        if (cursor_frame >= buffer.start_frame + count) {
            continue;
        }
        first_index = index;
        first_offset = cursor_frame > buffer.start_frame
            ? cursor_frame - buffer.start_frame
            : 0;
        break;
    }
    if (first_index == buffers.size()) {
        return std::nullopt;
    }

    std::vector<std::byte> bytes;
    std::uint64_t remaining = fade_frames;
    for (std::size_t index = first_index;
         index < buffers.size() && remaining != 0;
         ++index) {
        const PlayoutBuffer& buffer = buffers[index];
        const std::uint64_t count = static_cast<std::uint64_t>(
            buffer.chunk.bytes.size() / bytes_per_frame);
        const std::uint64_t offset = index == first_index ? first_offset : 0;
        if (offset >= count) {
            continue;
        }
        const std::uint64_t copy_frames = std::min(remaining, count - offset);
        const std::size_t begin = static_cast<std::size_t>(offset) * bytes_per_frame;
        const std::size_t copy_bytes =
            static_cast<std::size_t>(copy_frames) * bytes_per_frame;
        bytes.insert(
            bytes.end(),
            buffer.chunk.bytes.begin() + begin,
            buffer.chunk.bytes.begin() + begin + copy_bytes);
        remaining -= copy_frames;
    }
    if (bytes.empty()) {
        return std::nullopt;
    }

    const std::size_t frames = bytes.size() / bytes_per_frame;
    for (std::size_t frame = 0; frame < frames; ++frame) {
        const double gain = frames == 1
            ? 0.0
            : static_cast<double>(frames - 1 - frame) /
                  static_cast<double>(frames - 1);
        for (std::uint32_t channel = 0; channel < format.channels; ++channel) {
            const std::size_t offset =
                frame * bytes_per_frame + channel * sizeof(std::int16_t);
            std::int16_t sample = 0;
            std::memcpy(&sample, bytes.data() + offset, sizeof(sample));
            const long shaped = static_cast<long>(std::lround(
                static_cast<double>(sample) * gain));
            const long clamped = std::clamp<long>(
                shaped,
                std::numeric_limits<std::int16_t>::min(),
                std::numeric_limits<std::int16_t>::max());
            sample = static_cast<std::int16_t>(clamped);
            std::memcpy(bytes.data() + offset, &sample, sizeof(sample));
        }
    }

    PcmChunk output;
    output.request_id = buffers[first_index].chunk.request_id;
    output.format = format;
    output.bytes = std::move(bytes);
    return output;
}

} // namespace qwen_tts_bridge::audio
