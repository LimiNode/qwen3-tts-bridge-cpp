#pragma once

#include <qwen_tts_bridge/audio.hpp>
#include <qwen_tts_bridge/transport.hpp>
#include <qwen_tts_bridge/playback/winmm_playback.hpp>

#include "play_options.hpp"
#include "play_request_state.hpp"

#include <iosfwd>

namespace qwen_tts_examples::play {

bool uses_mock_worker(const ProgramOptions& options);
void print_usage(std::ostream& out, const std::string& executable_name);
ProgramOptions parse_options(int argc, wchar_t** argv);
void validate_options(const ProgramOptions& options);
qwen_tts_bridge::StdIoTransportOptions make_transport_options(
    const ProgramOptions& options, bool safe_profile = false);
qwen_tts_bridge::AudioFormat requested_audio_format(const ProgramOptions& options);

void print_interactive_status(const ProgramOptions& options);
bool apply_interactive_command(ProgramOptions& options, const std::string& line);
bool has_sampling_overrides(const ProgramOptions& options);
std::string utf8_from_wide(const std::wstring& value);
bool read_interactive_line(std::string& line);
int run_playback_lifecycle_self_test();

} // namespace qwen_tts_examples::play
