#include <qwen_tts_bridge/protocol/control.hpp>
#include <qwen_tts_bridge/protocol/framing.hpp>

#include <nlohmann/json.hpp>

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <algorithm>
#include <array>
#include <chrono>
#include <condition_variable>
#include <cstddef>
#include <filesystem>
#include <iostream>
#include <mutex>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

#ifndef QWEN_TTS_NATIVE_WORKER_EXE
#error "QWEN_TTS_NATIVE_WORKER_EXE is required"
#endif
#ifndef QWEN_TTS_FAKE_RUNTIME_DIR
#error "QWEN_TTS_FAKE_RUNTIME_DIR is required"
#endif

namespace {
using namespace qwen_tts_bridge;

bool check(bool value, const char* expression, int line) {
    if (!value) {
        std::cerr << "CHECK failed: " << expression << " at line " << line << '\n';
    }
    return value;
}

#define CHECK(value) if (!check((value), #value, __LINE__)) return 1

struct ScopedHandle {
    HANDLE value = nullptr;

    ScopedHandle() = default;

    ~ScopedHandle() {
        reset();
    }

    ScopedHandle(const ScopedHandle&) = delete;
    ScopedHandle& operator=(const ScopedHandle&) = delete;

    HANDLE get() const {
        return value;
    }

    void reset(HANDLE replacement = nullptr) {
        if (value != nullptr && value != INVALID_HANDLE_VALUE) {
            CloseHandle(value);
        }
        value = replacement;
    }

    HANDLE* put() {
        reset();
        return &value;
    }
};

struct TestResources {
    ScopedHandle child_stdout_read;
    ScopedHandle child_stdout_write;
    ScopedHandle child_stdin_read;
    ScopedHandle child_stdin_write;
    ScopedHandle child_stderr_read;
    ScopedHandle child_stderr_write;
    ScopedHandle process;
    ScopedHandle process_thread;
    std::thread stdout_reader;
    std::thread stderr_reader;

    ~TestResources() {
        cleanup();
    }

    void cleanup() noexcept {
        child_stdin_write.reset();
        child_stdin_read.reset();
        child_stdout_write.reset();
        child_stderr_write.reset();

        if (process.get() != nullptr && process.get() != INVALID_HANDLE_VALUE) {
            if (WaitForSingleObject(process.get(), 0) != WAIT_OBJECT_0) {
                TerminateProcess(process.get(), 1);
                WaitForSingleObject(process.get(), 5000);
            }
        }
        if (stdout_reader.joinable()) {
            stdout_reader.join();
        }
        if (stderr_reader.joinable()) {
            stderr_reader.join();
        }
        child_stdout_read.reset();
        child_stderr_read.reset();
        process_thread.reset();
        process.reset();
    }
};

bool write_all(HANDLE handle, const std::vector<std::byte>& bytes) {
    std::size_t offset = 0;
    while (offset < bytes.size()) {
        DWORD written = 0;
        if (WriteFile(
                handle,
                bytes.data() + offset,
                static_cast<DWORD>(std::min<std::size_t>(
                    bytes.size() - offset,
                    static_cast<std::size_t>(MAXDWORD))),
                &written,
                nullptr) == FALSE || written == 0) {
            return false;
        }
        offset += written;
    }
    return true;
}

struct ByteCapture {
    std::mutex mutex;
    std::condition_variable changed;
    std::vector<std::byte> bytes;
};

std::vector<std::byte> control_frame(RequestId request_id, const ControlMessage& message) {
    const auto payload = encode_control_message(message);
    if (!payload) {
        return {};
    }
    const auto frame = encode_frame(FrameType::ControlJson, request_id, payload.payload);
    return frame ? frame.bytes : std::vector<std::byte>{};
}

bool parser_rejects_incomplete(const std::vector<std::byte>& bytes) {
    FrameParser parser;
    parser.append(bytes);
    const auto result = parser.parse_next();
    return result.status == ParseStatus::NeedMoreData && parser.buffered_size() != 0;
}

int run_parser_eof_regressions() {
    const auto payload = encode_control_message(
        ControlMessage{HelloMessage{"eof-regression", "0.2.0"}});
    CHECK(static_cast<bool>(payload));
    const auto encoded = encode_frame(FrameType::ControlJson, 0, payload.payload);
    CHECK(static_cast<bool>(encoded));
    CHECK(encoded.bytes.size() > ProtocolLimits::min_header_size);

    std::vector<std::byte> truncated_header(
        encoded.bytes.begin(),
        encoded.bytes.begin() + static_cast<std::ptrdiff_t>(ProtocolLimits::min_header_size - 1));
    CHECK(parser_rejects_incomplete(truncated_header));

    std::vector<std::byte> truncated_payload(
        encoded.bytes.begin(),
        encoded.bytes.end() - 1);
    CHECK(parser_rejects_incomplete(truncated_payload));

    auto trailing_data = encoded.bytes;
    trailing_data.push_back(std::byte{0x7f});
    FrameParser parser;
    parser.append(trailing_data);
    CHECK(parser.parse_next().status == ParseStatus::FrameReady);
    CHECK(parser.parse_next().status == ParseStatus::NeedMoreData);
    CHECK(parser.buffered_size() == 1);
    return 0;
}

void drain_pipe(HANDLE handle, ByteCapture* output) {
    std::array<std::byte, 64 * 1024> buffer{};
    DWORD count = 0;
    while (ReadFile(
               handle,
               buffer.data(),
               static_cast<DWORD>(buffer.size()),
               &count,
               nullptr) != FALSE && count != 0) {
        if (output != nullptr) {
            {
                std::lock_guard<std::mutex> lock(output->mutex);
                output->bytes.insert(output->bytes.end(), buffer.begin(), buffer.begin() + count);
            }
            output->changed.notify_all();
        }
    }
}

} // namespace

