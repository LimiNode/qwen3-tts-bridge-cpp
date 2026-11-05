#include <qwen_tts_bridge/protocol/control.hpp>
#include <qwen_tts_bridge/protocol/framing.hpp>

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

std::size_t terminal_frame_count(const std::vector<std::byte>& bytes) {
    FrameParser parser;
    parser.append(bytes);
    std::size_t count = 0;
    for (;;) {
        const auto result = parser.parse_next();
        if (result.status != ParseStatus::FrameReady) {
            break;
        }
        if (result.frame.header.request_id != 100 && result.frame.header.request_id != 101) {
            continue;
        }
        const auto decoded = decode_control_message(
            result.frame.payload,
            ControlMessageDirection::WorkerToClient);
        if (decoded &&
            (control_message_type(decoded.message) == ControlMessageType::Completed ||
             control_message_type(decoded.message) == ControlMessageType::Cancelled)) {
            ++count;
        }
    }
    return count;
}

bool wait_for_terminal_frames(ByteCapture& capture) {
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(5);
    std::unique_lock<std::mutex> lock(capture.mutex);
    for (;;) {
        const auto snapshot = capture.bytes;
        lock.unlock();
        if (terminal_frame_count(snapshot) >= 2) {
            return true;
        }
        lock.lock();
        if (capture.changed.wait_until(lock, deadline) == std::cv_status::timeout) {
            return terminal_frame_count(capture.bytes) >= 2;
        }
    }
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

int main() {
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
    SynthesizeMessage synthesis;
    synthesis.text = "native stdout integrity";
    CHECK(write_all(resources.child_stdin_write.get(), control_frame(100, ControlMessage{synthesis})));
    CHECK(write_all(resources.child_stdin_write.get(), control_frame(101, ControlMessage{synthesis})));
    CHECK(wait_for_terminal_frames(stdout_capture));
    CHECK(write_all(resources.child_stdin_write.get(), control_frame(100, ControlMessage{CancelMessage{}})));
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
        CHECK(result.status == ParseStatus::FrameReady);
        frames.push_back(result.frame);
    }

    if (frames.size() != 12) {
        std::cerr << "native worker frame count: " << frames.size() << '\n';
        for (const auto& frame : frames) {
            std::cerr << "  type=" << static_cast<int>(frame.header.frame_type)
                      << " request_id=" << frame.header.request_id
                      << " payload=" << frame.payload.size();
            if (frame.header.frame_type == FrameType::ControlJson) {
                const auto decoded = decode_control_message(
                    frame.payload,
                    ControlMessageDirection::WorkerToClient);
                if (decoded) {
                    std::cerr << " control_type="
                              << static_cast<int>(control_message_type(decoded.message));
                }
            }
            std::cerr << '\n';
        }
    }
    CHECK(frames.size() == 12);
    CHECK(frames.front().header.request_id == 0);
    CHECK(frames.back().header.request_id == 0);
    CHECK(frames.back().header.frame_type == FrameType::ControlJson);
    std::size_t audio_frames = 0;
    std::size_t terminal_frames = 0;
    for (const auto& frame : frames) {
        CHECK(frame.header.frame_type != FrameType::ErrorJson);
        if (frame.header.frame_type == FrameType::AudioPcm) {
            ++audio_frames;
        }
        if (frame.header.request_id == 100 || frame.header.request_id == 101) {
            const auto decoded = decode_control_message(
                frame.payload,
                ControlMessageDirection::WorkerToClient);
            if (decoded && (control_message_type(decoded.message) == ControlMessageType::Completed ||
                            control_message_type(decoded.message) == ControlMessageType::Cancelled)) {
                ++terminal_frames;
            }
        }
    }
    CHECK(audio_frames == 4);
    CHECK(terminal_frames == 2);
    return 0;
}
