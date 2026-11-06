#include "stdout_writer.hpp"

#include <algorithm>
#include <limits>

namespace qwen_tts_bridge::native_worker {

StdoutWriteResult write_stdout_frame(
    HANDLE stdout_handle,
    const std::vector<std::byte>& frame) {
    if (stdout_handle == nullptr || stdout_handle == INVALID_HANDLE_VALUE) {
        return {false, 0, ERROR_INVALID_HANDLE};
    }

    std::size_t offset = 0;
    while (offset < frame.size()) {
        const auto remaining = frame.size() - offset;
        const auto request_size = static_cast<DWORD>(std::min<std::size_t>(
            remaining,
            static_cast<std::size_t>(std::numeric_limits<DWORD>::max())));
        DWORD written = 0;
        if (!WriteFile(
                stdout_handle,
                frame.data() + offset,
                request_size,
                &written,
                nullptr)) {
            return {false, offset + written, GetLastError()};
        }
        if (written == 0) {
            return {false, offset, ERROR_WRITE_FAULT};
        }
        offset += written;
    }
    return {true, offset, ERROR_SUCCESS};
}

} // namespace qwen_tts_bridge::native_worker
