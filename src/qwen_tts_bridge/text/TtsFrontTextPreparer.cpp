#include "TtsFrontTextPreparer.hpp"

#include <cstdint>
#include <string_view>
#include <utility>

namespace qwen_tts_bridge {
namespace {

constexpr const char* kCombiningAcute = "\xCC\x81";

bool is_vowel(std::uint32_t code_point) {
    switch (code_point) {
    case 0x0410u: case 0x0430u: // А а
    case 0x0415u: case 0x0435u: // Е е
    case 0x0401u: case 0x0451u: // Ё ё
    case 0x0418u: case 0x0438u: // И и
    case 0x041Eu: case 0x043Eu: // О о
    case 0x0423u: case 0x0443u: // У у
    case 0x042Bu: case 0x044Bu: // Ы ы
    case 0x042Du: case 0x044Du: // Э э
    case 0x042Eu: case 0x044Eu: // Ю ю
    case 0x042Fu: case 0x044Fu: // Я я
    case 0x0041u: case 0x0061u: // A a
    case 0x0045u: case 0x0065u: // E e
    case 0x0049u: case 0x0069u: // I i
    case 0x004Fu: case 0x006Fu: // O o
    case 0x0055u: case 0x0075u: // U u
    case 0x0059u: case 0x0079u: // Y y
        return true;
    default:
        return false;
    }
}

bool decode_code_point(
    std::string_view value,
    std::size_t offset,
    std::uint32_t& code_point,
    std::size_t& width) {
    if (offset >= value.size()) {
        return false;
    }
    const auto lead = static_cast<unsigned char>(value[offset]);
    if (lead <= 0x7Fu) {
        code_point = lead;
        width = 1;
        return true;
    }
    if (lead >= 0xC2u && lead <= 0xDFu) {
        width = 2;
        code_point = lead & 0x1Fu;
    }
    else if (lead >= 0xE0u && lead <= 0xEFu) {
        width = 3;
        code_point = lead & 0x0Fu;
    }
    else if (lead >= 0xF0u && lead <= 0xF4u) {
        width = 4;
        code_point = lead & 0x07u;
    }
    else {
        return false;
    }
    if (offset + width > value.size()) {
        return false;
    }
    for (std::size_t index = 1; index < width; ++index) {
        const auto byte = static_cast<unsigned char>(value[offset + index]);
        if ((byte & 0xC0u) != 0x80u) {
            return false;
        }
        code_point = (code_point << 6u) | (byte & 0x3Fu);
    }
    return true;
}

std::string render_word_stress(
    const std::string& word,
    std::size_t stressed_vowel,
    bool& rendered) {
    std::string output;
    output.reserve(word.size() + 2);
    std::size_t vowel_index = 0;
    for (std::size_t offset = 0; offset < word.size();) {
        std::uint32_t code_point = 0;
        std::size_t width = 0;
        if (!decode_code_point(word, offset, code_point, width)) {
            output = word;
            return output;
        }
        output.append(word, offset, width);
        if (is_vowel(code_point)) {
            if (vowel_index == stressed_vowel) {
                output += kCombiningAcute;
                rendered = true;
                return output + word.substr(offset + width);
            }
            ++vowel_index;
        }
        offset += width;
    }
    return output;
}

std::string render_explicit_stress(
    const tts_front::TextFrontendResult& result,
    bool& rendered_any) {
    std::string output;
    std::size_t cursor = 0;
    for (const auto& word : result.words) {
        if (word.source_offset < cursor ||
            word.source_offset > result.normalized_text.size()) {
            continue;
        }
        output.append(
            result.normalized_text,
            cursor,
            word.source_offset - cursor);
        const auto surface_end = word.source_offset + word.surface.size();
        if (surface_end > result.normalized_text.size()) {
            continue;
        }
        const std::string replacement =
            word.pronunciation.empty() ? word.surface : word.pronunciation;
        if (word.stressed_vowel) {
            output += render_word_stress(
                replacement,
                *word.stressed_vowel,
                rendered_any);
        }
        else {
            output += replacement;
        }
        cursor = surface_end;
    }
    output.append(result.normalized_text, cursor, std::string::npos);
    return output;
}

void copy_frontend_diagnostics(
    const tts_front::TextFrontendResult& result,
    PreparedText& prepared) {
    prepared.frontend_normalized_text = result.normalized_text;
    prepared.frontend_pronunciation_text = result.pronunciation_text;
    prepared.frontend_has_uncertainty = result.has_uncertainty();
    prepared.frontend_warnings.clear();
    for (const auto& warning : result.warnings) {
        prepared.frontend_warnings.push_back({
            tts_front::to_string(warning.code),
            warning.message,
            warning.offset,
            warning.length});
    }
    prepared.frontend_stress_decisions.clear();
    for (const auto& decision : result.stress_decisions) {
        prepared.frontend_stress_decisions.push_back({
            decision.word,
            decision.stressed_vowel,
            decision.from_dictionary,
            decision.reason});
    }
}

} // namespace

TtsFrontTextPreparer::TtsFrontTextPreparer(
    TtsFrontTextPreparerOptions options)
    : options_(std::move(options)) {}

bool TtsFrontTextPreparer::prepare(
    const TtsRequest& request,
    PreparedText& prepared,
    TtsError& error) const {
    const auto result = frontend_.process(request.text, options_.frontend);
    copy_frontend_diagnostics(result, prepared);
    prepared.original_text = request.text;

    if (result.normalized_text.empty()) {
        error = {
            request.id,
            "request_error",
            "empty_text",
            "text frontend produced no usable text"};
        return false;
    }

    prepared.effective_text = result.pronunciation_text.empty()
        ? result.normalized_text
        : result.pronunciation_text;

    if (options_.render_capability ==
        TextRenderCapability::ExplicitCombiningStress) {
        bool rendered_any = false;
        const auto rendered = render_explicit_stress(result, rendered_any);
        if (!rendered.empty()) {
            prepared.effective_text = rendered;
        }
        if (!rendered_any && !result.stress_decisions.empty()) {
            prepared.frontend_has_uncertainty = true;
            prepared.frontend_warnings.push_back({
                "stress_rendering_unavailable",
                "Semantic stress was present but no compatible word span could be rendered",
                0,
                0});
        }
    }

    if (prepared.effective_text.empty()) {
        error = {
            request.id,
            "request_error",
            "empty_text",
            "text frontend produced empty pronunciation text"};
        return false;
    }
    return true;
}

} // namespace qwen_tts_bridge
