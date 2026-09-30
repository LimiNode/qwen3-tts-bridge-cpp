/// Demonstrates the backend-neutral streaming audio post-processing seam.
#include <qwen_tts_bridge/audio.hpp>

#include <iostream>
#include <memory>

int main() {
    auto chain = std::make_shared<qwen_tts_bridge::audio::AudioPostProcessorChain>();
    qwen_tts_bridge::audio::TerminalFadeOptions options;
    options.fade_ms = 15;
    options.completion_silence_ms = 85;
    options.cancellation_silence_ms = 0;
    chain->add(std::make_unique<qwen_tts_bridge::audio::TerminalFadePostProcessor>(options));

    qwen_tts_bridge::TtsCallbacks downstream;
    downstream.on_audio = [](const qwen_tts_bridge::PcmChunk& chunk) {
        std::cout << "post-processed PCM: " << chunk.bytes.size() << " bytes\n";
    };
    const auto callbacks = qwen_tts_bridge::audio::with_audio_post_processing(
        chain, std::move(downstream));
    std::cout << "Install these callbacks for a request; post-processing remains "
                 "streaming and backend-independent.\n";
    (void)callbacks;
    return 0;
}
