#include <qwen_tts_bridge/client.hpp>

#include <chrono>
#include <atomic>
#include <condition_variable>
#include <cstdlib>
#include <filesystem>
#include <iostream>
#include <mutex>
#include <string>
#include <fstream>
#include <iterator>
#include <thread>
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
    std::vector<TtsCompletion> completions;
};

StdIoTransportOptions options(
    int stream_max_chunk_frames = 8,
    std::string* stderr_capture = nullptr,
    std::atomic<bool>* cadence_observed = nullptr,
    int max_text_bytes = 0) {
    const std::filesystem::path runtime = QWEN_TTS_FAKE_RUNTIME_DIR;
    StdIoTransportOptions result;
    result.arguments = {
        QWEN_TTS_NATIVE_WORKER_EXE,
        "--runtime-dir", runtime.string(),
        "--stream-max-chunk-frames", std::to_string(stream_max_chunk_frames),
        "--talker-model", (runtime / "talker.gguf").string(),
        "--codec-model", (runtime / "codec.gguf").string()
    };
    if (max_text_bytes > 0) {
        result.arguments.push_back("--max-text-bytes");
        result.arguments.push_back(std::to_string(max_text_bytes));
    }
    result.stderr_handler = [stderr_capture, cadence_observed](std::string message) {
        if (stderr_capture != nullptr) {
            *stderr_capture += message;
        }
        if (cadence_observed != nullptr &&
            message.find("stream_max_chunk_frames=4") != std::string::npos) {
            cadence_observed->store(true, std::memory_order_release);
        }
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

StdIoTransportOptions manifest_options(
    const std::filesystem::path& manifest,
    std::string* stderr_capture = nullptr,
    std::atomic<bool>* mismatch_observed = nullptr) {
    auto result = options();
    if (stderr_capture != nullptr) {
        result.stderr_handler = [stderr_capture](std::string message) {
            *stderr_capture += message;
        };
        if (mismatch_observed != nullptr) {
            result.stderr_handler = [stderr_capture, mismatch_observed](std::string message) {
                if (stderr_capture != nullptr) {
                    *stderr_capture += message;
                }
                if (message.find("engine commit does not match") != std::string::npos) {
                    mismatch_observed->store(true, std::memory_order_release);
                }
            };
        }
    }
    result.arguments = {
        QWEN_TTS_NATIVE_WORKER_EXE,
        "--runtime-dir", manifest.parent_path().string(),
        "--manifest-path", manifest.string(),
        "--talker-model", (manifest.parent_path() / "talker.gguf").string(),
        "--codec-model", (manifest.parent_path() / "codec.gguf").string()
    };
    return result;
}
}

int main() {
    const auto runtime = std::filesystem::path(QWEN_TTS_FAKE_RUNTIME_DIR);
    const auto mismatch_manifest = runtime / "manifest-mismatch.json";
    {
        std::ifstream input(runtime / "manifest.json", std::ios::binary);
        std::string text((std::istreambuf_iterator<char>(input)), {});
        const auto marker = text.find("fake-qwentts-test");
        CHECK(marker != std::string::npos);
        text.replace(marker, std::string("fake-qwentts-test").size(), "wrong-commit");
        std::ofstream output(mismatch_manifest, std::ios::binary);
        output << text;
    }
    QwenTtsClient mismatched_client;
    QwenTtsClientOptions mismatched_options;
    mismatched_options.session.startup_timeout = std::chrono::seconds(2);
    std::string mismatch_stderr;
    std::atomic<bool> mismatch_observed{false};
    CHECK(!mismatched_client.start(
        manifest_options(mismatch_manifest, &mismatch_stderr, &mismatch_observed), mismatched_options));
    for (int attempt = 0; attempt < 20 &&
         !mismatch_observed.load(std::memory_order_acquire); ++attempt) {
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }
    CHECK(mismatch_observed.load(std::memory_order_acquire));

    QwenTtsClient invalid_client;
    QwenTtsClientOptions invalid_options;
    invalid_options.session.startup_timeout = std::chrono::seconds(2);
    CHECK(!invalid_client.start(missing_dll_options(), invalid_options));

    QwenTtsClient client;
    QwenTtsClientOptions client_options;
    client_options.session.startup_timeout = std::chrono::seconds(5);
    std::atomic<bool> cadence_observed{false};
    CHECK(client.start(options(4, nullptr, &cadence_observed), client_options));
    for (int attempt = 0; attempt < 20 &&
         !cadence_observed.load(std::memory_order_acquire); ++attempt) {
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }
    CHECK(cadence_observed.load(std::memory_order_acquire));

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
    callbacks.on_completion_metadata = [&probe](const TtsCompletion& completion) {
        std::lock_guard<std::mutex> lock(probe.mutex);
        probe.completions.push_back(completion);
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
    CHECK(probe.completions.size() == 1);
    CHECK(probe.completions.front().execution_outcome == "natural_eos");
    CHECK(probe.audio.size() == 16);
    CHECK(static_cast<unsigned char>(probe.audio[0]) == 0x00u);
    CHECK(static_cast<unsigned char>(probe.audio[1]) == 0x80u);
    CHECK(static_cast<unsigned char>(probe.audio[10]) == 0xffu);
    CHECK(static_cast<unsigned char>(probe.audio[11]) == 0x7fu);

    QwenTtsClient limited_client;
    QwenTtsClientOptions limited_options;
    limited_options.session.startup_timeout = std::chrono::seconds(5);
    CHECK(limited_client.start(options(8, nullptr, nullptr, 4), limited_options));
    Probe limited_probe;
    TtsCallbacks limited_callbacks;
    limited_callbacks.on_error = [&limited_probe](const TtsError& error) {
        std::lock_guard<std::mutex> lock(limited_probe.mutex);
        limited_probe.errors.push_back(error);
        limited_probe.condition.notify_all();
    };
    CHECK(limited_client.synthesize_async("native worker request", limited_callbacks) != 0);
    {
        std::unique_lock<std::mutex> lock(limited_probe.mutex);
        CHECK(limited_probe.condition.wait_for(lock, std::chrono::seconds(5), [&limited_probe]() {
            return !limited_probe.errors.empty();
        }));
    }
    CHECK(limited_probe.errors.size() == 1);
    CHECK(limited_probe.errors.front().code == "sequence_capacity_exceeded");
    limited_client.stop();

    Probe cancelled_probe;
    TtsCallbacks cancelled_callbacks;
    cancelled_callbacks.on_audio = [&cancelled_probe](const PcmChunk& chunk) {
        std::lock_guard<std::mutex> lock(cancelled_probe.mutex);
        cancelled_probe.audio.insert(
            cancelled_probe.audio.end(), chunk.bytes.begin(), chunk.bytes.end());
        cancelled_probe.condition.notify_all();
    };
    cancelled_callbacks.on_cancelled = [&cancelled_probe]() {
        std::lock_guard<std::mutex> lock(cancelled_probe.mutex);
        ++cancelled_probe.cancelled;
        cancelled_probe.condition.notify_all();
    };
    cancelled_callbacks.on_completed = [&cancelled_probe]() {
        std::lock_guard<std::mutex> lock(cancelled_probe.mutex);
        ++cancelled_probe.completed;
        cancelled_probe.condition.notify_all();
    };
    cancelled_callbacks.on_error = [&cancelled_probe](const TtsError& error) {
        std::lock_guard<std::mutex> lock(cancelled_probe.mutex);
        cancelled_probe.errors.push_back(error);
        cancelled_probe.condition.notify_all();
    };
    const RequestId cancelled_id = client.synthesize_async("cancel native worker", cancelled_callbacks);
    {
        std::unique_lock<std::mutex> lock(cancelled_probe.mutex);
        CHECK(cancelled_probe.condition.wait_for(lock, std::chrono::seconds(5), [&cancelled_probe]() {
            return cancelled_probe.audio.size() >= 8 || !cancelled_probe.errors.empty();
        }));
    }
    CHECK(client.cancel(cancelled_id));
    {
        std::unique_lock<std::mutex> lock(cancelled_probe.mutex);
        CHECK(cancelled_probe.condition.wait_for(lock, std::chrono::seconds(5), [&cancelled_probe]() {
            return cancelled_probe.cancelled != 0 || !cancelled_probe.errors.empty();
        }));
    }
    CHECK(cancelled_probe.errors.empty());
    CHECK(cancelled_probe.cancelled == 1);
    const auto cancelled_audio_size = cancelled_probe.audio.size();
    std::this_thread::sleep_for(std::chrono::milliseconds(250));
    CHECK(cancelled_probe.audio.size() == cancelled_audio_size);

    Probe recovery_probe;
    TtsCallbacks recovery_callbacks;
    recovery_callbacks.on_audio = [&recovery_probe](const PcmChunk& chunk) {
        std::lock_guard<std::mutex> lock(recovery_probe.mutex);
        recovery_probe.audio.insert(
            recovery_probe.audio.end(), chunk.bytes.begin(), chunk.bytes.end());
    };
    recovery_callbacks.on_completed = [&recovery_probe]() {
        std::lock_guard<std::mutex> lock(recovery_probe.mutex);
        ++recovery_probe.completed;
        recovery_probe.condition.notify_all();
    };
    recovery_callbacks.on_error = [&recovery_probe](const TtsError& error) {
        std::lock_guard<std::mutex> lock(recovery_probe.mutex);
        recovery_probe.errors.push_back(error);
        recovery_probe.condition.notify_all();
    };
    CHECK(client.synthesize_async("after cancellation", recovery_callbacks) != 0);
    {
        std::unique_lock<std::mutex> lock(recovery_probe.mutex);
        CHECK(recovery_probe.condition.wait_for(lock, std::chrono::seconds(5), [&recovery_probe]() {
            return recovery_probe.completed != 0 || !recovery_probe.errors.empty();
        }));
    }
    CHECK(recovery_probe.errors.empty());
    CHECK(recovery_probe.completed == 1);

    Probe max_probe;
    TtsCallbacks max_callbacks;
    max_callbacks.on_audio = [&max_probe](const PcmChunk& chunk) {
        std::lock_guard<std::mutex> lock(max_probe.mutex);
        max_probe.audio.insert(max_probe.audio.end(), chunk.bytes.begin(), chunk.bytes.end());
    };
    max_callbacks.on_completion_metadata = [&max_probe](const TtsCompletion& completion) {
        std::lock_guard<std::mutex> lock(max_probe.mutex);
        max_probe.completions.push_back(completion);
        max_probe.condition.notify_all();
    };
    max_callbacks.on_completed = [&max_probe]() {
        std::lock_guard<std::mutex> lock(max_probe.mutex);
        ++max_probe.completed;
        max_probe.condition.notify_all();
    };
    max_callbacks.on_error = [&max_probe](const TtsError& error) {
        std::lock_guard<std::mutex> lock(max_probe.mutex);
        max_probe.errors.push_back(error);
        max_probe.condition.notify_all();
    };
    CHECK(client.synthesize_async("force max tokens", max_callbacks) != 0);
    {
        std::unique_lock<std::mutex> lock(max_probe.mutex);
        CHECK(max_probe.condition.wait_for(lock, std::chrono::seconds(5), [&max_probe]() {
            return max_probe.completed != 0 || !max_probe.errors.empty();
        }));
    }
    CHECK(max_probe.errors.empty());
    CHECK(max_probe.completed == 1);
    CHECK(max_probe.completions.size() == 1);
    CHECK(max_probe.completions.front().execution_outcome == "max_tokens");

    Probe unknown_probe;
    TtsCallbacks unknown_callbacks;
    unknown_callbacks.on_audio = [&unknown_probe](const PcmChunk& chunk) {
        std::lock_guard<std::mutex> lock(unknown_probe.mutex);
        unknown_probe.audio.insert(unknown_probe.audio.end(), chunk.bytes.begin(), chunk.bytes.end());
    };
    unknown_callbacks.on_error = [&unknown_probe](const TtsError& error) {
        std::lock_guard<std::mutex> lock(unknown_probe.mutex);
        unknown_probe.errors.push_back(error);
        unknown_probe.condition.notify_all();
    };
    unknown_callbacks.on_completed = [&unknown_probe]() {
        std::lock_guard<std::mutex> lock(unknown_probe.mutex);
        ++unknown_probe.completed;
        unknown_probe.condition.notify_all();
    };
    CHECK(client.synthesize_async("force unknown finish reason", unknown_callbacks) != 0);
    {
        std::unique_lock<std::mutex> lock(unknown_probe.mutex);
        CHECK(unknown_probe.condition.wait_for(lock, std::chrono::seconds(5), [&unknown_probe]() {
            return !unknown_probe.errors.empty() || unknown_probe.completed != 0;
        }));
    }
    CHECK(unknown_probe.completed == 0);
    CHECK(unknown_probe.errors.size() == 1);
    CHECK(unknown_probe.errors.front().code == "invalid_finish_reason");

    Probe empty_eos_probe;
    TtsCallbacks empty_eos_callbacks;
    empty_eos_callbacks.on_audio = [&empty_eos_probe](const PcmChunk& chunk) {
        std::lock_guard<std::mutex> lock(empty_eos_probe.mutex);
        empty_eos_probe.audio.insert(
            empty_eos_probe.audio.end(), chunk.bytes.begin(), chunk.bytes.end());
        empty_eos_probe.condition.notify_all();
    };
    empty_eos_callbacks.on_completed = [&empty_eos_probe]() {
        std::lock_guard<std::mutex> lock(empty_eos_probe.mutex);
        ++empty_eos_probe.completed;
        empty_eos_probe.condition.notify_all();
    };
    empty_eos_callbacks.on_error = [&empty_eos_probe](const TtsError& error) {
        std::lock_guard<std::mutex> lock(empty_eos_probe.mutex);
        empty_eos_probe.errors.push_back(error);
        empty_eos_probe.condition.notify_all();
    };
    CHECK(client.synthesize_async("force empty eos", empty_eos_callbacks) != 0);
    {
        std::unique_lock<std::mutex> lock(empty_eos_probe.mutex);
        CHECK(empty_eos_probe.condition.wait_for(
            lock, std::chrono::seconds(5), [&empty_eos_probe]() {
                return !empty_eos_probe.errors.empty() ||
                    empty_eos_probe.completed != 0;
            }));
    }
    CHECK(empty_eos_probe.completed == 0);
    CHECK(empty_eos_probe.errors.size() == 1);
    CHECK(empty_eos_probe.errors.front().category == "model_error");
    CHECK(empty_eos_probe.errors.front().code == "empty_audio");
    CHECK(empty_eos_probe.audio.empty());

    client.stop();
    return EXIT_SUCCESS;
}
