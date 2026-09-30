#include <qwen_tts_bridge/audio/playout_cursor.hpp>

#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <vector>

#define CHECK(expr)                                                            \
    do {                                                                       \
        if (!(expr)) {                                                         \
            std::cerr << "CHECK failed: " #expr " at " << __FILE__ << ':'  \
                      << __LINE__ << '\n';                                     \
            std::exit(EXIT_FAILURE);                                           \
        }                                                                      \
    } while (false)

namespace {

using qwen_tts_bridge::AudioFormat;
using qwen_tts_bridge::PcmChunk;
using qwen_tts_bridge::audio::PlayoutBuffer;
using qwen_tts_bridge::audio::make_playout_cursor_fade;

PcmChunk constant_chunk(std::size_t frames, std::int16_t value) {
    PcmChunk chunk;
    chunk.request_id = 42;
    chunk.format.sample_format = "s16le";
    chunk.format.sample_rate = 1000;
    chunk.format.channels = 1;
    chunk.bytes.resize(frames * sizeof(value));
    for (std::size_t index = 0; index < frames; ++index) {
        std::memcpy(
            chunk.bytes.data() + index * sizeof(value),
            &value,
            sizeof(value));
    }
    return chunk;
}

std::int16_t sample_at(const PcmChunk& chunk, std::size_t index) {
    std::int16_t value = 0;
    std::memcpy(
        &value,
        chunk.bytes.data() + index * sizeof(value),
        sizeof(value));
    return value;
}

void test_cursor_uses_audible_buffer_not_producer_tail() {
    std::vector<PlayoutBuffer> buffers;
    buffers.push_back({constant_chunk(100, 100), 0});
    buffers.push_back({constant_chunk(100, 200), 100});
    buffers.push_back({constant_chunk(100, 300), 200});

    const auto tail = make_playout_cursor_fade(buffers, 120, 15);
    CHECK(tail.has_value());
    CHECK(tail->request_id == 42);
    CHECK(tail->bytes.size() == 15 * sizeof(std::int16_t));
    CHECK(sample_at(tail.value(), 0) == 200);
    CHECK(sample_at(tail.value(), 14) == 0);
}

void test_cursor_can_cross_buffer_boundary() {
    std::vector<PlayoutBuffer> buffers;
    buffers.push_back({constant_chunk(100, 100), 0});
    buffers.push_back({constant_chunk(100, 200), 100});

    const auto tail = make_playout_cursor_fade(buffers, 95, 20);
    CHECK(tail.has_value());
    CHECK(tail->bytes.size() == 20 * sizeof(std::int16_t));
    CHECK(sample_at(tail.value(), 0) == 100);
    CHECK(sample_at(tail.value(), 4) > 0);
    CHECK(sample_at(tail.value(), 4) < 100);
    CHECK(sample_at(tail.value(), 5) > 100);
    CHECK(sample_at(tail.value(), 5) < 200);
    CHECK(sample_at(tail.value(), 19) == 0);
}

void test_cursor_rejects_incompatible_buffers() {
    std::vector<PlayoutBuffer> buffers;
    buffers.push_back({constant_chunk(10, 100), 0});
    PcmChunk invalid = constant_chunk(10, 200);
    invalid.format.sample_rate = 24000;
    buffers.push_back({std::move(invalid), 10});

    bool threw = false;
    try {
        static_cast<void>(make_playout_cursor_fade(buffers, 0, 15));
    }
    catch (const std::invalid_argument&) {
        threw = true;
    }
    CHECK(threw);
}

void test_cursor_rejects_unsorted_or_overlapping_buffers() {
    std::vector<PlayoutBuffer> unsorted;
    unsorted.push_back({constant_chunk(10, 100), 20});
    unsorted.push_back({constant_chunk(10, 200), 0});
    bool threw = false;
    try {
        static_cast<void>(make_playout_cursor_fade(unsorted, 0, 15));
    }
    catch (const std::invalid_argument&) {
        threw = true;
    }
    CHECK(threw);

    std::vector<PlayoutBuffer> overlapping;
    overlapping.push_back({constant_chunk(10, 100), 0});
    overlapping.push_back({constant_chunk(10, 200), 5});
    threw = false;
    try {
        static_cast<void>(make_playout_cursor_fade(overlapping, 0, 15));
    }
    catch (const std::invalid_argument&) {
        threw = true;
    }
    CHECK(threw);
}

} // namespace

int main() {
    test_cursor_uses_audible_buffer_not_producer_tail();
    test_cursor_can_cross_buffer_boundary();
    test_cursor_rejects_incompatible_buffers();
    test_cursor_rejects_unsorted_or_overlapping_buffers();
    return EXIT_SUCCESS;
}
