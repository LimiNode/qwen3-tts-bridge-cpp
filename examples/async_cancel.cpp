/// Demonstrates request-ID cancellation while the worker remains alive.
#include <qwen_tts_bridge/client.hpp>

#include <chrono>
#include <iostream>
#include <string>
#include <thread>
#include <vector>

int main(int argc, char** argv) {
    if (argc < 2) {
        std::cerr << "usage: async_cancel <worker-executable> [--worker-arg <arg>]...\n";
        return 2;
    }
    std::vector<std::string> worker_arguments;
    for (int index = 2; index < argc; ++index) {
        const std::string argument = argv[index];
        if (argument == "--worker-arg" && index + 1 < argc) {
            worker_arguments.emplace_back(argv[++index]);
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
