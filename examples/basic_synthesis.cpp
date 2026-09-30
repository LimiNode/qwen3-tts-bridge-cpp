/// Minimal asynchronous synthesis example.
#include <qwen_tts_bridge/client.hpp>

#include <condition_variable>
#include <iostream>
#include <mutex>
#include <string>

int main(int argc, char** argv) {
    if (argc < 2) {
        std::cerr << "usage: basic_synthesis <worker-executable> [text]\n";
        return 2;
    }

    qwen_tts_bridge::QwenTtsClient client;
    qwen_tts_bridge::StdIoTransportOptions transport;
    transport.arguments.emplace_back(argv[1]);
    qwen_tts_bridge::QwenTtsClientOptions options;
    if (!client.start(transport, options)) {
        std::cerr << "worker did not become ready\n";
        return 1;
    }

    std::mutex mutex;
    std::condition_variable condition;
    bool terminal = false;
    bool failed = false;
    qwen_tts_bridge::TtsRequest request;
    request.text = argc >= 3 ? argv[2] : "Hello from QwenTTSBridge.";
    qwen_tts_bridge::TtsCallbacks callbacks;
    callbacks.on_audio = [](const qwen_tts_bridge::PcmChunk& chunk) {
        std::cout << "PCM chunk: " << chunk.bytes.size() << " bytes\n";
    };
    callbacks.on_completed = [&] {
        std::lock_guard<std::mutex> lock(mutex);
        terminal = true;
        condition.notify_one();
    };
    callbacks.on_error = [&](const qwen_tts_bridge::TtsError& error) {
        std::cerr << error.category << "/" << error.code << ": " << error.message << "\n";
        std::lock_guard<std::mutex> lock(mutex);
        failed = true;
        terminal = true;
        condition.notify_one();
    };
    if (client.synthesize_async(std::move(request), std::move(callbacks)) == 0) {
        client.stop();
        return 1;
    }
    std::unique_lock<std::mutex> lock(mutex);
    condition.wait(lock, [&] { return terminal; });
    lock.unlock();
    client.stop();
    return failed ? 1 : 0;
}
