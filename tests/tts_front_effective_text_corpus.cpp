#include <qwen_tts_bridge/text.hpp>

#include <cstdlib>
#include <fstream>
#include <iostream>
#include <string>
#include <string_view>
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

struct CorpusCase {
    const char* id;
    const char* text;
    tts_front::Language language;
    TextRenderCapability render;
    bool dictionary;
    tts_front::MixedLanguagePolicy mixed_policy;
    const char* expected_effective_text;
    std::size_t expected_warning_count;
    bool expected_uncertainty;
};

constexpr CorpusCase kCorpus[] = {
    {"ru_stress_homographs", "замок мука горе", tts_front::Language::Russian,
     TextRenderCapability::ExplicitCombiningStress, true, tts_front::MixedLanguagePolicy::DominantLanguage,
     "за\xCC\x81мок мука\xCC\x81 го\xCC\x81ре", 0, false},
    {"ru_numbers", "В 2026 году 2 книги и 5 домов.",
     tts_front::Language::Russian, TextRenderCapability::Base, false, tts_front::MixedLanguagePolicy::DominantLanguage,
     "В две тысячи двадцать шесть году два книги и пять домов.", 0, false},
    {"ru_currency", "Цена: 1 234,50 ₽ и 50 евро.",
     tts_front::Language::Russian, TextRenderCapability::Base, false, tts_front::MixedLanguagePolicy::DominantLanguage,
     "Цена: 1 234,50 ₽ и пятьдесят евро.", 1, true},
    {"ru_agreement", "У 21-го клиента 3 новых договора.",
     tts_front::Language::Russian, TextRenderCapability::Base, false, tts_front::MixedLanguagePolicy::DominantLanguage,
     "У 21-го клиента три новых договора.", 1, true},
    {"ru_abbreviations", "API, RTX 4090 и CUDA 13.3 готовы.",
     tts_front::Language::Russian, TextRenderCapability::Base, false, tts_front::MixedLanguagePolicy::DominantLanguage,
     "API, RTX 4090 и CUDA 13.3 готовы.", 0, false},
    {"ru_date_time", "В 2026 г. встреча в 14:30.",
     tts_front::Language::Russian, TextRenderCapability::Base, false, tts_front::MixedLanguagePolicy::DominantLanguage,
     "В две тысячи двадцать шестом году встреча в четырнадцать часов тридцать минут.", 0, false},
    {"mixed_technical", "Сегодня API v2.3 работает через HTTP/2.",
     tts_front::Language::Auto, TextRenderCapability::Base, false, tts_front::MixedLanguagePolicy::DominantLanguage,
     "Сегодня API v2.3 работает через HTTP/2.", 1, true},
    {"en_controls", "Build 42 uses CUDA 13.3 on 2026-10-24.",
     tts_front::Language::English, TextRenderCapability::Base, false, tts_front::MixedLanguagePolicy::DominantLanguage,
     "Build forty two uses CUDA 13.3 on 2026-10-24.", 1, true},
    {"unchanged_plain", "Простая фраза без чисел.",
     tts_front::Language::Russian, TextRenderCapability::Base, false, tts_front::MixedLanguagePolicy::DominantLanguage,
     "Простая фраза без чисел.", 0, false},
    {"currency_prefixes", "$ 1,234.50; €-2.00; £ 3.5; ¥+4,50.",
     tts_front::Language::English, TextRenderCapability::Base, false, tts_front::MixedLanguagePolicy::DominantLanguage,
     "$ 1,234.50; €-2.00; £ 3.5; ¥+4,50.", 4, true},
    {"currency_continuations", "$1,23% 456 and €1,234/567.",
     tts_front::Language::English, TextRenderCapability::Base, false, tts_front::MixedLanguagePolicy::DominantLanguage,
     "$1,23% 456 and €1,234/five hundred sixty seven.", 2, true},
    {"technical_protected", "https://example.com/$1,234%25 RTX-4090/123 C++17,234%25",
     tts_front::Language::English, TextRenderCapability::Base, false, tts_front::MixedLanguagePolicy::DominantLanguage,
     "https://example.com/$1,234%25 RTX-4090/123 C++17,234%25", 3, true},
    {"mixed_segment_candidates", "Цена $12.50 и 3 кг; API v2.3.",
     tts_front::Language::Auto, TextRenderCapability::Base, false, tts_front::MixedLanguagePolicy::SegmentCandidates,
     "Цена twelve dollars fifty cents и три килограмма; API v2.3.", 1, true},
    {"ru_supported_decimal", "В отчёте 1,5 метра.",
     tts_front::Language::Russian, TextRenderCapability::Base, false, tts_front::MixedLanguagePolicy::DominantLanguage,
     "В отчёте одна целая пять десятых метра.", 0, false},
    {"ru_genitive_decimal", "После 1,5 попыток и 2,25 часа.",
     tts_front::Language::Russian, TextRenderCapability::Base, false, tts_front::MixedLanguagePolicy::DominantLanguage,
     "После 1,5 попыток и две целых двадцать пять сотых часа.", 1, true},
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
                escaped += "\\u00";
                constexpr char hex[] = "0123456789abcdef";
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

int write_corpus(std::ostream& output, bool enforce_v023_oracle) {
    output << "{\"schema\":1,\"cases\":[\n";
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
        if (enforce_v023_oracle) {
            CHECK(prepared.effective_text == corpus_case.expected_effective_text);
            CHECK(prepared.frontend_warnings.size() == corpus_case.expected_warning_count);
            CHECK(prepared.frontend_has_uncertainty == corpus_case.expected_uncertainty);
        }

        if (enforce_v023_oracle && std::string_view(corpus_case.id) == "ru_genitive_decimal") {
            CHECK(prepared.frontend_warnings.size() == 1);
            const auto& warning = prepared.frontend_warnings.front();
            const auto expected_offset = request.text.find("1,5");
            CHECK(warning.code == "unresolved_number");
            CHECK(warning.offset == expected_offset);
            CHECK(warning.length == std::string_view("1,5").size());
        }

        if (!first) {
            output << ",\n";
        }
        first = false;
        output << "  {\"id\":";
        write_string(output, corpus_case.id);
        output << ",\"input\":";
        write_string(output, request.text);
        output << ",\"language\":";
        write_string(output, tts_front::to_string(corpus_case.language));
        output << ",\"render\":";
        write_string(output, corpus_case.render == TextRenderCapability::Base
            ? "base" : "explicit_combining_stress");
        output << ",\"normalized_text\":";
        write_string(output, prepared.frontend_normalized_text);
        output << ",\"pronunciation_text\":";
        write_string(output, prepared.frontend_pronunciation_text);
        output << ",\"effective_text\":";
        write_string(output, prepared.effective_text);
        output << ",\"warning_count\":" << prepared.frontend_warnings.size();
        output << ",\"uncertain\":" << (prepared.frontend_has_uncertainty ? "true" : "false");
        output << ",\"warnings\":[";
        for (std::size_t index = 0; index < prepared.frontend_warnings.size(); ++index) {
            if (index != 0) {
                output << ',';
            }
            const auto& warning = prepared.frontend_warnings[index];
            output << "{\"code\":";
            write_string(output, warning.code);
            output << ",\"offset\":" << warning.offset;
            output << ",\"length\":" << warning.length << '}';
        }
        output << "]";
        output << "}";
    }
    output << "\n]}\n";
    return EXIT_SUCCESS;
}

} // namespace

int main(int argc, char** argv) {
    bool emit_only = false;
    for (int index = 1; index < argc; ++index) {
        const auto argument = std::string_view(argv[index]);
        if (argument == "--emit-only") {
            emit_only = true;
        }
        else if (argument != "--stdout") {
            std::cerr << "usage: tts_front_effective_text_corpus [--stdout] [--emit-only]\n";
            return EXIT_FAILURE;
        }
    }
    if (argc > 3) {
        std::cerr << "usage: tts_front_effective_text_corpus [--stdout] [--emit-only]\n";
        return EXIT_FAILURE;
    }
    return write_corpus(std::cout, !emit_only);
}
