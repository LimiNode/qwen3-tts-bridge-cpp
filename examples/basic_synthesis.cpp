/// Minimal asynchronous synthesis example.
#include <qwen_tts_bridge/client.hpp>

#include <condition_variable>
#include <iostream>
#include <mutex>
#include <string>
#include <utility>
#include <vector>

int main(int argc, char** argv) {
    if (argc < 2) {
        std::cerr << "usage: basic_synthesis <worker-executable> [--worker-arg <arg>]... [--text <text>]\n";
        return 2;
    }

    std::string text = "Hello from QwenTTSBridge.";
    std::vector<std::string> worker_arguments;
    for (int index = 2; index < argc; ++index) {
        const std::string argument = argv[index];
        if (argument == "--worker-arg" && index + 1 < argc) {
            worker_arguments.emplace_back(argv[++index]);
        }
        else if (argument == "--text" && index + 1 < argc) {
            text = argv[++index];
        }
        else {
            std::cerr << "unknown or incomplete option: " << argument << "\n";
            return 2;
        }
    }

    qwen_tts_bridge::QwenTtsClient client;
    qwen_tts_bridge::StdIoTransportOptions transport;
    transport.arguments.emplace_back(argv[1]);
    transport.arguments.insert(
        transport.arguments.end(), worker_arguments.begin(), worker_arguments.end());
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
    request.text = std::move(text);
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
