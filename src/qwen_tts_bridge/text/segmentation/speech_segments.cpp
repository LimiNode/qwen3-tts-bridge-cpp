#include <qwen_tts_bridge/text/segmentation.hpp>

#include <cstdint>
#include <stdexcept>
#include <string>

namespace qwen_tts_bridge::text {
namespace {

struct Character {
    std::uint32_t value;
    std::size_t begin;
    std::size_t end;
};

std::vector<Character> decode(std::string_view source) {
    std::vector<Character> result;
    for (std::size_t offset = 0; offset < source.size();) {
        const auto begin = offset;
        const auto lead = static_cast<unsigned char>(source[offset++]);
        std::uint32_t value = lead;
        std::size_t continuation = 0;
        if (lead >= 0xC2 && lead <= 0xDF) {
            value = lead & 0x1F;
            continuation = 1;
        }
        else if (lead >= 0xE0 && lead <= 0xEF) {
            value = lead & 0x0F;
            continuation = 2;
        }
        else if (lead >= 0xF0 && lead <= 0xF4) {
            value = lead & 7;
            continuation = 3;
        }
        else if (lead >= 0x80 || lead == 0) {
            throw std::invalid_argument("speech segmentation requires UTF-8 without NUL");
        }
        if (continuation > source.size() - offset) {
            throw std::invalid_argument("truncated UTF-8 in speech segmentation");
        }
        for (std::size_t index = 0; index < continuation; ++index) {
            const auto byte = static_cast<unsigned char>(source[offset++]);
            if ((byte & 0xC0) != 0x80) {
                throw std::invalid_argument("invalid UTF-8 in speech segmentation");
            }
            value = (value << 6) | (byte & 0x3F);
        }
        if ((continuation == 2 && value < 0x800) ||
            (continuation == 3 && value < 0x10000) || value > 0x10FFFF ||
            (value >= 0xD800 && value <= 0xDFFF)) {
            throw std::invalid_argument("invalid UTF-8 scalar in speech segmentation");
        }
        result.push_back({value, begin, offset});
    }
    return result;
}

bool is_space(std::uint32_t value) {
    return (value >= 9 && value <= 13) || value == 32 || value == 0xA0 ||
        value == 0x1680 || (value >= 0x2000 && value <= 0x200A) ||
        value == 0x2028 || value == 0x2029 || value == 0x202F ||
        value == 0x205F || value == 0x3000;
}

bool is_letter(std::uint32_t value) {
    return (value >= 'a' && value <= 'z') || (value >= 'A' && value <= 'Z') ||
        (value >= 0x410 && value <= 0x44F) || value == 0x401 || value == 0x451;
}

bool is_digit(std::uint32_t value) {
    return value >= '0' && value <= '9';
}

bool is_combining_mark(std::uint32_t value) {
    return value >= 0x300 && value <= 0x36F;
}

std::uint32_t lower(std::uint32_t value) {
    if ((value >= 'A' && value <= 'Z') || (value >= 0x410 && value <= 0x42F)) {
        return value + 32;
    }
    return value == 0x401 ? 0x451 : value;
}

bool protected_period(const std::vector<Character>& chars, std::size_t index) {
    if (index != 0 && index + 1 < chars.size() &&
        is_digit(chars[index - 1].value) && is_digit(chars[index + 1].value)) {
        return true;
    }
    std::size_t begin = index;
    while (begin != 0 && (is_letter(chars[begin - 1].value) ||
        is_combining_mark(chars[begin - 1].value))) {
        --begin;
    }
    std::u32string word;
    for (auto offset = begin; offset < index; ++offset) {
        if (!is_combining_mark(chars[offset].value)) {
            word.push_back(static_cast<char32_t>(lower(chars[offset].value)));
        }
    }
    // Conservatively retain initials, including dotted acronyms (U.S.A.).
    if (word.size() == 1) {
        return true;
    }
    static const std::u32string abbreviations[] = {
        U"mr", U"mrs", U"ms", U"dr", U"prof", U"sr", U"jr", U"st", U"vs",
        U"etc", U"fig", U"no", U"inc",
        U"\u0433\u0433", U"\u0443\u043b", U"\u043a\u0432",
        U"\u0438\u043c", U"\u0440\u0438\u0441", U"\u0441\u0442\u0440",
        U"\u0442\u0435\u043b", U"\u0441\u043c", U"\u043f\u0440\u043e\u0444",
        U"\u0434\u043e\u0446", U"\u0430\u043a\u0430\u0434", U"\u0440\u0443\u0431"
    };
    for (const auto& abbreviation : abbreviations) {
        if (word == abbreviation) {
            return true;
        }
    }
    return false;
}

bool terminal(std::uint32_t value) {
    return value == '.' || value == '!' || value == '?' || value == 0x2026;
}

void update_nesting(
    std::uint32_t value,
    bool word_apostrophe,
    std::vector<std::uint32_t>& closes) {
    if (word_apostrophe) {
        return;
    }
    if (!closes.empty() && value == closes.back()) {
        closes.pop_back();
        return;
    }
    switch (value) {
    case '"': closes.push_back('"'); break;
    case '\'': closes.push_back('\''); break;
    case '(': closes.push_back(')'); break;
    case '[': closes.push_back(']'); break;
    case '{': closes.push_back('}'); break;
    case 0xAB: closes.push_back(0xBB); break;
    case 0x201C: closes.push_back(0x201D); break;
    case 0x201E: closes.push_back(0x201C); break;
    case 0x2018: closes.push_back(0x2019); break;
    default: break;
    }
}

} // namespace

std::vector<SpeechSegment> plan_speech_segments(
    std::string_view source,
    SpeechSegmentLimits limits) {
    if (limits.max_source_bytes == 0 || limits.max_segment_bytes == 0 ||
        limits.max_segments == 0) {
        throw std::invalid_argument("speech segmentation limits must be positive");
    }
    if (source.size() > limits.max_source_bytes) {
        throw std::length_error("speech segmentation source byte limit exceeded");
    }
    const auto chars = decode(source);
    std::vector<SpeechSegment> segments;
    std::vector<std::uint32_t> closes;
    std::size_t begin = 0;
    bool has_spoken_text = false;
    const auto append = [&](std::size_t end) {
        if (end - begin > limits.max_segment_bytes) {
            throw std::length_error(
                "speech segment exceeds byte limit; add a complete sentence boundary");
        }
        if (segments.size() == limits.max_segments) {
            throw std::length_error("speech segment count limit exceeded");
        }
        segments.push_back({begin, end});
        begin = end;
    };

    for (std::size_t index = 0; index < chars.size(); ++index) {
        const auto value = chars[index].value;
        has_spoken_text = has_spoken_text || !is_space(value);
        const bool word_apostrophe = (value == '\'' || value == 0x2019) &&
            index != 0 && index + 1 < chars.size() &&
            is_letter(chars[index - 1].value) && is_letter(chars[index + 1].value);
        update_nesting(value, word_apostrophe, closes);
        if (!terminal(value) || (value == '.' && protected_period(chars, index))) {
            continue;
        }
        auto end = index + 1;
        while (end < chars.size() && terminal(chars[end].value)) {
            ++end;
        }
        auto nesting_depth = closes.size();
        while (end < chars.size() && nesting_depth != 0 &&
            chars[end].value == closes[nesting_depth - 1]) {
            --nesting_depth;
            ++end;
        }
        if (nesting_depth != 0 || (end < chars.size() && !is_space(chars[end].value))) {
            continue;
        }
        while (end < chars.size() && is_space(chars[end].value)) {
            ++end;
        }
        append(end == chars.size() ? source.size() : chars[end].begin);
        index = end - 1;
        closes.clear();
        has_spoken_text = false;
    }
    if (begin != source.size() && has_spoken_text) {
        append(source.size());
    }
    else if (!segments.empty()) {
        segments.back().end = source.size();
    }
    return segments;
}

} // namespace qwen_tts_bridge::text
