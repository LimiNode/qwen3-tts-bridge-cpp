#include <qwen_tts_bridge/text.hpp>

#include <cstdlib>
#include <iostream>
#include <string>
#include <string_view>

namespace {

using namespace qwen_tts_bridge;

struct CorpusCase {
    const char* id;
    const char* text;
    tts_front::Language language;
    TextRenderCapability render;
    bool dictionary;
    tts_front::MixedLanguagePolicy mixed_policy;
};

constexpr CorpusCase kCorpus[] = {
    {"ru_leading_zero_year", "В 0026 году", tts_front::Language::Russian,
     TextRenderCapability::Base, false, tts_front::MixedLanguagePolicy::DominantLanguage},
    {"ru_numbers", "В 2026 году 2 книги и 5 домов.", tts_front::Language::Russian,
     TextRenderCapability::Base, false, tts_front::MixedLanguagePolicy::DominantLanguage},
    {"ru_agreement", "У 21-го клиента 3 новых договора.", tts_front::Language::Russian,
     TextRenderCapability::Base, false, tts_front::MixedLanguagePolicy::DominantLanguage},
    {"ru_supported_decimal", "В отчёте 1,5 метра.", tts_front::Language::Russian,
     TextRenderCapability::Base, false, tts_front::MixedLanguagePolicy::DominantLanguage},
    {"ru_stress_homographs", "замок мука горе", tts_front::Language::Russian,
     TextRenderCapability::ExplicitCombiningStress, true, tts_front::MixedLanguagePolicy::DominantLanguage},
    {"ru_date_time", "В 2026 г. встреча в 14:30.", tts_front::Language::Russian,
     TextRenderCapability::Base, false, tts_front::MixedLanguagePolicy::DominantLanguage},
    {"ru_currency", "Цена: 1 234,50 ₽ и 50 евро.", tts_front::Language::Russian,
     TextRenderCapability::Base, false, tts_front::MixedLanguagePolicy::DominantLanguage},
    {"ru_abbreviations", "API, RTX 4090 и CUDA 13.3 готовы.", tts_front::Language::Russian,
     TextRenderCapability::Base, false, tts_front::MixedLanguagePolicy::DominantLanguage},
    {"ru_genitive_decimal", "После 1,5 попыток и 2,25 часа.", tts_front::Language::Russian,
     TextRenderCapability::Base, false, tts_front::MixedLanguagePolicy::DominantLanguage},
    {"ru_numeric_boundaries", "21-й, 3.14, 1,5%, 1 000 000 и 999999.", tts_front::Language::Russian,
     TextRenderCapability::Base, false, tts_front::MixedLanguagePolicy::DominantLanguage},
    {"mixed_technical", "Сегодня API v2.3 работает через HTTP/2.", tts_front::Language::Auto,
     TextRenderCapability::Base, false, tts_front::MixedLanguagePolicy::DominantLanguage},
    {"mixed_segment_candidates", "Цена $12.50 и 3 кг; API v2.3.", tts_front::Language::Auto,
     TextRenderCapability::Base, false, tts_front::MixedLanguagePolicy::SegmentCandidates},
    {"en_controls", "Build 42 uses CUDA 13.3 on 2026-10-24.", tts_front::Language::English,
     TextRenderCapability::Base, false, tts_front::MixedLanguagePolicy::DominantLanguage},
    {"currency_boundaries", "$ 1,234.50; €-2.00; £ 3.5; ¥+4,50.", tts_front::Language::English,
     TextRenderCapability::Base, false, tts_front::MixedLanguagePolicy::DominantLanguage},
    {"technical_protected", "https://example.com/$1,234%25 RTX-4090/123 C++17,234%25",
     tts_front::Language::English, TextRenderCapability::Base, false,
     tts_front::MixedLanguagePolicy::DominantLanguage},
    {"ru_plain_control", "Простая фраза без чисел.", tts_front::Language::Russian,
     TextRenderCapability::Base, false, tts_front::MixedLanguagePolicy::DominantLanguage},
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
            } else {
                escaped.push_back(static_cast<char>(byte));
            }
        }
    }
    return escaped;
}

void write_string(std::ostream& output, std::string_view value) {
    output << '"' << json_escape(value) << '"';
}

int emit_corpus() {
    std::cout << "{\"schema\":1,\"cases\":[\n";
    bool first = true;
    for (const auto& corpus_case : kCorpus) {
        tts_front::PronunciationDictionary dictionary;
        if (corpus_case.dictionary) {
            if (!dictionary.add_token("замок", "замок", 0) ||
                !dictionary.add_token("мука", "мука", 1) ||
                !dictionary.add_token("горе", "горе", 0)) {
                return EXIT_FAILURE;
            }
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
        if (!preparer.prepare(request, prepared, error) || !error.code.empty()) {
            std::cerr << "prepare failed for " << corpus_case.id << ": " << error.code << '\n';
            return EXIT_FAILURE;
        }

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
        std::cout << ",\"effective_text\":";
        write_string(std::cout, prepared.effective_text);
        std::cout << ",\"normalized_text\":";
        write_string(std::cout, prepared.frontend_normalized_text);
        std::cout << ",\"pronunciation_text\":";
        write_string(std::cout, prepared.frontend_pronunciation_text);
        std::cout << ",\"warning_count\":" << prepared.frontend_warnings.size();
        std::cout << ",\"uncertain\":" << (prepared.frontend_has_uncertainty ? "true" : "false");
        std::cout << ",\"warnings\":[";
        for (std::size_t index = 0; index < prepared.frontend_warnings.size(); ++index) {
            if (index != 0) std::cout << ',';
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
