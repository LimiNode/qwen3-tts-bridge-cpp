#pragma once

#include <string_view>

namespace qwen_tts_bridge::native_worker {

/// Publish one complete stderr diagnostic line without interleaving writers.
void write_diagnostic_line(std::string_view line) noexcept;

} // namespace qwen_tts_bridge::native_worker
