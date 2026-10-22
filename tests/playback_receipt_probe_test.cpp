#include <qwen_tts_bridge/playback.hpp>

#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>

#define CHECK(expr)                                                            \
    do {                                                                       \
        if (!(expr)) {                                                         \
            std::cerr << "CHECK failed: " #expr " at " << __FILE__ << ':' \
                      << __LINE__ << '\\n';                                  \
            std::exit(EXIT_FAILURE);                                          \
        }                                                                        \
    } while (false)

namespace {

using qwen_tts_bridge::AudioFormat;
using qwen_tts_bridge::PcmChunk;
using qwen_tts_bridge::playback::PlaybackCue;
using qwen_tts_bridge::playback::PlaybackCueSelection;
using qwen_tts_bridge::playback::PlaybackCursorSnapshot;
using qwen_tts_bridge::playback::PlaybackReceiptProbe;
using qwen_tts_bridge::playback::PlaybackReceiptStatus;

PcmChunk pcm_chunk(
    std::uint64_t request_id,
    std::uint64_t first_sample,
    std::uint32_t sample_rate = 24000) {
    PcmChunk chunk;
    chunk.request_id = request_id;
    chunk.format = AudioFormat{"s16le", sample_rate, 1};
    chunk.first_sample = first_sample;
    chunk.sample_count = 2400;
    chunk.bytes.resize(chunk.sample_count * sizeof(std::int16_t));
    return chunk;
}

PlaybackCue cue(
    std::uint64_t epoch,
    std::uint64_t request_id,
    std::uint64_t first_sample) {
    PlaybackCue value;
    value.playback_epoch = epoch;
    value.request_id = request_id;
    value.first_sample = first_sample;
    value.sample_count = 1200;
    value.mouth_open = 0.75F;
    value.activity = 0.5F;
    return value;
}

void test_contiguous_timeline_and_cursor_selection() {
    PlaybackReceiptProbe probe;
    probe.begin(3, 17);
    CHECK(probe.observe_pcm(3, pcm_chunk(17, 0)) == PlaybackReceiptStatus::Accepted);
    CHECK(probe.observe_pcm(3, pcm_chunk(17, 2400)) == PlaybackReceiptStatus::Accepted);
    CHECK(probe.append_cue(cue(3, 17, 0)) == PlaybackReceiptStatus::Accepted);
    CHECK(probe.append_cue(cue(3, 17, 1200)) == PlaybackReceiptStatus::Accepted);

    PlaybackCursorSnapshot snapshot;
    snapshot.playback_epoch = 3;
    snapshot.request_id = 17;
    snapshot.utterance_sample = 1300;
    snapshot.sample_rate = 24000;
    snapshot.position_available = true;
    const auto selection = probe.select(snapshot);
    CHECK(selection.status == PlaybackCueSelection::Status::Selected);
    CHECK(selection.cue.first_sample == 1200);
    CHECK(probe.receipt().pcm_sample_count == 4800);
    CHECK(probe.receipt().cue_sample_count == 2400);
    CHECK(probe.receipt().pcm_contiguous);
    CHECK(probe.receipt().cue_contiguous);
    CHECK(probe.mark_terminal(3, 17));
    CHECK(probe.receipt().terminal);
    CHECK(probe.receipt().to_json().find("\"pcm_contiguous\":true") != std::string::npos);
    CHECK(selection.to_json().find("\"status\":\"selected\"") != std::string::npos);
}

void test_discontinuity_and_bounded_history_are_fail_closed() {
    PlaybackReceiptProbe probe(1);
    probe.begin(4, 31);
    CHECK(probe.observe_pcm(4, pcm_chunk(31, 0)) == PlaybackReceiptStatus::Accepted);
    CHECK(probe.observe_pcm(4, pcm_chunk(31, 2500)) == PlaybackReceiptStatus::DiscontinuousPcm);
    CHECK(probe.append_cue(cue(4, 31, 0)) == PlaybackReceiptStatus::Accepted);
    CHECK(probe.append_cue(cue(4, 31, 1200)) == PlaybackReceiptStatus::CueHistoryFull);
    CHECK(probe.receipt().cue_history_overflow);
    CHECK(!probe.receipt().pcm_contiguous);
}

void test_cue_contiguity_is_observation_continuity() {
    PlaybackReceiptProbe probe;
    probe.begin(5, 33);
    CHECK(probe.append_cue(cue(5, 33, 600)) == PlaybackReceiptStatus::Accepted);
    CHECK(probe.append_cue(cue(5, 33, 1800)) == PlaybackReceiptStatus::Accepted);
    CHECK(probe.receipt().cue_contiguous);
    CHECK(probe.receipt().cue_sample_count == 3000);
}

void test_stale_epoch_is_never_selected() {
    PlaybackReceiptProbe probe;
    probe.begin(10, 42);
    CHECK(probe.observe_pcm(10, pcm_chunk(42, 0)) == PlaybackReceiptStatus::Accepted);
    CHECK(probe.append_cue(cue(10, 42, 0)) == PlaybackReceiptStatus::Accepted);

    PlaybackCursorSnapshot old_snapshot;
    old_snapshot.playback_epoch = 10;
    old_snapshot.request_id = 42;
    old_snapshot.utterance_sample = 10;
    old_snapshot.sample_rate = 24000;
    old_snapshot.position_available = true;
    CHECK(probe.select(old_snapshot).status == PlaybackCueSelection::Status::Selected);

    probe.invalidate(11);
    const auto stale_audio = probe.observe_pcm(10, pcm_chunk(42, 0));
    CHECK(stale_audio == PlaybackReceiptStatus::StaleEpoch);
    CHECK(probe.select(old_snapshot).status == PlaybackCueSelection::Status::StaleEpoch);

    probe.begin(11, 43);
    CHECK(probe.observe_pcm(11, pcm_chunk(43, 0)) == PlaybackReceiptStatus::Accepted);
    CHECK(probe.append_cue(cue(11, 43, 0)) == PlaybackReceiptStatus::Accepted);
    old_snapshot.playback_epoch = 11;
    old_snapshot.request_id = 42;
    CHECK(probe.select(old_snapshot).status == PlaybackCueSelection::Status::StaleRequest);
    old_snapshot.request_id = 43;
    CHECK(probe.select(old_snapshot).status == PlaybackCueSelection::Status::Selected);
}

void test_terminal_identity_fences_late_callbacks() {
    PlaybackReceiptProbe probe;
    probe.begin(20, 77);
    CHECK(probe.observe_pcm(20, pcm_chunk(77, 0)) == PlaybackReceiptStatus::Accepted);
    CHECK(!probe.mark_terminal(19, 77));
    CHECK(!probe.mark_terminal(20, 76));
    CHECK(probe.mark_terminal(20, 77));
    CHECK(!probe.mark_terminal(20, 77));
    CHECK(probe.observe_pcm(20, pcm_chunk(77, 2400)) ==
          PlaybackReceiptStatus::AlreadyTerminal);
    CHECK(probe.append_cue(cue(20, 77, 0)) == PlaybackReceiptStatus::AlreadyTerminal);

    probe.begin(21, 78);
    CHECK(!probe.mark_terminal(20, 77));
    CHECK(!probe.receipt().terminal);
}

void test_sample_rate_identity_and_invalid_ranges() {
    PlaybackReceiptProbe probe;
    probe.begin(30, 88);
    CHECK(probe.observe_pcm(30, pcm_chunk(88, 0, 0)) ==
          PlaybackReceiptStatus::InvalidSampleRate);
    CHECK(probe.observe_pcm(30, pcm_chunk(88, 0, 24000)) == PlaybackReceiptStatus::Accepted);
    CHECK(probe.observe_pcm(30, pcm_chunk(88, 2400, 48000)) ==
          PlaybackReceiptStatus::SampleRateMismatch);

    PlaybackCursorSnapshot wrong_rate;
    wrong_rate.playback_epoch = 30;
    wrong_rate.request_id = 88;
    wrong_rate.utterance_sample = 10;
    wrong_rate.sample_rate = 48000;
    wrong_rate.position_available = true;
    CHECK(probe.select(wrong_rate).status == PlaybackCueSelection::Status::SampleRateMismatch);

    PlaybackCursorSnapshot right_rate = wrong_rate;
    right_rate.sample_rate = 24000;
    CHECK(probe.select(right_rate).status == PlaybackCueSelection::Status::OutsideCueTimeline);

    PcmChunk overflowing = pcm_chunk(88, std::numeric_limits<std::uint64_t>::max());
    CHECK(probe.observe_pcm(30, overflowing) == PlaybackReceiptStatus::InvalidRange);
    CHECK(probe.receipt().pcm_chunk_count == 1);
    CHECK(probe.receipt().sample_rate == 24000);
}

void test_epoch_is_monotonic() {
    PlaybackReceiptProbe probe;
    probe.begin(40, 99);
    try {
        probe.begin(40, 100);
        CHECK(false);
    } catch (const std::invalid_argument&) {
    }
    try {
        probe.invalidate(39);
        CHECK(false);
    } catch (const std::invalid_argument&) {
    }
    probe.invalidate(41);
    probe.begin(41, 101);
    try {
        probe.begin(41, 102);
        CHECK(false);
    } catch (const std::invalid_argument&) {
    }
    CHECK(probe.observe_pcm(40, pcm_chunk(99, 0)) == PlaybackReceiptStatus::StaleEpoch);
    CHECK(!probe.mark_terminal(40, 99));
    CHECK(!probe.mark_terminal(41, 99));
    CHECK(!probe.receipt().terminal);
}

} // namespace

int main() {
    test_contiguous_timeline_and_cursor_selection();
    test_discontinuity_and_bounded_history_are_fail_closed();
    test_cue_contiguity_is_observation_continuity();
    test_stale_epoch_is_never_selected();
    test_terminal_identity_fences_late_callbacks();
    test_sample_rate_identity_and_invalid_ranges();
    test_epoch_is_monotonic();
    return EXIT_SUCCESS;
}
