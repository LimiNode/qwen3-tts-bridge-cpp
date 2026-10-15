#include <qwen_tts_bridge/client.hpp>
#ifdef QWEN_TTS_BRIDGE_INSTALL_CONSUMER_USE_WINMM
#include <qwen_tts_bridge/playback/winmm_playback.hpp>
#endif

int main() {
    qwen_tts_bridge::TtsRequest request;
    request.text = "consumer smoke";
#ifdef QWEN_TTS_BRIDGE_INSTALL_CONSUMER_USE_WINMM
    qwen_tts_bridge::playback::WaveOutPlayer player(
        qwen_tts_bridge::playback::PlaybackSinkMode::Disabled);
#endif
    return request.text.empty() ? 1 : 0;
}
