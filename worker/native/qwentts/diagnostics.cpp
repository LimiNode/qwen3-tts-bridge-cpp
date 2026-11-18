#include "diagnostics.hpp"

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <condition_variable>
#include <cstddef>
#include <cstdint>
#include <deque>
#include <mutex>
#include <string>
#include <thread>
#include <utility>

namespace qwen_tts_bridge::native_worker {
namespace {

class DiagnosticWriter final {
public:
    DiagnosticWriter()
        : thread_([this]() { run(); }) {}

    void enqueue(std::string_view line) noexcept {
        try {
            std::string record(line);
            record.push_back('\n');
            if (record.size() > max_record_bytes_) {
                std::lock_guard<std::mutex> lock(mutex_);
                ++dropped_records_;
                return;
            }
            {
                std::lock_guard<std::mutex> lock(mutex_);
                if (stopped_ || queued_bytes_ + record.size() > max_queue_bytes_ ||
                    queue_.size() >= max_records_) {
                    ++dropped_records_;
                    return;
                }
                queued_bytes_ += record.size();
                queue_.push_back(std::move(record));
            }
            condition_.notify_one();
        }
        catch (...) {
            std::lock_guard<std::mutex> lock(mutex_);
            ++dropped_records_;
        }
    }

    bool flush(std::chrono::milliseconds timeout) noexcept {
        try {
            std::unique_lock<std::mutex> lock(mutex_);
            return drained_condition_.wait_for(lock, timeout, [this]() {
                return queue_.empty() && !write_in_progress_;
            });
        }
        catch (...) {
            return false;
        }
    }

private:
    void run() noexcept {
        const HANDLE stderr_handle = GetStdHandle(STD_ERROR_HANDLE);
        for (;;) {
            std::string record;
            {
                std::unique_lock<std::mutex> lock(mutex_);
                condition_.wait(lock, [this]() { return stopped_ || !queue_.empty(); });
                if (queue_.empty() && stopped_) {
                    return;
                }
                record = std::move(queue_.front());
                queue_.pop_front();
                queued_bytes_ -= record.size();
                write_in_progress_ = true;
                drained_condition_.notify_all();
            }

            bool success = stderr_handle != nullptr && stderr_handle != INVALID_HANDLE_VALUE;
            std::size_t offset = 0;
            while (success && offset < record.size()) {
                DWORD written = 0;
                success = WriteFile(
                    stderr_handle,
                    record.data() + offset,
                    static_cast<DWORD>(record.size() - offset),
                    &written,
                    nullptr) != FALSE;
                if (success && written == 0) {
                    success = false;
                }
                if (success) {
                    offset += written;
                }
            }

            {
                std::lock_guard<std::mutex> lock(mutex_);
                write_in_progress_ = false;
                if (!success) {
                    // A closed diagnostics pipe is terminal for this process.
                    // Drop the bounded backlog and let protocol/shutdown paths
                    // continue independently of stderr availability.
                    queue_.clear();
                    queued_bytes_ = 0;
                    stopped_ = true;
                }
                drained_condition_.notify_all();
            }
            if (!success) {
                condition_.notify_all();
                return;
            }
        }
    }

    static constexpr std::size_t max_records_ = 64;
    static constexpr std::size_t max_record_bytes_ = 1u * 1024u * 1024u + 4096u;
    static constexpr std::size_t max_queue_bytes_ = 4u * 1024u * 1024u;

    std::mutex mutex_;
    std::condition_variable condition_;
    std::condition_variable drained_condition_;
    std::deque<std::string> queue_;
    std::size_t queued_bytes_ = 0;
    std::uint64_t dropped_records_ = 0;
    bool write_in_progress_ = false;
    bool stopped_ = false;
    std::thread thread_;
};

// The diagnostics worker intentionally lives until process termination.  This
// avoids joining a thread that may be blocked in a synchronous WriteFile on a
// stalled anonymous pipe, and its owning object therefore cannot be destroyed
// while the worker is still using it.  The bounded queue is the only memory
// retained by the worker, and protocol/shutdown code never waits for it.
DiagnosticWriter* diagnostic_writer() noexcept {
    try {
        static DiagnosticWriter* writer = new DiagnosticWriter();
        return writer;
    }
    catch (...) {
        return nullptr;
    }
}

} // namespace

void write_diagnostic_line(std::string_view line) noexcept {
    if (auto* writer = diagnostic_writer(); writer != nullptr) {
        writer->enqueue(line);
    }
}

bool flush_diagnostics(std::chrono::milliseconds timeout) noexcept {
    if (auto* writer = diagnostic_writer(); writer != nullptr) {
        return writer->flush(timeout);
    }
    return false;
}

} // namespace qwen_tts_bridge::native_worker
