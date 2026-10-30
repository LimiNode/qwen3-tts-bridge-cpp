#include <qwen_tts_bridge/playback/winmm_playback.hpp>

#include "qwen_tts_bridge/playback/playback_interruption_diagnostics.hpp"

#include <cstdlib>
#include <iostream>
#include <optional>
#include <string>
#include <vector>

#define CHECK(expr)                                                            \
    do {                                                                       \
        if (!(expr)) {                                                         \
            std::cerr << "CHECK failed: " #expr << "\n";                    \
            std::exit(EXIT_FAILURE);                                            \
        }                                                                      \
    } while (false)

namespace {

using qwen_tts_bridge::playback::PlaybackInterruptionDiagnostic;
using qwen_tts_bridge::playback::detail::format_interruption_diagnostics_json;

void test_empty_document() {
    CHECK(format_interruption_diagnostics_json({}, 4) ==
        "{\n"
        "  \"schema_version\": 2,\n"
        "  \"measurement\": \"waveout_interruption_cursor\",\n"
        "  \"late_audio_after_terminal_count\": 4,\n"
        "  \"events\": [\n"
        "  ]\n"
        "}\n");
}

PlaybackInterruptionDiagnostic representative_event() {
    PlaybackInterruptionDiagnostic event;
    event.event_index = 3;
    event.requested_fade_ms = 25;
    event.old_request_id = 11;
    event.new_request_id = 12;
    event.old_terminal_state = "cancelled";
    event.new_terminal_state = "completed";
    event.cursor_available = true;
    event.cursor_frame = 1234;
    event.selected_buffer_start_frame = 1200;
    event.selected_buffer_frame_count = 480;
    event.selected_local_offset_frames = 34;
    event.queued_buffer_count = 2;
    event.queued_audio_ms = 37.5;
    event.submitted_head_frame = 2000;
    event.producer_ahead_frames = 766;
    event.fade_frame_count = 600;
    event.waveout_reset_called = true;
    event.waveout_reset_started_ms = 10.125;
    event.waveout_reset_completed_ms = 12.5;
    event.interruption_completed_ms = 15.75;
    return event;
}

void test_representative_event_and_optional_values() {
    const auto event = representative_event();
    const auto json = format_interruption_diagnostics_json({event}, 0);
    CHECK(json ==
        "{\n"
        "  \"schema_version\": 2,\n"
        "  \"measurement\": \"waveout_interruption_cursor\",\n"
        "  \"late_audio_after_terminal_count\": 0,\n"
        "  \"events\": [\n"
        "    {\"event_index\": 3, \"requested_fade_ms\": 25, \"old_request_id\": 11, \"new_request_id\": 12, \"old_terminal_state\": \"cancelled\", \"new_terminal_state\": \"completed\", \"cursor_available\": true, \"cursor_frame\": 1234, \"selected_buffer_start_frame\": 1200, \"selected_buffer_frame_count\": 480, \"selected_local_offset_frames\": 34, \"queued_buffer_count\": 2, \"queued_audio_ms\": 37.500, \"submitted_head_frame\": 2000, \"producer_ahead_frames\": 766, \"fade_frame_count\": 600, \"waveout_reset_called\": true, \"waveout_reset_started_ms\": 10.125, \"waveout_reset_completed_ms\": 12.500, \"interruption_completed_ms\": 15.750}\n"
        "  ]\n"
        "}\n");

    auto absent = event;
    absent.cursor_available = false;
    absent.waveout_reset_called = false;
    absent.waveout_reset_started_ms.reset();
    absent.waveout_reset_completed_ms.reset();
    absent.interruption_completed_ms.reset();
    const auto absent_json = format_interruption_diagnostics_json({absent}, 1);
    CHECK(absent_json.find("\"cursor_available\": false") != std::string::npos);
    CHECK(absent_json.find("\"waveout_reset_started_ms\": null") != std::string::npos);
    CHECK(absent_json.find("\"waveout_reset_completed_ms\": null") != std::string::npos);
    CHECK(absent_json.find("\"interruption_completed_ms\": null") != std::string::npos);
}

void test_multiple_events_preserve_order_and_separator() {
    auto first = representative_event();
    auto second = representative_event();
    first.event_index = 4;
    second.event_index = 5;
    second.old_request_id = 21;
    const auto json = format_interruption_diagnostics_json({first, second}, 2);
    const auto first_position = json.find("\"event_index\": 4");
    const auto second_position = json.find("\"event_index\": 5");
    CHECK(first_position != std::string::npos);
    CHECK(second_position != std::string::npos);
    CHECK(first_position < second_position);
    CHECK(json.find("},\n    {\"event_index\": 5") != std::string::npos);
}

} // namespace

int main() {
    test_empty_document();
    test_representative_event_and_optional_values();
    test_multiple_events_preserve_order_and_separator();
    return 0;
}
