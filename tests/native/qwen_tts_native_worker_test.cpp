#include <qwen_tts_bridge/client.hpp>

#include <chrono>
#include <condition_variable>
#include <cstdlib>
#include <filesystem>
#include <iostream>
#include <mutex>
#include <string>
#include <vector>

#define CHECK(expr) do { \
    if (!(expr)) { \
        std::cerr << "CHECK failed: " #expr << " at " << __FILE__ << ':' << __LINE__ << '\n'; \
        return EXIT_FAILURE; \
    } \
} while (false)

namespace {
using namespace qwen_tts_bridge;

struct Probe {
    std::mutex mutex;
    std::condition_variable condition;
    std::vector<std::byte> audio;
    std::size_t completed = 0;
    std::size_t cancelled = 0;
    std::vector<TtsError> errors;
};

StdIoTransportOptions options() {
    const std::filesystem::path runtime = QWEN_TTS_FAKE_RUNTIME_DIR;
    StdIoTransportOptions result;
    result.arguments = {
        QWEN_TTS_NATIVE_WORKER_EXE,
        "--runtime-dir", runtime.string(),
        "--talker-model", (runtime / "talker.gguf").string(),
        "--codec-model", (runtime / "codec.gguf").string()
    };
    result.stderr_handler = [](std::string message) {
        std::cerr << "[native-worker-stderr] " << message << '\n';
    };
    return result;
}

StdIoTransportOptions missing_dll_options() {
    const auto runtime = std::filesystem::path(QWEN_TTS_FAKE_RUNTIME_DIR);
    StdIoTransportOptions result = options();
    result.arguments = {
        QWEN_TTS_NATIVE_WORKER_EXE,
        "--dll-path", (runtime / "missing-qwen.dll").string(),
        "--manifest-path", (runtime / "manifest.json").string(),
        "--talker-model", (runtime / "talker.gguf").string(),
        "--codec-model", (runtime / "codec.gguf").string()
    };
    return result;
}
}

int main() {
    QwenTtsClient invalid_client;
    QwenTtsClientOptions invalid_options;
    invalid_options.session.startup_timeout = std::chrono::seconds(2);
    CHECK(!invalid_client.start(missing_dll_options(), invalid_options));

    QwenTtsClient client;
    QwenTtsClientOptions client_options;
    client_options.session.startup_timeout = std::chrono::seconds(5);
    CHECK(client.start(options(), client_options));

    ReadyMessage ready;
    CHECK(client.ready_message(ready));
    CHECK(ready.capabilities.streaming);
    CHECK(ready.capabilities.cancellation);

    Probe probe;
    TtsCallbacks callbacks;
    callbacks.on_audio = [&probe](const PcmChunk& chunk) {
        std::lock_guard<std::mutex> lock(probe.mutex);
        probe.audio.insert(probe.audio.end(), chunk.bytes.begin(), chunk.bytes.end());
    };
    callbacks.on_completed = [&probe]() {
        std::lock_guard<std::mutex> lock(probe.mutex);
        ++probe.completed;
        probe.condition.notify_all();
    };
    callbacks.on_cancelled = [&probe]() {
        std::lock_guard<std::mutex> lock(probe.mutex);
        ++probe.cancelled;
        probe.condition.notify_all();
    };
    callbacks.on_error = [&probe](const TtsError& error) {
        std::lock_guard<std::mutex> lock(probe.mutex);
        probe.errors.push_back(error);
        probe.condition.notify_all();
    };

    const RequestId id = client.synthesize_async("native worker test", callbacks);
    CHECK(id != 0);
    {
        std::unique_lock<std::mutex> lock(probe.mutex);
        CHECK(probe.condition.wait_for(lock, std::chrono::seconds(5), [&probe]() {
            return probe.completed != 0 || !probe.errors.empty();
        }));
    }
    CHECK(probe.errors.empty());
    CHECK(probe.completed == 1);
    CHECK(probe.audio.size() == 16);
    CHECK(static_cast<unsigned char>(probe.audio[0]) == 0x00u);
    CHECK(static_cast<unsigned char>(probe.audio[1]) == 0x80u);
    CHECK(static_cast<unsigned char>(probe.audio[10]) == 0xffu);
    CHECK(static_cast<unsigned char>(probe.audio[11]) == 0x7fu);

    client.stop();
    return EXIT_SUCCESS;
}
