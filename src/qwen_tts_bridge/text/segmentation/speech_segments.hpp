#pragma once

#include <cstddef>
#include <string_view>
#include <vector>

namespace qwen_tts_bridge::text {

/// \brief Exact half-open UTF-8 source range; whitespace is not discarded.
struct SpeechSegment {
    std::size_t begin = 0;
    std::size_t end = 0;
};

/// \brief Resource limits, not linguistic or model-token estimates.
struct SpeechSegmentLimits {
    std::size_t max_source_bytes = 1024 * 1024;
    std::size_t max_segment_bytes = 4096;
    std::size_t max_segments = 256;
};

/// \brief Plan conservative RU/EN sentence boundaries without changing text.
///
/// Returned ranges partition the complete source, including whitespace and
/// combining accents. A final unpunctuated utterance is retained as a whole.
/// Decimal points, initials, common abbreviations and balanced quotes/brackets
/// are protected. This heuristic is not a grammar parser or proof of prosody.
/// No fallback cuts at arbitrary words: an oversized indivisible span fails.
/// \param source UTF-8 text, without embedded NUL.
/// \param limits Explicit finite memory/count bounds.
/// \return Ordered ranges; an all-whitespace source has no spoken segments.
/// \throws std::invalid_argument for invalid UTF-8 or zero limits.
/// \throws std::length_error when a source, segment or count exceeds its limit.
std::vector<SpeechSegment> plan_speech_segments(
    std::string_view source,
    SpeechSegmentLimits limits = {});

} // namespace qwen_tts_bridge::text
