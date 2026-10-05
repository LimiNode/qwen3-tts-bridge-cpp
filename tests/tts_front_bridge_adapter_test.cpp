#include <qwen_tts_bridge/text.hpp>

#include <cstdlib>
#include <iostream>
#include <string>

#define CHECK(expr)                                                            \
    do {                                                                       \
        if (!(expr)) {                                                         \
            std::cerr << "CHECK failed: " #expr << " at " << __FILE__ << ':'  \
                      << __LINE__ << '\n';                                    \
            std::exit(EXIT_FAILURE);                                           \
        }                                                                      \
    } while (false)

namespace {

using namespace qwen_tts_bridge;

std::string russian_source() {
    return "\xD0\xB7\xD0\xB0\xD0\xBC\xD0\xBE\xD0\xBA"; // замок
}

void test_base_renderer_preserves_model_neutral_text() {
    tts_front::PronunciationDictionary dictionary;
    CHECK(dictionary.add_token(russian_source(), russian_source(), 1));

    TtsFrontTextPreparerOptions options;
    options.frontend.language = tts_front::Language::Russian;
    options.frontend.dictionary = &dictionary;
    options.render_capability = TextRenderCapability::Base;
    TtsFrontTextPreparer preparer(options);

    TtsRequest request;
    request.text = russian_source();
    PreparedText prepared;
    TtsError error;
    CHECK(preparer.prepare(request, prepared, error));
    CHECK(error.code.empty());
    CHECK(prepared.original_text == russian_source());
    CHECK(prepared.effective_text == russian_source());
    CHECK(prepared.effective_text.find("\xCC\x81") == std::string::npos);
    CHECK(prepared.frontend_stress_decisions.size() == 1);
    CHECK(prepared.frontend_stress_decisions.front().stressed_vowel == 1);
}

void test_explicit_stress_renderer_uses_frontend_decision() {
    tts_front::PronunciationDictionary dictionary;
    CHECK(dictionary.add_token(russian_source(), russian_source(), 1));

    TtsFrontTextPreparerOptions options;
    options.frontend.language = tts_front::Language::Russian;
    options.frontend.dictionary = &dictionary;
    options.render_capability = TextRenderCapability::ExplicitCombiningStress;
    TtsFrontTextPreparer preparer(options);

    TtsRequest request;
    request.text = russian_source();
    PreparedText prepared;
    TtsError error;
    CHECK(preparer.prepare(request, prepared, error));
    CHECK(error.code.empty());
    CHECK(prepared.effective_text.find("\xCC\x81") != std::string::npos);
    CHECK(prepared.frontend_normalized_text == russian_source());
    CHECK(prepared.frontend_pronunciation_text == russian_source());
}

void test_frontend_warning_is_preserved() {
    TtsFrontTextPreparerOptions options;
    options.frontend.language = tts_front::Language::Auto;
    TtsFrontTextPreparer preparer(options);

    TtsRequest request;
    request.text = "\xD0\xA2\xD0\xB5\xD1\x81\xD1\x82 API"; // Тест API
    PreparedText prepared;
    TtsError error;
    CHECK(preparer.prepare(request, prepared, error));
    CHECK(error.code.empty());
    CHECK(prepared.frontend_warnings.size() == 1);
    CHECK(prepared.frontend_warnings.front().code == "ambiguous_normalization");
    CHECK(prepared.frontend_has_uncertainty);
}

} // namespace

int main() {
    test_base_renderer_preserves_model_neutral_text();
    test_explicit_stress_renderer_uses_frontend_decision();
    test_frontend_warning_is_preserved();
    return 0;
}
