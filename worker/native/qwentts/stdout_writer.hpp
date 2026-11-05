#pragma once

#include <windows.h>

#include <cstddef>
#include <vector>

namespace qwen_tts_bridge::native_worker {

struct StdoutWriteResult {
    bool success = false;
    std::size_t bytes_written = 0;
    DWORD error_code = ERROR_SUCCESS;
};

/// Write one complete QTB frame without closing the process-owned stdout handle.
StdoutWriteResult write_stdout_frame(
    HANDLE stdout_handle,
    const std::vector<std::byte>& frame);

} // namespace qwen_tts_bridge::native_worker