int run_pipe_integrity_case(int iteration) {
    ByteCapture stdout_capture;
    ByteCapture stderr_capture;
    TestResources resources;

    SECURITY_ATTRIBUTES attributes{};
    attributes.nLength = sizeof(attributes);
    attributes.bInheritHandle = TRUE;

    CHECK(CreatePipe(
        resources.child_stdout_read.put(),
        resources.child_stdout_write.put(),
        &attributes,
        0) != FALSE);
    CHECK(SetHandleInformation(resources.child_stdout_read.get(), HANDLE_FLAG_INHERIT, 0) != FALSE);
    CHECK(CreatePipe(
        resources.child_stdin_read.put(),
        resources.child_stdin_write.put(),
        &attributes,
        0) != FALSE);
    CHECK(SetHandleInformation(resources.child_stdin_write.get(), HANDLE_FLAG_INHERIT, 0) != FALSE);
    CHECK(CreatePipe(
        resources.child_stderr_read.put(),
        resources.child_stderr_write.put(),
        &attributes,
        0) != FALSE);
    CHECK(SetHandleInformation(resources.child_stderr_read.get(), HANDLE_FLAG_INHERIT, 0) != FALSE);

    const auto runtime = std::filesystem::path(QWEN_TTS_FAKE_RUNTIME_DIR);
    std::wstring command = L"\"" +
        std::filesystem::path(QWEN_TTS_NATIVE_WORKER_EXE).wstring() + L"\"";
    command += L" --runtime-dir \"" + runtime.wstring() + L"\"";
    command += L" --stream-max-chunk-frames 4";
    command += L" --talker-model \"" + (runtime / "talker.gguf").wstring() + L"\"";
    command += L" --codec-model \"" + (runtime / "codec.gguf").wstring() + L"\"";
    command += L" --max-admitted-requests 16";
    std::vector<wchar_t> command_line(command.begin(), command.end());
    command_line.push_back(L'\0');

    STARTUPINFOW startup{};
    startup.cb = sizeof(startup);
    startup.dwFlags = STARTF_USESTDHANDLES;
    startup.hStdInput = resources.child_stdin_read.get();
    startup.hStdOutput = resources.child_stdout_write.get();
    startup.hStdError = resources.child_stderr_write.get();
    PROCESS_INFORMATION process_info{};
    CHECK(CreateProcessW(
        nullptr,
        command_line.data(),
        nullptr,
        nullptr,
        TRUE,
        CREATE_NO_WINDOW,
        nullptr,
        nullptr,
        &startup,
        &process_info) != FALSE);
    resources.process.reset(process_info.hProcess);
    resources.process_thread.reset(process_info.hThread);
    resources.child_stdin_read.reset();
    resources.child_stdout_write.reset();
    resources.child_stderr_write.reset();

    resources.stdout_reader = std::thread(
        drain_pipe,
        resources.child_stdout_read.get(),
        &stdout_capture);
    resources.stderr_reader = std::thread(
        drain_pipe,
        resources.child_stderr_read.get(),
        &stderr_capture);

    CHECK(write_all(
        resources.child_stdin_write.get(),
        control_frame(0, ControlMessage{HelloMessage{"stdout-integrity", "0.2.0"}})));
    // This is the original timing-sensitive sequence: two requests are sent
    // back-to-back, then the late cancel and shutdown are sent on a bounded
    // delay without waiting for terminal events first.
    std::this_thread::sleep_for(std::chrono::milliseconds(350));
    SynthesizeMessage synthesis;
    synthesis.text = "native stdout integrity";
    CHECK(write_all(resources.child_stdin_write.get(), control_frame(100, ControlMessage{synthesis})));
    CHECK(write_all(resources.child_stdin_write.get(), control_frame(101, ControlMessage{synthesis})));
    std::this_thread::sleep_for(std::chrono::milliseconds(350));
    CHECK(write_all(resources.child_stdin_write.get(), control_frame(100, ControlMessage{CancelMessage{}})));
    std::this_thread::sleep_for(std::chrono::milliseconds(350));
    CHECK(write_all(resources.child_stdin_write.get(), control_frame(0, ControlMessage{ShutdownMessage{}})));
    resources.child_stdin_write.reset();

    CHECK(WaitForSingleObject(resources.process.get(), 15000) == WAIT_OBJECT_0);
    DWORD exit_code = 1;
    CHECK(GetExitCodeProcess(resources.process.get(), &exit_code) != FALSE);
    if (exit_code != 0) {
        std::vector<std::byte> stderr_bytes;
        {
            std::lock_guard<std::mutex> lock(stderr_capture.mutex);
            stderr_bytes = stderr_capture.bytes;
        }
        std::cerr << "native worker exit code: " << exit_code << "\n"
                  << "stderr:\n"
                  << std::string(reinterpret_cast<const char*>(stderr_bytes.data()), stderr_bytes.size())
                  << '\n';
    }
    CHECK(exit_code == 0);
    resources.stdout_reader.join();
    resources.stderr_reader.join();
    resources.child_stdout_read.reset();
    resources.child_stderr_read.reset();
    resources.process_thread.reset();
    resources.process.reset();

    std::vector<std::byte> stderr_bytes;
    {
        std::lock_guard<std::mutex> lock(stderr_capture.mutex);
        stderr_bytes = stderr_capture.bytes;
    }
    const std::string stderr_text(
        reinterpret_cast<const char*>(stderr_bytes.data()), stderr_bytes.size());
    std::istringstream stderr_lines(stderr_text);
    std::string stderr_line;
    while (std::getline(stderr_lines, stderr_line)) {
        if (stderr_line.rfind("qtb_metric ", 0) != 0) {
            continue;
        }
        try {
            const auto metric = nlohmann::json::parse(stderr_line.substr(10));
            CHECK(metric.is_object());
        }
        catch (const nlohmann::json::exception& error) {
            std::cerr << "invalid qtb_metric JSONL: " << error.what() << '\n'
                      << stderr_line << '\n';
            return 1;
        }
    }

    std::vector<std::byte> stdout_bytes;
    {
        std::lock_guard<std::mutex> lock(stdout_capture.mutex);
        stdout_bytes = stdout_capture.bytes;
    }
    FrameParser parser;
    parser.append(stdout_bytes);
    std::vector<Frame> frames;
    for (;;) {
        const auto result = parser.parse_next();
        if (result.status == ParseStatus::NeedMoreData) {
            break;
        }
        if (result.status != ParseStatus::FrameReady) {
            std::cerr << "iteration " << iteration << " parser error: " << result.message << '\n';
        }
        CHECK(result.status == ParseStatus::FrameReady);
        frames.push_back(result.frame);
    }
    CHECK(parser.buffered_size() == 0);

    const std::array<std::byte, 8> expected_chunk_a{
        std::byte{0x00}, std::byte{0x80}, std::byte{0x00}, std::byte{0xc0},
        std::byte{0x00}, std::byte{0x00}, std::byte{0x00}, std::byte{0x40}};
    const std::array<std::byte, 8> expected_chunk_b{
        std::byte{0x00}, std::byte{0x60}, std::byte{0xff}, std::byte{0x7f},
        std::byte{0x00}, std::byte{0x20}, std::byte{0x00}, std::byte{0x00}};
    std::array<std::size_t, 2> queued_counts{};
    std::array<std::size_t, 2> started_counts{};
    std::array<std::size_t, 2> terminal_counts{};
    std::size_t ready_count = 0;
    std::size_t shutdown_ack_count = 0;
    std::size_t audio_frames = 0;
    for (const auto& frame : frames) {
        const auto request_index = [](RequestId request_id) -> std::size_t {
            return request_id == 100 ? 0u : 1u;
        };
        if (frame.header.frame_type == FrameType::AudioPcm) {
            CHECK(frame.header.request_id == 100 || frame.header.request_id == 101);
            CHECK(frame.payload.size() == expected_chunk_a.size());
            const bool expected_pcm =
                std::equal(frame.payload.begin(), frame.payload.end(), expected_chunk_a.begin()) ||
                std::equal(frame.payload.begin(), frame.payload.end(), expected_chunk_b.begin());
            CHECK(expected_pcm);
            ++audio_frames;
            continue;
        }
        if (frame.header.frame_type == FrameType::ErrorJson) {
            const auto decoded = decode_error_message(frame.payload);
            CHECK(static_cast<bool>(decoded));
            CHECK(decoded.message.category == "request_error");
            CHECK(decoded.message.code == "unknown_request_id");
            CHECK(frame.header.request_id == 100);
            continue;
        }
        CHECK(frame.header.frame_type == FrameType::ControlJson);
        const auto decoded = decode_control_message(
            frame.payload,
            ControlMessageDirection::WorkerToClient);
        CHECK(static_cast<bool>(decoded));
        const auto type = control_message_type(decoded.message);
        if (type == ControlMessageType::Ready) {
            CHECK(frame.header.request_id == 0);
            const auto* ready = std::get_if<ReadyMessage>(&decoded.message);
            CHECK(ready != nullptr);
            CHECK(ready->capabilities.streaming);
            CHECK(ready->capabilities.cancellation);
            ++ready_count;
        } else if (type == ControlMessageType::ShutdownAck) {
            CHECK(frame.header.request_id == 0);
            CHECK(std::get_if<ShutdownAckMessage>(&decoded.message) != nullptr);
            ++shutdown_ack_count;
        } else {
            CHECK(frame.header.request_id == 100 || frame.header.request_id == 101);
            const auto index = request_index(frame.header.request_id);
            if (type == ControlMessageType::Queued) {
                CHECK(std::get_if<QueuedMessage>(&decoded.message) != nullptr);
                ++queued_counts[index];
            } else if (type == ControlMessageType::Started) {
                const auto* started = std::get_if<StartedMessage>(&decoded.message);
                CHECK(started != nullptr);
                CHECK(started->audio_format.sample_format == "s16le");
                CHECK(started->audio_format.sample_rate == 24000);
                CHECK(started->audio_format.channels == 1);
                ++started_counts[index];
            } else if (type == ControlMessageType::Completed) {
                const auto* completed = std::get_if<CompletedMessage>(&decoded.message);
                CHECK(completed != nullptr);
                CHECK(completed->has_execution_outcome);
                CHECK(completed->execution_outcome == "natural_eos");
                ++terminal_counts[index];
            } else if (type == ControlMessageType::Cancelled) {
                CHECK(std::get_if<CancelledMessage>(&decoded.message) != nullptr);
                ++terminal_counts[index];
            } else {
                CHECK(false);
            }
        }
    }
    CHECK(ready_count == 1);
    CHECK(shutdown_ack_count == 1);
    CHECK(queued_counts[0] == 1);
    CHECK(queued_counts[1] == 1);
    CHECK(terminal_counts[0] == 1);
    CHECK(terminal_counts[1] == 1);
    CHECK(started_counts[0] <= 1);
    CHECK(started_counts[1] <= 1);
    CHECK(audio_frames <= 4);
    return 0;
}

int main() {
    CHECK(run_parser_eof_regressions() == 0);
    for (int iteration = 0; iteration < 10; ++iteration) {
        if (run_pipe_integrity_case(iteration) != 0) {
            return 1;
        }
    }
    return 0;
}
