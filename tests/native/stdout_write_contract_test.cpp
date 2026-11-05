#include "stdout_writer.hpp"

#include <windows.h>

#include <array>
#include <cstddef>
#include <cstdint>
#include <iostream>
#include <thread>
#include <vector>

namespace {

bool check(bool value, const char* expression, int line) {
    if (!value) {
        std::cerr << "CHECK failed: " << expression << " at line " << line << '\n';
    }
    return value;
}

#define CHECK(value) if (!check((value), #value, __LINE__)) return 1

struct PipeResources {
    HANDLE read_handle = nullptr;
    HANDLE write_handle = nullptr;
    std::thread reader;

    ~PipeResources() {
        cleanup();
    }

    void cleanup() noexcept {
        if (write_handle != nullptr && write_handle != INVALID_HANDLE_VALUE) {
            CloseHandle(write_handle);
            write_handle = nullptr;
        }
        if (reader.joinable()) {
            reader.join();
        }
        if (read_handle != nullptr && read_handle != INVALID_HANDLE_VALUE) {
            CloseHandle(read_handle);
            read_handle = nullptr;
        }
    }
};

} // namespace

int main() {
    CHECK(!qwen_tts_bridge::native_worker::write_stdout_frame(
        INVALID_HANDLE_VALUE,
        std::vector<std::byte>(1, std::byte{0})).success);

    SECURITY_ATTRIBUTES attributes{};
    attributes.nLength = sizeof(attributes);
    attributes.bInheritHandle = TRUE;
    PipeResources resources;
    CHECK(CreatePipe(&resources.read_handle, &resources.write_handle, &attributes, 4096) != FALSE);
    CHECK(SetHandleInformation(resources.read_handle, HANDLE_FLAG_INHERIT, 0) != FALSE);

    std::vector<std::byte> expected(2u * 1024u * 1024u);
    for (std::size_t index = 0; index < expected.size(); ++index) {
        expected[index] = static_cast<std::byte>(index % 251u);
    }

    std::vector<std::byte> received;
    resources.reader = std::thread([&]() {
        std::array<std::byte, 8192> buffer{};
        DWORD count = 0;
        while (ReadFile(
                   resources.read_handle,
                   buffer.data(),
                   static_cast<DWORD>(buffer.size()),
                   &count,
                   nullptr) != FALSE && count != 0) {
            received.insert(received.end(), buffer.begin(), buffer.begin() + count);
        }
    });

    const auto result = qwen_tts_bridge::native_worker::write_stdout_frame(
        resources.write_handle,
        expected);
    CHECK(result.success);
    CHECK(result.bytes_written == expected.size());
    CHECK(result.error_code == ERROR_SUCCESS);
    resources.cleanup();
    CHECK(received == expected);
    return 0;
}
