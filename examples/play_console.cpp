#include <qwen_tts_bridge/audio.hpp>

#include "play.hpp"

#define WIN32_LEAN_AND_MEAN
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>

#include <array>
#include <iostream>
#include <stdexcept>

namespace qwen_tts_examples::play {

std::string utf8_from_wide(const std::wstring& value) {
    if (value.empty()) {
        return {};
    }

    const int byte_count = WideCharToMultiByte(
        CP_UTF8,
        WC_ERR_INVALID_CHARS,
        value.data(),
        static_cast<int>(value.size()),
        nullptr,
        0,
        nullptr,
        nullptr);
    if (byte_count <= 0) {
        throw std::runtime_error("failed to convert console input to UTF-8");
    }

    std::string utf8(static_cast<std::size_t>(byte_count), '\0');
    if (WideCharToMultiByte(
            CP_UTF8,
            WC_ERR_INVALID_CHARS,
            value.data(),
            static_cast<int>(value.size()),
            utf8.data(),
            byte_count,
            nullptr,
            nullptr) <= 0) {
        throw std::runtime_error("failed to convert console input to UTF-8");
    }
    return utf8;
}

bool read_interactive_line(std::string& line) {
    const HANDLE input = GetStdHandle(STD_INPUT_HANDLE);
    DWORD console_mode = 0;
    if (input == INVALID_HANDLE_VALUE ||
        input == nullptr ||
        !GetConsoleMode(input, &console_mode)) {
        return static_cast<bool>(std::getline(std::cin, line));
    }

    std::array<wchar_t, 4096> wide_buffer{};
    DWORD characters_read = 0;
    if (!ReadConsoleW(
            input,
            wide_buffer.data(),
            static_cast<DWORD>(wide_buffer.size() - 1),
            &characters_read,
            nullptr)) {
        return false;
    }

    std::wstring wide_line(wide_buffer.data(), characters_read);
    while (!wide_line.empty() &&
           (wide_line.back() == L'\r' || wide_line.back() == L'\n')) {
        wide_line.pop_back();
    }
    line = utf8_from_wide(wide_line);
    return true;
}

} // namespace qwen_tts_examples::play
