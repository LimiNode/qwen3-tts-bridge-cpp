#include <qwen_tts_bridge/client.hpp>
#include <qwen_tts_bridge/protocol/framing.hpp>

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstddef>
#include <cstdlib>
#include <iostream>
#include <mutex>
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>
#include <vector>

#define CHECK(expr)                                                            \
    do {                                                                       \
        if (!(expr)) {                                                         \
            std::cerr << "CHECK failed: " #expr << " at " << __FILE__ << ':'  \
                      << __LINE__ << '\n';                                     \
            std::exit(EXIT_FAILURE);                                           \
        }                                                                      \
    } while (false)

namespace {

using namespace qwen_tts_bridge;

struct RequestProbe {
    std::mutex mutex;
    std::condition_variable condition;
    std::size_t audio_chunks = 0;
    std::size_t audio_bytes = 0;
    std::size_t completed_count = 0;
    std::size_t cancelled_count = 0;
    bool completed = false;
    bool cancelled = false;
    std::vector<TtsError> errors;
    std::vector<RequestId> audio_request_ids;
};

std::vector<std::byte> bytes_from_string(const std::string& value) {
    std::vector<std::byte> bytes;
    bytes.reserve(value.size());
    for (const char ch : value) {
        bytes.push_back(static_cast<std::byte>(static_cast<unsigned char>(ch)));
    }
    return bytes;
}

std::vector<std::byte> frame_bytes(
    FrameType frame_type,
    RequestId request_id,
    const std::vector<std::byte>& payload) {
    const EncodeResult encoded = encode_frame(frame_type, request_id, payload);
    CHECK(encoded);
    return encoded.bytes;
}

std::vector<std::byte> control_frame_bytes(
    RequestId request_id,
    const std::string& json) {
    return frame_bytes(FrameType::ControlJson, request_id, bytes_from_string(json));
}

std::vector<std::byte> ready_frame_bytes() {
    return control_frame_bytes(
        0,
        "{\"message_type\":\"ready\","
        "\"worker_version\":\"0.2.0\","
        "\"session_id\":\"scripted-client-test\","
        "\"warmed_up\":true,"
        "\"capabilities\":{"
        "\"streaming\":true,"
        "\"cancellation\":true,"
        "\"instructions\":true,"
        "\"voice_clone\":false},"
        "\"voice_ids\":[\"ephi\",\"kraftwerk\"]"
        "}");
}

class BlockingTransport final : public ITransport {
public:
    bool block_after_hello = false;
    SendResult send_after_hello_result = SendResult::Accepted;

    bool start(
        ReceiveHandler receive_handler,
        ErrorHandler error_handler,
        ExitHandler exit_handler) override {
        receive_handler_ = std::move(receive_handler);
        error_handler_ = std::move(error_handler);
        exit_handler_ = std::move(exit_handler);
        running_ = true;
        return true;
    }

    SendResult send(const std::byte* data, std::size_t size) override {
        if (!running_ || (data == nullptr && size != 0)) {
            return SendResult::Closed;
        }

        const int current_send = ++send_count_;
        {
            std::lock_guard<std::mutex> lock(mutex_);
            last_send_.assign(data, data + size);
        }
        if (current_send == 1) {
            receive_handler_(ready_frame_bytes());
            return SendResult::Accepted;
        }

        if (send_after_hello_result != SendResult::Accepted) {
            return send_after_hello_result;
        }

        if (block_after_hello) {
            std::unique_lock<std::mutex> lock(mutex_);
            blocked_ = true;
            condition_.notify_all();
            condition_.wait(lock, [this]() {
                return release_block_ || !running_;
            });
        }

        return running_ ? SendResult::Accepted : SendResult::Closed;
    }

    bool is_running() const override {
        return running_;
    }

    void stop() override {
        {
            std::lock_guard<std::mutex> lock(mutex_);
            running_ = false;
            release_block_ = true;
        }
        condition_.notify_all();
    }

