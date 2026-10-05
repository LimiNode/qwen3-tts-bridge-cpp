#pragma once

/// \file TtsFrontTextPreparer.hpp
/// \brief Adapter from the released tts-front-cpp frontend to PreparedText.

#include <tts_front.hpp>

#include <string>

#include "../client/client_types.hpp"

namespace qwen_tts_bridge {

/// \brief Model-facing rendering capability selected by an application.
enum class TextRenderCapability {
    Base,
    ExplicitCombiningStress,
};

/// \brief Configuration for the tts-front-cpp bridge adapter.
struct TtsFrontTextPreparerOptions {
    tts_front::TextFrontendOptions frontend;
    TextRenderCapability render_capability = TextRenderCapability::Base;
};

/// \brief Runs tts-front-cpp once and renders its result for a Qwen capability.
///
/// The frontend remains model-agnostic. Combining U+0301 is emitted only when
/// `ExplicitCombiningStress` is selected by the caller for a model contract
/// that documents this representation. The adapter is safe to reuse from
/// concurrent request-preparation calls when the configured dictionary remains
/// alive and is not mutated.
class TtsFrontTextPreparer final {
public:
    explicit TtsFrontTextPreparer(TtsFrontTextPreparerOptions options = {});

    bool prepare(
        const TtsRequest& request,
        PreparedText& prepared,
        TtsError& error) const;

private:
    TtsFrontTextPreparerOptions options_;
    tts_front::TextFrontend frontend_;
};

} // namespace qwen_tts_bridge
