#pragma once

#include <windows.h>

#include <cstddef>
#include <vector>

/// \file stdout_writer.hpp
/// \brief Publishes complete binary QTB frames to the native worker's stdout.
///
/// Native worker stdout is a protocol-only byte stream: human-readable output
/// must stay on stderr.  The writer uses the Win32 byte-oriented `WriteFile`
/// API so partial writes and write failures are observable.  This lets the
/// bounded output writer fail closed instead of allowing a truncated frame to
/// corrupt the stream seen by the bridge client.

namespace qwen_tts_bridge::native_worker {

/// \brief Result of one complete-frame publication attempt.
struct StdoutWriteResult {
    /// True only when every byte of the frame was accepted by `WriteFile`.
    bool success = false;

    /// Number of bytes accepted before success or failure.
    std::size_t bytes_written = 0;

    /// Win32 error from the failed call, or `ERROR_SUCCESS` on success.
    DWORD error_code = ERROR_SUCCESS;
};

/// \brief Writes one complete QTB frame to an existing process-owned handle.
///
/// The function retries until the complete frame is written, reports a
/// zero-progress write as `ERROR_WRITE_FAULT`, and never closes or replaces
/// `stdout_handle`.  Callers must serialize calls for one protocol stream.
///
/// \param stdout_handle Existing process-owned stdout handle.
/// \param frame Complete serialized QTB frame to publish.
/// \return Publication result with byte progress and a Win32 error code.
StdoutWriteResult write_stdout_frame(
    HANDLE stdout_handle,
    const std::vector<std::byte>& frame);

} // namespace qwen_tts_bridge::native_worker
