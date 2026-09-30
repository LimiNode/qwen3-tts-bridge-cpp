/// Demonstrates request-ID cancellation while the worker remains alive.
#include <qwen_tts_bridge/client.hpp>

#include <chrono>
#include <iostream>
#include <thread>

int main(int argc, char** argv) {
    if (argc < 2) {
        std::cerr << "usage: async_cancel <worker-executable>\n";
        return 2;
    }
    qwen_tts_bridge::QwenTtsClient client;
    qwen_tts_bridge::StdIoTransportOptions transport;
    transport.arguments.emplace_back(argv[1]);
    if (!client.start(transport)) {
        return 1;
    }
    qwen_tts_bridge::TtsCallbacks callbacks;
    callbacks.on_audio = [](const qwen_tts_bridge::PcmChunk&) {};
    callbacks.on_cancelled = [] { std::cout << "request cancelled\n"; };
    callbacks.on_completed = [] { std::cout << "request completed\n"; };
    callbacks.on_error = [](const qwen_tts_bridge::TtsError& error) {
        std::cerr << error.code << ": " << error.message << "\n";
    };
    qwen_tts_bridge::TtsRequest request;
    request.text = "This request is intentionally cancelled.";
    const auto request_id = client.synthesize_async(std::move(request), std::move(callbacks));
    if (request_id == 0) {
        client.stop();
        return 1;
    }
    std::this_thread::sleep_for(std::chrono::milliseconds(100));
    if (!client.cancel(request_id)) {
        std::cerr << "cancel was not accepted\n";
        client.stop();
        return 1;
    }
    std::this_thread::sleep_for(std::chrono::milliseconds(100));
    client.stop();
    return 0;
}
