#include "../examples/qwen_tts_play_completion_policy.hpp"

#include <iostream>

int main() {
    qwen_tts_bridge::TtsCompletion natural;
    natural.has_generation_trace = true;
    natural.termination_reason = "eos";
    natural.hit_eos = true;
    if (!qwen_tts_examples::playback::completion_has_natural_eos(natural)) {
        std::cerr << "natural EOS was rejected\n";
        return 1;
    }

    for (const auto& reason : {"max_seq_len", "max_new_tokens", ""}) {
        qwen_tts_bridge::TtsCompletion non_natural = natural;
        non_natural.termination_reason = reason;
        non_natural.hit_eos = false;
        if (qwen_tts_examples::playback::completion_has_natural_eos(non_natural)) {
            std::cerr << "non-natural completion was accepted\n";
            return 1;
        }
    }

    qwen_tts_bridge::TtsCompletion missing_trace = natural;
    missing_trace.has_generation_trace = false;
    if (qwen_tts_examples::playback::completion_has_natural_eos(missing_trace)) {
        std::cerr << "missing trace was accepted\n";
        return 1;
    }

    if (qwen_tts_examples::playback::completion_has_natural_eos(std::nullopt)) {
        std::cerr << "missing completion metadata was accepted\n";
        return 1;
    }

    qwen_tts_bridge::TtsCompletion contradictory = natural;
    contradictory.hit_max_new_tokens = true;
    if (qwen_tts_examples::playback::completion_has_natural_eos(contradictory)) {
        std::cerr << "contradictory completion was accepted\n";
        return 1;
    }


    contradictory = natural;
    contradictory.hit_max_seq_len = true;
    if (qwen_tts_examples::playback::completion_has_natural_eos(contradictory)) {
        std::cerr << "contradictory sequence-limit completion was accepted\n";
        return 1;
    }
    return 0;
}
