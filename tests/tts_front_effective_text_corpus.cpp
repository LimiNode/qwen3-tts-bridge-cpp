#include <qwen_tts_bridge/text.hpp>

#include <algorithm>
#include <cstdlib>
#include <iostream>
#include <string>
#include <string_view>
#include <tuple>
#include <vector>

#define CHECK(expr)                                                            \
    do {                                                                       \
        if (!(expr)) {                                                         \
            std::cerr << "CHECK failed: " #expr << " at " << __FILE__ << ':'  \
                      << __LINE__ << '\n';                                    \
            return EXIT_FAILURE;                                               \
        }                                                                      \
    } while (false)

namespace {

using namespace qwen_tts_bridge;

struct ExpectedWarning {
    const char* code;
    std::size_t offset;
    std::size_t length;
};

struct CorpusCase {
    const char* id;
    const char* text;
    tts_front::Language language;
    TextRenderCapability render;
    bool dictionary;
    tts_front::MixedLanguagePolicy mixed_policy;
    const char* expected_normalized_text;
    const char* expected_pronunciation_text;
    const char* expected_effective_text;
    bool expected_uncertainty;
    const ExpectedWarning* expected_warnings;
    std::size_t expected_warning_count;
};

constexpr ExpectedWarning kLeadingZeroWarnings[] = {
    {"unresolved_number", 3, 4},
};
constexpr ExpectedWarning kAgreementWarnings[] = {
    {"unresolved_number", 3, 3},
};
constexpr ExpectedWarning kRussianCurrencyWarnings[] = {
    {"unresolved_number", 10, 12},
};
constexpr ExpectedWarning kGenitiveDecimalWarnings[] = {
    {"unresolved_number", 11, 3},
};
constexpr ExpectedWarning kNumericBoundaryWarnings[] = {
    {"unresolved_number", 0, 3},
};
constexpr ExpectedWarning kMixedTechnicalWarnings[] = {
    {"ambiguous_normalization", 0, 59},
};
constexpr ExpectedWarning kMixedSegmentWarnings[] = {
    {"ambiguous_normalization", 0, 36},
};
constexpr ExpectedWarning kEnglishControlWarnings[] = {
    {"unresolved_number", 27, 10},
};
constexpr ExpectedWarning kCurrencyBoundaryWarnings[] = {
    {"unresolved_number", 0, 11},
    {"unresolved_number", 12, 9},
    {"unresolved_number", 22, 7},
    {"unresolved_number", 30, 7},
};
constexpr ExpectedWarning kCurrencyContinuationWarnings[] = {
    {"unresolved_number", 0, 10},
    {"unresolved_number", 15, 8},
};
constexpr ExpectedWarning kTechnicalProtectedWarnings[] = {
    {"unresolved_number", 20, 9},
    {"unresolved_number", 33, 9},
    {"unresolved_number", 48, 7},
};

constexpr CorpusCase kCorpus[] = {
    {"ru_leading_zero_year", "В 0026 году", tts_front::Language::Russian,
     TextRenderCapability::Base, false, tts_front::MixedLanguagePolicy::DominantLanguage,
     "В 0026 году", "В 0026 году", "В 0026 году", true,
     kLeadingZeroWarnings, 1},
    {"ru_numbers", "В 2026 году 2 книги и 5 домов.", tts_front::Language::Russian,
     TextRenderCapability::Base, false, tts_front::MixedLanguagePolicy::DominantLanguage,
     "В две тысячи двадцать шестом году два книги и пять домов.",
     "В две тысячи двадцать шестом году два книги и пять домов.",
     "В две тысячи двадцать шестом году два книги и пять домов.", false,
     nullptr, 0},
    {"ru_agreement", "У 21-го клиента 3 новых договора.", tts_front::Language::Russian,
     TextRenderCapability::Base, false, tts_front::MixedLanguagePolicy::DominantLanguage,
     "У 21-го клиента три новых договора.", "У 21-го клиента три новых договора.",
     "У 21-го клиента три новых договора.", true, kAgreementWarnings, 1},
    {"ru_supported_decimal", "В отчёте 1,5 метра.", tts_front::Language::Russian,
     TextRenderCapability::Base, false, tts_front::MixedLanguagePolicy::DominantLanguage,
     "В отчёте одна целая пять десятых метра.",
     "В отчёте одна целая пять десятых метра.",
     "В отчёте одна целая пять десятых метра.", false, nullptr, 0},
    {"ru_stress_homographs", "замок мука горе", tts_front::Language::Russian,
     TextRenderCapability::ExplicitCombiningStress, true,
     tts_front::MixedLanguagePolicy::DominantLanguage,
     "замок мука горе", "замок мука горе", "за́мок мука́ го́ре", false, nullptr, 0},
    {"ru_date_time", "В 2026 г. встреча в 14:30.", tts_front::Language::Russian,
     TextRenderCapability::Base, false, tts_front::MixedLanguagePolicy::DominantLanguage,
     "В две тысячи двадцать шестом году встреча в четырнадцать часов тридцать минут.",
     "В две тысячи двадцать шестом году встреча в четырнадцать часов тридцать минут.",
     "В две тысячи двадцать шестом году встреча в четырнадцать часов тридцать минут.",
     false, nullptr, 0},
    {"ru_currency", "Цена: 1 234,50 ₽ и 50 евро.", tts_front::Language::Russian,
     TextRenderCapability::Base, false, tts_front::MixedLanguagePolicy::DominantLanguage,
     "Цена: 1 234,50 ₽ и пятьдесят евро.", "Цена: 1 234,50 ₽ и пятьдесят евро.",
     "Цена: 1 234,50 ₽ и пятьдесят евро.", true, kRussianCurrencyWarnings, 1},
    {"ru_abbreviations", "API, RTX 4090 и CUDA 13.3 готовы.", tts_front::Language::Russian,
     TextRenderCapability::Base, false, tts_front::MixedLanguagePolicy::DominantLanguage,
     "API, RTX 4090 и CUDA 13.3 готовы.", "API, RTX 4090 и CUDA 13.3 готовы.",
     "API, RTX 4090 и CUDA 13.3 готовы.", false, nullptr, 0},
    {"ru_genitive_decimal", "После 1,5 попыток и 2,25 часа.", tts_front::Language::Russian,
     TextRenderCapability::Base, false, tts_front::MixedLanguagePolicy::DominantLanguage,
     "После 1,5 попыток и две целых двадцать пять сотых часа.",
     "После 1,5 попыток и две целых двадцать пять сотых часа.",
     "После 1,5 попыток и две целых двадцать пять сотых часа.", true,
     kGenitiveDecimalWarnings, 1},
    {"ru_numeric_boundaries", "21-й, 3.14, 1,5%, 1 000 000 и 999999.",
     tts_front::Language::Russian, TextRenderCapability::Base, false,
     tts_front::MixedLanguagePolicy::DominantLanguage,
     "21-й, 3.14, одна целая пять десятых процента, один миллион и девятьсот девяносто девять тысяч девятьсот девяносто девять.",
     "21-й, 3.14, одна целая пять десятых процента, один миллион и девятьсот девяносто девять тысяч девятьсот девяносто девять.",
     "21-й, 3.14, одна целая пять десятых процента, один миллион и девятьсот девяносто девять тысяч девятьсот девяносто девять.",
     true, kNumericBoundaryWarnings, 1},
    {"mixed_technical", "Сегодня API v2.3 работает через HTTP/2.", tts_front::Language::Auto,
     TextRenderCapability::Base, false, tts_front::MixedLanguagePolicy::DominantLanguage,
     "Сегодня API v2.3 работает через HTTP/2.", "Сегодня API v2.3 работает через HTTP/2.",
     "Сегодня API v2.3 работает через HTTP/2.", true, kMixedTechnicalWarnings, 1},
    {"mixed_segment_candidates", "Цена $12.50 и 3 кг; API v2.3.", tts_front::Language::Auto,
     TextRenderCapability::Base, false, tts_front::MixedLanguagePolicy::SegmentCandidates,
     "Цена twelve dollars fifty cents и три килограмма; API v2.3.",
     "Цена twelve dollars fifty cents и три килограмма; API v2.3.",
     "Цена twelve dollars fifty cents и три килограмма; API v2.3.", true,
     kMixedSegmentWarnings, 1},
    {"en_controls", "Build 42 uses CUDA 13.3 on 2026-10-24.", tts_front::Language::English,
     TextRenderCapability::Base, false, tts_front::MixedLanguagePolicy::DominantLanguage,
     "Build forty two uses CUDA 13.3 on 2026-10-24.",
     "Build forty two uses CUDA 13.3 on 2026-10-24.",
     "Build forty two uses CUDA 13.3 on 2026-10-24.", true,
     kEnglishControlWarnings, 1},
    {"currency_boundaries", "$ 1,234.50; €-2.00; £ 3.5; ¥+4,50.",
     tts_front::Language::English, TextRenderCapability::Base, false,
     tts_front::MixedLanguagePolicy::DominantLanguage,
     "$ 1,234.50; €-2.00; £ 3.5; ¥+4,50.",
     "$ 1,234.50; €-2.00; £ 3.5; ¥+4,50.",
     "$ 1,234.50; €-2.00; £ 3.5; ¥+4,50.", true,
     kCurrencyBoundaryWarnings, 4},
    {"currency_continuations", "$1,23% 456 and €1,234/567.", tts_front::Language::English,
     TextRenderCapability::Base, false, tts_front::MixedLanguagePolicy::DominantLanguage,
     "$1,23% 456 and €1,234/five hundred sixty seven.",
     "$1,23% 456 and €1,234/five hundred sixty seven.",
     "$1,23% 456 and €1,234/five hundred sixty seven.", true,
     kCurrencyContinuationWarnings, 2},
    {"technical_protected", "https://example.com/$1,234%25 RTX-4090/123 C++17,234%25",
     tts_front::Language::English, TextRenderCapability::Base, false,
     tts_front::MixedLanguagePolicy::DominantLanguage,
     "https://example.com/$1,234%25 RTX-4090/123 C++17,234%25",
     "https://example.com/$1,234%25 RTX-4090/123 C++17,234%25",
     "https://example.com/$1,234%25 RTX-4090/123 C++17,234%25", true,
     kTechnicalProtectedWarnings, 3},
    {"ru_plain_control", "Простая фраза без чисел.", tts_front::Language::Russian,
     TextRenderCapability::Base, false, tts_front::MixedLanguagePolicy::DominantLanguage,
     "Простая фраза без чисел.", "Простая фраза без чисел.",
     "Простая фраза без чисел.", false, nullptr, 0},
};

std::string json_escape(std::string_view value) {
    std::string escaped;
    escaped.reserve(value.size() + 8);
    for (const unsigned char byte : value) {
        switch (byte) {
        case '"': escaped += "\\\""; break;
        case '\\': escaped += "\\\\"; break;
        case '\n': escaped += "\\n"; break;
        case '\r': escaped += "\\r"; break;
        case '\t': escaped += "\\t"; break;
        default:
            if (byte < 0x20u) {
                constexpr char hex[] = "0123456789abcdef";
                escaped += "\\u00";
                escaped += hex[(byte >> 4u) & 0x0Fu];
                escaped += hex[byte & 0x0Fu];
            }
            else {
                escaped.push_back(static_cast<char>(byte));
            }
        }
    }
    return escaped;
}

void write_string(std::ostream& output, std::string_view value) {
    output << '"' << json_escape(value) << '"';
}

using WarningKey = std::tuple<std::string, std::size_t, std::size_t>;

std::vector<WarningKey> canonical_warnings(const PreparedText& prepared) {
    std::vector<WarningKey> warnings;
    warnings.reserve(prepared.frontend_warnings.size());
    for (const auto& warning : prepared.frontend_warnings) {
        warnings.emplace_back(warning.code, warning.offset, warning.length);
    }
    std::sort(warnings.begin(), warnings.end());
    return warnings;
}

int verify_oracle(const CorpusCase& corpus_case, const PreparedText& prepared) {
    CHECK(prepared.original_text == corpus_case.text);
    CHECK(prepared.frontend_normalized_text == corpus_case.expected_normalized_text);
    CHECK(prepared.frontend_pronunciation_text == corpus_case.expected_pronunciation_text);
    CHECK(prepared.effective_text == corpus_case.expected_effective_text);
    CHECK(prepared.frontend_has_uncertainty == corpus_case.expected_uncertainty);

    const auto actual_warnings = canonical_warnings(prepared);
    CHECK(actual_warnings.size() == corpus_case.expected_warning_count);
    for (std::size_t index = 0; index < actual_warnings.size(); ++index) {
        const auto& actual = actual_warnings[index];
        const auto& expected = corpus_case.expected_warnings[index];
        const WarningKey expected_key{expected.code, expected.offset, expected.length};
        CHECK(actual == expected_key);
    }
    return EXIT_SUCCESS;
}

int emit_corpus() {
    std::cout << "{\"schema\":1,\"cases\":[\n";
    bool first = true;
    for (const auto& corpus_case : kCorpus) {
        tts_front::PronunciationDictionary dictionary;
        if (corpus_case.dictionary) {
            CHECK(dictionary.add_token("замок", "замок", 0));
            CHECK(dictionary.add_token("мука", "мука", 1));
            CHECK(dictionary.add_token("горе", "горе", 0));
        }

        TtsFrontTextPreparerOptions options;
        options.frontend.language = corpus_case.language;
        options.frontend.diagnostics = true;
        options.frontend.mixed_language_policy = corpus_case.mixed_policy;
        options.frontend.dictionary = corpus_case.dictionary ? &dictionary : nullptr;
        options.render_capability = corpus_case.render;
        TtsFrontTextPreparer preparer(options);

        TtsRequest request;
        request.text = corpus_case.text;
        PreparedText prepared;
        TtsError error;
        CHECK(preparer.prepare(request, prepared, error));
        CHECK(error.code.empty());
        CHECK(!prepared.effective_text.empty());
        CHECK(verify_oracle(corpus_case, prepared) == EXIT_SUCCESS);

        if (!first) {
            std::cout << ",\n";
        }
        first = false;
        std::cout << "  {\"id\":";
        write_string(std::cout, corpus_case.id);
        std::cout << ",\"input\":";
        write_string(std::cout, request.text);
        std::cout << ",\"language\":";
        write_string(std::cout, tts_front::to_string(corpus_case.language));
        std::cout << ",\"render\":";
        write_string(std::cout, corpus_case.render == TextRenderCapability::Base
            ? "base" : "explicit_combining_stress");
        std::cout << ",\"normalized_text\":";
        write_string(std::cout, prepared.frontend_normalized_text);
        std::cout << ",\"pronunciation_text\":";
        write_string(std::cout, prepared.frontend_pronunciation_text);
        std::cout << ",\"effective_text\":";
        write_string(std::cout, prepared.effective_text);
        std::cout << ",\"warning_count\":" << prepared.frontend_warnings.size();
        std::cout << ",\"uncertain\":"
                  << (prepared.frontend_has_uncertainty ? "true" : "false");
        std::cout << ",\"warnings\":[";
        for (std::size_t index = 0; index < prepared.frontend_warnings.size(); ++index) {
            if (index != 0) {
                std::cout << ',';
            }
            const auto& warning = prepared.frontend_warnings[index];
            std::cout << "{\"code\":";
            write_string(std::cout, warning.code);
            std::cout << ",\"offset\":" << warning.offset
                      << ",\"length\":" << warning.length << '}';
        }
        std::cout << "]}";
    }
    std::cout << "\n]}\n";
    return EXIT_SUCCESS;
}

} // namespace

int main(int argc, char** argv) {
    if (argc != 1 && (argc != 2 || std::string_view(argv[1]) != "--stdout")) {
        std::cerr << "usage: tts_front_effective_text_corpus [--stdout]\n";
        return EXIT_FAILURE;
    }
    return emit_corpus();
}
