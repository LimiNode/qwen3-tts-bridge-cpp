#pragma once

#include <string_view>

namespace qwen_tts_bridge::native_worker {

/// Publish one complete stderr diagnostic line without interleaving writers.
///
/// Native metrics use a JSONL record prefixed with `qtb_metric `.  Callers
/// must build the complete line before entering this boundary so a competing
/// worker thread cannot produce a malformed record.
void write_diagnostic_line(std::string_view line) noexcept;

} // namespace qwen_tts_bridge::native_worker
