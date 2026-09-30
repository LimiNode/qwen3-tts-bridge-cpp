#include <qwen_tts_bridge/client.hpp>

int main() {
    qwen_tts_bridge::TtsRequest request;
    request.text = "consumer smoke";
    return request.text.empty() ? 1 : 0;
}