    bool wait_until_blocked() {
        std::unique_lock<std::mutex> lock(mutex_);
        return condition_.wait_for(
            lock,
            std::chrono::seconds(5),
            [this]() {
                return blocked_;
            });
    }

    void release() {
        {
            std::lock_guard<std::mutex> lock(mutex_);
            release_block_ = true;
        }
        condition_.notify_all();
    }

    std::vector<std::byte> last_send() const {
        std::lock_guard<std::mutex> lock(mutex_);
        return last_send_;
    }

    int send_count() const noexcept {
        return send_count_.load();
    }

private:
    ReceiveHandler receive_handler_;
    ErrorHandler error_handler_;
    ExitHandler exit_handler_;
    mutable std::mutex mutex_;
    std::condition_variable condition_;
    std::atomic<int> send_count_{0};
    std::atomic<bool> running_{false};
    bool blocked_ = false;
    bool release_block_ = false;
    std::vector<std::byte> last_send_;
};

StdIoTransportOptions make_worker_options(
    int mock_chunks,
    double chunk_delay_seconds = 0.0) {
    StdIoTransportOptions options;
    options.arguments = {
        QWEN_TTS_BRIDGE_TEST_PYTHON_EXECUTABLE,
        "-m",
        "qwen_tts_bridge_worker.main",
        "--mock",
        "--mock-chunks",
        std::to_string(mock_chunks),
        "--mock-chunk-delay",
        std::to_string(chunk_delay_seconds)
    };
    options.working_directory = QWEN_TTS_BRIDGE_TEST_WORKER_DIR;
    options.shutdown_timeout = std::chrono::seconds(5);
    return options;
}

QwenTtsClientOptions make_client_options() {
    QwenTtsClientOptions options;
    options.session.client_name = "qwen-tts-client-test";
    options.session.client_version = "0.2.0";
    options.session.startup_timeout = std::chrono::seconds(5);
    return options;
}

TtsCallbacks make_callbacks(RequestProbe& probe) {
    TtsCallbacks callbacks;
    callbacks.on_audio = [&probe](const PcmChunk& chunk) {
        std::lock_guard<std::mutex> lock(probe.mutex);
        ++probe.audio_chunks;
        probe.audio_bytes += chunk.bytes.size();
        probe.audio_request_ids.push_back(chunk.request_id);
        probe.condition.notify_all();
    };
    callbacks.on_completed = [&probe]() {
        std::lock_guard<std::mutex> lock(probe.mutex);
        ++probe.completed_count;
        probe.completed = true;
        probe.condition.notify_all();
    };
    callbacks.on_cancelled = [&probe]() {
        std::lock_guard<std::mutex> lock(probe.mutex);
        ++probe.cancelled_count;
        probe.cancelled = true;
        probe.condition.notify_all();
    };
    callbacks.on_error = [&probe](const TtsError& error) {
        std::lock_guard<std::mutex> lock(probe.mutex);
        probe.errors.push_back(error);
        probe.condition.notify_all();
    };
    return callbacks;
}

template <class Predicate>
bool wait_for_probe(RequestProbe& probe, Predicate predicate) {
    std::unique_lock<std::mutex> lock(probe.mutex);
    return probe.condition.wait_for(
        lock,
        std::chrono::seconds(5),
        [&probe, &predicate]() {
            return predicate(probe);
        });
}

TtsRequest make_request(const std::string& text) {
    TtsRequest request;
    request.text = text;
    request.language = "English";
    request.instruction = "Speak calmly.";
    return request;
}

void test_synthesize_async_delivers_audio_and_completed() {
    QwenTtsClient client;
    CHECK(client.start(make_worker_options(2), make_client_options()));
    CHECK(client.is_running());

    RequestProbe probe;
    const RequestId request_id = client.synthesize_async(
        "Hello from QwenTtsClient.",
        make_callbacks(probe));

    CHECK(request_id != 0);
    CHECK(wait_for_probe(probe, [](const RequestProbe& state) {
        return state.completed || !state.errors.empty();
    }));

    {
        std::lock_guard<std::mutex> lock(probe.mutex);
        CHECK(probe.errors.empty());
        CHECK(probe.completed);
        CHECK(probe.completed_count == 1);
        CHECK(!probe.cancelled);
        CHECK(probe.cancelled_count == 0);
        CHECK(probe.audio_chunks > 0);
        CHECK(probe.audio_bytes > 0);
        for (const RequestId audio_request_id : probe.audio_request_ids) {
            CHECK(audio_request_id == request_id);
        }
    }

    client.stop();
    CHECK(!client.is_running());
}

void test_available_voice_ids_snapshot() {
    QwenTtsClient client;
    CHECK(client.available_voice_ids().empty());
    CHECK(client.start(
        std::make_unique<BlockingTransport>(),
        make_client_options()));
    const auto voice_ids = client.available_voice_ids();
    CHECK(voice_ids.size() == 2);
    CHECK(voice_ids[0] == "ephi");
    CHECK(voice_ids[1] == "kraftwerk");
    client.stop();
    CHECK(client.available_voice_ids().empty());
}

void test_multiple_async_requests_complete() {
    QwenTtsClient client;
    CHECK(client.start(make_worker_options(1), make_client_options()));

    RequestProbe first;
    RequestProbe second;

    const RequestId first_id = client.synthesize_async(
        make_request("First queued request."),
        make_callbacks(first));
    const RequestId second_id = client.synthesize_async(
        make_request("Second queued request."),
        make_callbacks(second));

    CHECK(first_id != 0);
    CHECK(second_id != 0);
    CHECK(first_id != second_id);

    CHECK(wait_for_probe(first, [](const RequestProbe& state) {
        return state.completed || !state.errors.empty();
    }));
    CHECK(wait_for_probe(second, [](const RequestProbe& state) {
        return state.completed || !state.errors.empty();
    }));

    {
        std::lock_guard<std::mutex> lock(first.mutex);
        CHECK(first.errors.empty());
        CHECK(first.completed);
        CHECK(first.completed_count == 1);
        CHECK(first.audio_chunks > 0);
    }
    {
        std::lock_guard<std::mutex> lock(second.mutex);
        CHECK(second.errors.empty());
        CHECK(second.completed);
        CHECK(second.completed_count == 1);
        CHECK(second.audio_chunks > 0);
    }

    client.stop();
}

void test_cancel_queued_request() {
    QwenTtsClient client;
    CHECK(client.start(make_worker_options(5, 0.05), make_client_options()));

    RequestProbe first;
    RequestProbe second;

    const RequestId first_id = client.synthesize_async(
        make_request("Long first request."),
        make_callbacks(first));
    const RequestId second_id = client.synthesize_async(
        make_request("Queued request to cancel."),
        make_callbacks(second));

    CHECK(first_id != 0);
    CHECK(second_id != 0);
    CHECK(client.cancel(second_id));

    CHECK(wait_for_probe(second, [](const RequestProbe& state) {
        return state.cancelled || !state.errors.empty();
    }));
    CHECK(wait_for_probe(first, [](const RequestProbe& state) {
        return state.completed || !state.errors.empty();
    }));

    {
        std::lock_guard<std::mutex> lock(second.mutex);
        CHECK(second.errors.empty());
        CHECK(second.cancelled);
        CHECK(second.cancelled_count == 1);
        CHECK(!second.completed);
        CHECK(second.completed_count == 0);
    }
    {
        std::lock_guard<std::mutex> lock(first.mutex);
        CHECK(first.errors.empty());
        CHECK(first.completed);
        CHECK(first.completed_count == 1);
    }

    client.stop();
}

void test_request_error_routes_to_callback() {
    QwenTtsClient client;
    CHECK(client.start(make_worker_options(1), make_client_options()));

    RequestProbe probe;
    TtsRequest request = make_request("Unsupported format request.");
    request.output.sample_rate = 48000;

    const RequestId request_id = client.synthesize_async(
        std::move(request),
        make_callbacks(probe));

    CHECK(request_id != 0);
    CHECK(wait_for_probe(probe, [](const RequestProbe& state) {
        return !state.errors.empty();
    }));

    {
        std::lock_guard<std::mutex> lock(probe.mutex);
        CHECK(!probe.completed);
        CHECK(!probe.cancelled);
        CHECK(probe.errors.size() == 1);
        CHECK(probe.errors.front().request_id == request_id);
        CHECK(probe.errors.front().category == "request_error");
        CHECK(probe.errors.front().code == "unsupported_audio_format");
    }

    client.stop();
}

void test_stop_from_audio_callback_allows_restart() {
    QwenTtsClient client;
    CHECK(client.start(make_worker_options(3, 0.01), make_client_options()));

    std::mutex mutex;
    std::condition_variable condition;
    bool audio_callback_returned = false;

    TtsCallbacks callbacks;
    callbacks.on_audio = [&](const PcmChunk&) {
        client.stop();
        {
            std::lock_guard<std::mutex> lock(mutex);
            audio_callback_returned = true;
        }
        condition.notify_all();
    };

    CHECK(client.synthesize_async(
        "Stop from audio callback.",
        std::move(callbacks)) != 0);

    {
        std::unique_lock<std::mutex> lock(mutex);
        CHECK(condition.wait_for(lock, std::chrono::seconds(5), [&]() {
            return audio_callback_returned;
        }));
    }

    CHECK(!client.is_running());
    CHECK(client.start(make_worker_options(1), make_client_options()));
    client.stop();
}

void test_stop_from_completed_callback_then_destruct_outside() {
    std::mutex mutex;
    std::condition_variable condition;
    bool completed_callback_returned = false;

    {
        QwenTtsClient client;
        CHECK(client.start(make_worker_options(1), make_client_options()));

        TtsCallbacks callbacks;
        callbacks.on_completed = [&]() {
            client.stop();
            {
                std::lock_guard<std::mutex> lock(mutex);
                completed_callback_returned = true;
            }
            condition.notify_all();
        };

        CHECK(client.synthesize_async(
            "Stop from completed callback.",
            std::move(callbacks)) != 0);

        std::unique_lock<std::mutex> lock(mutex);
        CHECK(condition.wait_for(lock, std::chrono::seconds(5), [&]() {
            return completed_callback_returned;
        }));
    }
}

void test_callback_exception_is_reported_and_swallowed() {
    QwenTtsClient client;
    QwenTtsClientOptions options = make_client_options();
    std::atomic<int> exception_count{0};
    options.on_callback_exception = [&](std::exception_ptr exception) {
        CHECK(exception != nullptr);
        ++exception_count;
    };
    CHECK(client.start(make_worker_options(1), options));

    RequestProbe probe;
    TtsCallbacks callbacks = make_callbacks(probe);
    callbacks.on_audio = [](const PcmChunk&) {
        throw std::runtime_error("audio callback failed");
    };

    CHECK(client.synthesize_async(
        "Throw from audio callback.",
        std::move(callbacks)) != 0);

    CHECK(wait_for_probe(probe, [](const RequestProbe& state) {
        return state.completed || !state.errors.empty();
    }));
    CHECK(exception_count == 1);

    {
        std::lock_guard<std::mutex> lock(probe.mutex);
        CHECK(probe.completed);
        CHECK(probe.completed_count == 1);
        CHECK(probe.errors.empty());
    }

    client.stop();
}

void test_error_callback_exception_is_reported_once() {
    QwenTtsClient client;
    QwenTtsClientOptions options = make_client_options();
    std::atomic<int> exception_count{0};
    options.on_callback_exception = [&](std::exception_ptr exception) {
        CHECK(exception != nullptr);
        ++exception_count;
    };
    CHECK(client.start(make_worker_options(1), options));

    TtsRequest request = make_request("Throw from error callback.");
    request.output.sample_rate = 48000;

    RequestProbe probe;
    TtsCallbacks callbacks = make_callbacks(probe);
    callbacks.on_error = [&](const TtsError&) {
        {
            std::lock_guard<std::mutex> lock(probe.mutex);
            probe.errors.push_back(TtsError{});
            probe.condition.notify_all();
        }
        throw std::runtime_error("error callback failed");
    };

    CHECK(client.synthesize_async(
        std::move(request),
        std::move(callbacks)) != 0);

    CHECK(wait_for_probe(probe, [](const RequestProbe& state) {
        return !state.errors.empty();
    }));
    for (int attempt = 0; attempt < 50 && exception_count != 1; ++attempt) {
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }
    CHECK(exception_count == 1);

    client.stop();
}

void test_outbound_count_overflow_is_rejected() {
    auto transport = std::make_unique<BlockingTransport>();
    auto* raw_transport = transport.get();
    raw_transport->block_after_hello = true;

    QwenTtsClientOptions options = make_client_options();
    options.max_outbound_commands = 1;

    QwenTtsClient client;
    CHECK(client.start(std::move(transport), options));

    RequestProbe first;
    RequestProbe second;
    RequestProbe third;

    CHECK(client.synthesize_async(
        make_request("Blocked request."),
        make_callbacks(first)) != 0);
    CHECK(raw_transport->wait_until_blocked());

    CHECK(client.synthesize_async(
        make_request("Queued request."),
        make_callbacks(second)) != 0);
    CHECK(client.synthesize_async(
        make_request("Overflow request."),
        make_callbacks(third)) == 0);

    raw_transport->release();
    client.stop();
}

void test_outbound_byte_overflow_is_rejected() {
    auto transport = std::make_unique<BlockingTransport>();

    QwenTtsClientOptions options = make_client_options();
    options.max_outbound_command_bytes = 128;

    QwenTtsClient client;
    CHECK(client.start(std::move(transport), options));

    TtsRequest request = make_request(std::string(512, 'x'));
    RequestProbe probe;
    CHECK(client.synthesize_async(
        std::move(request),
        make_callbacks(probe)) == 0);

    client.stop();
}

void test_invalid_request_is_rejected_before_id_assignment() {
    auto transport = std::make_unique<BlockingTransport>();

    QwenTtsClient client;
    CHECK(client.start(std::move(transport), make_client_options()));

    TtsRequest request = make_request("Invalid local request.");
    request.output.sample_rate = 0;

    RequestProbe probe;
    CHECK(client.synthesize_async(
        std::move(request),
        make_callbacks(probe)) == 0);

    client.stop();
}

void test_text_preprocessor_changes_spoken_text_only() {
    auto transport = std::make_unique<BlockingTransport>();
    auto* raw_transport = transport.get();
    raw_transport->block_after_hello = true;
    QwenTtsClientOptions options = make_client_options();
    options.text_preprocessor = [](const TtsRequest& request) {
        CHECK(request.reference_text == "reference stays byte-identical");
        return std::string("processed text");
    };
    QwenTtsClient client;
    CHECK(client.start(std::move(transport), options));
    TtsRequest request = make_request("original text");
    request.reference_audio_path = "reference.wav";
    request.reference_text = "reference stays byte-identical";
    RequestProbe probe;
    CHECK(client.synthesize_async(std::move(request), make_callbacks(probe)) != 0);
    CHECK(raw_transport->wait_until_blocked());
    const auto sent = raw_transport->last_send();
    std::string wire;
    wire.reserve(sent.size());
    for (const auto byte : sent) {
        wire.push_back(static_cast<char>(std::to_integer<unsigned char>(byte)));
    }
    CHECK(wire.find("processed text") != std::string::npos);
    CHECK(wire.find("reference stays byte-identical") != std::string::npos);
    raw_transport->release();
    client.stop();
}

void test_text_preprocessor_preserves_utf8_and_reference_text() {
    auto transport = std::make_unique<BlockingTransport>();
    auto* raw_transport = transport.get();
    raw_transport->block_after_hello = true;
    QwenTtsClientOptions options = make_client_options();
    const std::string russian_text =
        "\xD0\xA1\xD0\xB5\xD0\xB3\xD0\xBE\xD0\xB4\xD0\xBD\xD1\x8F";
    const std::string russian_reference =
        "\xD0\xAD\xD1\x82\xD0\xB0\xD0\xBB\xD0\xBE\xD0\xBD\xD0\xBD\xD0\xB0\xD1\x8F "
        "\xD1\x84\xD1\x80\xD0\xB0\xD0\xB7\xD0\xB0";
    const std::string processed_russian =
        russian_text + ", \xD0\xBF\xD1\x80\xD0\xBE\xD0\xB2\xD0\xB5\xD1\x80\xD0\xBA\xD0\xB0 UTF-8";
    options.text_preprocessor = [
        &russian_text,
        &russian_reference,
        &processed_russian](const TtsRequest& request) {
        CHECK(request.text == russian_text || request.text == "Today");
        CHECK(request.reference_text == russian_reference);
        return request.text == russian_text
            ? processed_russian
            : std::string("Today, UTF-8 check");
    };
    QwenTtsClient client;
    CHECK(client.start(std::move(transport), options));
    TtsRequest russian = make_request(russian_text);
    russian.reference_audio_path = "reference.wav";
    russian.reference_text = russian_reference;
    RequestProbe russian_probe;
    CHECK(client.synthesize_async(std::move(russian), make_callbacks(russian_probe)) != 0);
    CHECK(raw_transport->wait_until_blocked());
    const auto sent = raw_transport->last_send();
    std::string wire;
    wire.reserve(sent.size());
    for (const auto byte : sent) {
        wire.push_back(static_cast<char>(std::to_integer<unsigned char>(byte)));
    }
    CHECK(wire.find(processed_russian) != std::string::npos);
    CHECK(wire.find(russian_reference) != std::string::npos);
    raw_transport->release();
    client.stop();

    auto english_transport = std::make_unique<BlockingTransport>();
    auto* raw_english_transport = english_transport.get();
    raw_english_transport->block_after_hello = true;
    QwenTtsClientOptions english_options = make_client_options();
    english_options.text_preprocessor = [](const TtsRequest& request) {
        CHECK(request.text == "Today");
        CHECK(request.reference_text == "Reference sentence");
        return std::string("Today, UTF-8 check");
    };
    QwenTtsClient english_client;
    CHECK(english_client.start(std::move(english_transport), english_options));
    TtsRequest english = make_request("Today");
    english.reference_audio_path = "reference.wav";
    english.reference_text = "Reference sentence";
    RequestProbe english_probe;
    CHECK(english_client.synthesize_async(
        std::move(english), make_callbacks(english_probe)) != 0);
    CHECK(raw_english_transport->wait_until_blocked());
    const auto english_sent = raw_english_transport->last_send();
    std::string english_wire;
    english_wire.reserve(english_sent.size());
    for (const auto byte : english_sent) {
        english_wire.push_back(static_cast<char>(std::to_integer<unsigned char>(byte)));
    }
    CHECK(english_wire.find("Today, UTF-8 check") != std::string::npos);
    CHECK(english_wire.find("Reference sentence") != std::string::npos);
    raw_english_transport->release();
    english_client.stop();
}

void test_text_preprocessor_rejects_invalid_utf8() {
    auto transport = std::make_unique<BlockingTransport>();
    auto* raw_transport = transport.get();
    QwenTtsClientOptions options = make_client_options();
    options.text_preprocessor = [](const TtsRequest&) {
        return std::string("bad\xC3\x28", 5);
    };
    QwenTtsClient client;
    CHECK(client.start(std::move(transport), options));
    RequestProbe probe;
    CHECK(client.synthesize_async(make_request("valid"), make_callbacks(probe)) == 0);
    {
        std::lock_guard<std::mutex> lock(probe.mutex);
        CHECK(probe.errors.size() == 1);
        CHECK(probe.errors.front().category == "client_error");
        CHECK(probe.errors.front().code == "invalid_utf8_text");
    }
    CHECK(raw_transport->send_count() == 1);
    client.stop();
}

void test_text_preprocessor_failure_is_local() {
    auto transport = std::make_unique<BlockingTransport>();
    auto* raw_transport = transport.get();
    QwenTtsClientOptions options = make_client_options();
    options.text_preprocessor = [](const TtsRequest&) -> std::string {
        throw std::runtime_error("normalizer unavailable");
    };
    QwenTtsClient client;
    CHECK(client.start(std::move(transport), options));
    RequestProbe probe;
    CHECK(client.synthesize_async(
        make_request("must not reach worker"), make_callbacks(probe)) == 0);
    {
        std::lock_guard<std::mutex> lock(probe.mutex);
        CHECK(probe.errors.size() == 1);
        CHECK(probe.errors.front().code == "text_preprocessing_failed");
    }
    CHECK(raw_transport->send_count() == 1);
    client.stop();
}

void test_prepare_text_reports_effective_utf8_metrics() {
    auto transport = std::make_unique<BlockingTransport>();
    QwenTtsClientOptions options = make_client_options();
    options.text_preprocessor = [](const TtsRequest&) {
        return std::string("ООО ВК 2042 г.");
    };
    QwenTtsClient client;
    CHECK(client.start(std::move(transport), options));

    TtsRequest request = make_request("ООО ВК 2042 г.");
    PreparedText prepared;
    TtsError error;
    CHECK(client.prepare_text(request, prepared, error));
    CHECK(error.code.empty());
    CHECK(prepared.original_text == request.text);
    CHECK(prepared.effective_text == request.text);
    CHECK(prepared.utf8_bytes == prepared.effective_text.size());
    CHECK(prepared.non_space_utf8_bytes < prepared.utf8_bytes);
    CHECK(!prepared.was_modified);

    options.text_preprocessor = [](const TtsRequest&) {
        return std::string("о о о вэ ка в две тысячи сорок втором году");
    };
    client.stop();
    CHECK(client.start(std::make_unique<BlockingTransport>(), options));
    prepared = PreparedText{};
    error = TtsError{};
    CHECK(client.prepare_text(request, prepared, error));
    CHECK(prepared.was_modified);
    CHECK(prepared.original_text == request.text);
    CHECK(prepared.effective_text != request.text);
    CHECK(prepared.non_space_utf8_bytes <= prepared.utf8_bytes);
    client.stop();
}

void test_prepared_request_bypasses_preprocessor_once() {
    auto transport = std::make_unique<BlockingTransport>();
    auto* raw_transport = transport.get();
    raw_transport->block_after_hello = true;
    int preprocessing_calls = 0;
    QwenTtsClientOptions options = make_client_options();
    options.text_preprocessor = [&preprocessing_calls](const TtsRequest&) {
        ++preprocessing_calls;
        return std::string("effective text");
    };
    QwenTtsClient client;
    CHECK(client.start(std::move(transport), options));

    TtsRequest request = make_request("source text");
    PreparedText prepared;
    TtsError error;
    CHECK(client.prepare_text(request, prepared, error));
    CHECK(preprocessing_calls == 1);

    RequestProbe probe;
    PreparedTtsRequest prepared_request;
    prepared_request.request = request;
    prepared_request.text = prepared;
    CHECK(client.synthesize_async(
        std::move(prepared_request), make_callbacks(probe)) != 0);
    CHECK(preprocessing_calls == 1);
    CHECK(raw_transport->wait_until_blocked());
    const auto sent = raw_transport->last_send();
    std::string wire;
    for (const auto byte : sent) {
        wire.push_back(static_cast<char>(std::to_integer<unsigned char>(byte)));
    }
    CHECK(wire.find("effective text") != std::string::npos);
    CHECK(wire.find("source text") == std::string::npos);
    raw_transport->release();
    client.stop();
}

void test_prepared_request_rejects_source_mismatch() {
    auto transport = std::make_unique<BlockingTransport>();
    QwenTtsClient client;
    CHECK(client.start(std::move(transport), make_client_options()));

    PreparedTtsRequest prepared_request;
    prepared_request.request = make_request("source text");
    prepared_request.text.original_text = "different source";
    prepared_request.text.effective_text = "effective text";
    RequestProbe probe;
    CHECK(client.synthesize_async(
        std::move(prepared_request), make_callbacks(probe)) == 0);
    {
        std::lock_guard<std::mutex> lock(probe.mutex);
        CHECK(probe.errors.size() == 1);
        CHECK(probe.errors.front().code == "prepared_text_mismatch");
    }
    client.stop();
}

void test_duplicate_explicit_request_id_is_rejected() {
    auto transport = std::make_unique<BlockingTransport>();
    auto* raw_transport = transport.get();
    raw_transport->block_after_hello = true;

    QwenTtsClient client;
    CHECK(client.start(std::move(transport), make_client_options()));

    RequestProbe first;
    RequestProbe second;
    TtsRequest first_request = make_request("Explicit request ID.");
    first_request.id = 42;
    TtsRequest second_request = make_request("Duplicate explicit request ID.");
    second_request.id = 42;

    CHECK(client.synthesize_async(
        std::move(first_request),
        make_callbacks(first)) == 42);
    CHECK(raw_transport->wait_until_blocked());
    CHECK(client.synthesize_async(
        std::move(second_request),
        make_callbacks(second)) == 0);

    raw_transport->release();
    client.stop();
}

void test_transport_send_failure_fails_request_once() {
    auto transport = std::make_unique<BlockingTransport>();
    transport->send_after_hello_result = SendResult::Failed;

    QwenTtsClient client;
    CHECK(client.start(std::move(transport), make_client_options()));

    RequestProbe probe;
    CHECK(client.synthesize_async(
        make_request("Send failure request."),
        make_callbacks(probe)) != 0);

    CHECK(wait_for_probe(probe, [](const RequestProbe& state) {
        return !state.errors.empty();
    }));

    {
        std::lock_guard<std::mutex> lock(probe.mutex);
        CHECK(probe.errors.size() == 1);
        CHECK(!probe.completed);
        CHECK(!probe.cancelled);
    }

    client.stop();
}

} // namespace

int main() {
    test_synthesize_async_delivers_audio_and_completed();
    test_available_voice_ids_snapshot();
    test_multiple_async_requests_complete();
    test_cancel_queued_request();
    test_request_error_routes_to_callback();
    test_stop_from_audio_callback_allows_restart();
    test_stop_from_completed_callback_then_destruct_outside();
    test_callback_exception_is_reported_and_swallowed();
    test_error_callback_exception_is_reported_once();
    test_outbound_count_overflow_is_rejected();
    test_outbound_byte_overflow_is_rejected();
    test_invalid_request_is_rejected_before_id_assignment();
    test_text_preprocessor_changes_spoken_text_only();
    test_text_preprocessor_preserves_utf8_and_reference_text();
    test_text_preprocessor_rejects_invalid_utf8();
    test_text_preprocessor_failure_is_local();
    test_prepare_text_reports_effective_utf8_metrics();
    test_prepared_request_bypasses_preprocessor_once();
    test_prepared_request_rejects_source_mismatch();
    test_duplicate_explicit_request_id_is_rejected();
    test_transport_send_failure_fails_request_once();
    return 0;
}
