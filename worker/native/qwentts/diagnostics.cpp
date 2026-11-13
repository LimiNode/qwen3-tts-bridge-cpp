#include "diagnostics.hpp"

#include <iostream>
#include <mutex>
#include <string>

namespace qwen_tts_bridge::native_worker {
namespace {

std::mutex& diagnostics_mutex() {
    static std::mutex mutex;
    return mutex;
}

} // namespace

void write_diagnostic_line(std::string_view line) noexcept {
    try {
        const std::lock_guard<std::mutex> lock(diagnostics_mutex());
        std::cerr.write(line.data(), static_cast<std::streamsize>(line.size()));
        std::cerr.put('\n');
        std::cerr.flush();
    }
    catch (...) {
        // Diagnostics must never change worker control flow.
    }
}

} // namespace qwen_tts_bridge::native_worker
