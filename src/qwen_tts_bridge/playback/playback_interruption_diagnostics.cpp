#include "playback_interruption_diagnostics.hpp"

#include "winmm_playback.hpp"

#include <iomanip>
#include <sstream>

namespace qwen_tts_bridge::playback::detail {

std::string format_interruption_diagnostics_json(
    const std::vector<PlaybackInterruptionDiagnostic>& diagnostics,
    std::uint64_t late_audio_after_terminal_count) {
    std::ostringstream json;
    json << std::fixed << std::setprecision(3);
    json << "{\n"
         << "  \"schema_version\": 2,\n"
         << "  \"measurement\": \"waveout_interruption_cursor\",\n"
         << "  \"late_audio_after_terminal_count\": "
         << late_audio_after_terminal_count << ",\n"
         << "  \"events\": [\n";
    for (std::size_t index = 0; index < diagnostics.size(); ++index) {
        const auto& event = diagnostics[index];
        json << "    {\"event_index\": " << event.event_index
             << ", \"requested_fade_ms\": " << event.requested_fade_ms
             << ", \"old_request_id\": " << event.old_request_id
             << ", \"new_request_id\": " << event.new_request_id
             << ", \"old_terminal_state\": \"" << event.old_terminal_state
             << "\", \"new_terminal_state\": \"" << event.new_terminal_state
             << "\", \"cursor_available\": "
             << (event.cursor_available ? "true" : "false")
             << ", \"cursor_frame\": " << event.cursor_frame
             << ", \"selected_buffer_start_frame\": "
             << event.selected_buffer_start_frame
             << ", \"selected_buffer_frame_count\": "
             << event.selected_buffer_frame_count
             << ", \"selected_local_offset_frames\": "
             << event.selected_local_offset_frames
             << ", \"queued_buffer_count\": " << event.queued_buffer_count
             << ", \"queued_audio_ms\": " << event.queued_audio_ms
             << ", \"submitted_head_frame\": " << event.submitted_head_frame
             << ", \"producer_ahead_frames\": " << event.producer_ahead_frames
             << ", \"fade_frame_count\": " << event.fade_frame_count
             << ", \"waveout_reset_called\": "
             << (event.waveout_reset_called ? "true" : "false")
             << ", \"waveout_reset_started_ms\": ";
        if (event.waveout_reset_started_ms.has_value()) {
            json << event.waveout_reset_started_ms.value();
        }
        else {
            json << "null";
        }
        json << ", \"waveout_reset_completed_ms\": ";
        if (event.waveout_reset_completed_ms.has_value()) {
            json << event.waveout_reset_completed_ms.value();
        }
        else {
            json << "null";
        }
        json << ", \"interruption_completed_ms\": ";
        if (event.interruption_completed_ms.has_value()) {
            json << event.interruption_completed_ms.value();
        }
        else {
            json << "null";
        }
        json << "}";
        if (index + 1 != diagnostics.size()) {
            json << ',';
        }
        json << '\n';
    }
    json << "  ]\n}\n";
    return json.str();
}

} // namespace qwen_tts_bridge::playback::detail
