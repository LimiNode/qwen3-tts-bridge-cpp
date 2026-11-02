#include <qwen_tts_bridge/audio.hpp>
#include <qwen_tts_bridge/client.hpp>
#include <qwen_tts_bridge/data.hpp>
#include <qwen_tts_bridge/playback.hpp>
#include <qwen_tts_bridge/protocol/control.hpp>
#include <qwen_tts_bridge/protocol/framing.hpp>
#include <qwen_tts_bridge/session.hpp>
#include <qwen_tts_bridge/transport.hpp>
#ifdef QWEN_TTS_BRIDGE_INSTALL_CONSUMER_USE_WINMM
#include <qwen_tts_bridge/playback/winmm_playback.hpp>
#endif
#ifdef QWEN_TTS_BRIDGE_INSTALL_CONSUMER_USE_TTS_FRONT
#include <qwen_tts_bridge/text.hpp>
#endif

int main() {
    qwen_tts_bridge::TtsRequest request;
    request.text = "consumer smoke";
#ifdef QWEN_TTS_BRIDGE_INSTALL_CONSUMER_USE_TTS_FRONT
    qwen_tts_bridge::TtsFrontTextPreparer preparer;
    qwen_tts_bridge::PreparedText prepared;
    qwen_tts_bridge::TtsError error;
    if (!preparer.prepare(request, prepared, error)) {
        return 1;
    }
#endif
#ifdef QWEN_TTS_BRIDGE_INSTALL_CONSUMER_USE_WINMM
    qwen_tts_bridge::playback::WaveOutPlayer player(
        qwen_tts_bridge::playback::PlaybackSinkMode::Disabled);
#endif
    return request.text.empty() ? 1 : 0;
}
