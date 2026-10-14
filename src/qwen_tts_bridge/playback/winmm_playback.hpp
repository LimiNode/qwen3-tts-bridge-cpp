#pragma once

#define WIN32_LEAN_AND_MEAN
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <mmsystem.h>

#include <algorithm>
#include <array>
#include <chrono>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <functional>
#include <iomanip>
#include <limits>
#include <memory>
#include <mutex>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>
#include <vector>

#include <qwen_tts_bridge/audio.hpp>
#include <qwen_tts_bridge/data.hpp>

namespace qwen_tts_bridge::playback {

using qwen_tts_bridge::AudioFormat;
using qwen_tts_bridge::PcmChunk;
using qwen_tts_bridge::RequestId;
using qwen_tts_bridge::audio::PlayoutBuffer;
/// \brief Physical playback position on the player-owned sample clock.
///
/// The optional speech-animation adapter may convert this neutral DTO to its
/// own integration type. The WinMM module deliberately does not depend on
/// that optional subsystem.
struct PlaybackCursorSnapshot {
    std::uint64_t playback_epoch = 0;
    RequestId request_id = 0;
    std::uint64_t utterance_sample = 0;
    std::uint32_t sample_rate = 0;
    bool position_available = false;
};

enum class MockPlaybackFailureStage {
    Prepare,
    Write,
    Reset,
    Close,
};

struct PlaybackChunkMetric {
    double arrival_ms = 0.0;
    std::optional<double> inter_arrival_ms;
    double admission_ms = 0.0;
    double backpressure_wait_ms = 0.0;
    double audio_duration_ms = 0.0;
    double queued_audio_before_ms = 0.0;
    double queued_audio_after_ms = 0.0;
    bool queue_empty_before_later_chunk = false;
};

struct PlaybackInterruptionDiagnostic {
    std::size_t event_index = 0;
    std::uint32_t requested_fade_ms = 0;
    std::uint64_t old_request_id = 0;
    std::uint64_t new_request_id = 0;
    std::string old_terminal_state;
    std::string new_terminal_state;
    bool cursor_available = false;
    std::uint64_t cursor_frame = 0;
    std::uint64_t selected_buffer_start_frame = 0;
    std::uint64_t selected_buffer_frame_count = 0;
    std::uint64_t selected_local_offset_frames = 0;
    std::uint64_t queued_buffer_count = 0;
    double queued_audio_ms = 0.0;
    std::uint64_t submitted_head_frame = 0;
    std::uint64_t producer_ahead_frames = 0;
    std::uint64_t fade_frame_count = 0;
    bool waveout_reset_called = false;
    std::optional<double> waveout_reset_started_ms;
    std::optional<double> waveout_reset_completed_ms;
    std::optional<double> interruption_completed_ms;
};

class WprPlaybackMarkers final {
public:
    WprPlaybackMarkers() = default;

    WprPlaybackMarkers(const WprPlaybackMarkers&) = delete;
    WprPlaybackMarkers& operator=(const WprPlaybackMarkers&) = delete;

    void request_start() const {
        write(L"qwen_tts_bridge.playback.request_start");
    }

    void queue_empty_before_later_chunk(std::size_t chunk_index) const {
        write(
            L"qwen_tts_bridge.playback.queue_empty_before_later_chunk index=" +
            std::to_wstring(chunk_index));
    }

private:
    static std::wstring quote_argument(const std::wstring& value) {
        return L"\"" + value + L"\"";
    }

    void write(const std::wstring& marker) const {
        std::array<wchar_t, MAX_PATH> system_directory{};
        const UINT length = GetSystemDirectoryW(
            system_directory.data(), static_cast<UINT>(system_directory.size()));
        if (length == 0 || length >= system_directory.size()) {
            throw std::runtime_error("failed to resolve the system WPR executable path");
        }

        const std::wstring executable =
            std::wstring(system_directory.data(), length) + L"\\wpr.exe";
        std::wstring command_line = quote_argument(executable) + L" -marker " +
            quote_argument(marker);
        STARTUPINFOW startup_info{};
        startup_info.cb = sizeof(startup_info);
        PROCESS_INFORMATION process_info{};
        if (!CreateProcessW(
                executable.c_str(),
                command_line.data(),
                nullptr,
                nullptr,
                false,
                CREATE_NO_WINDOW,
                nullptr,
                nullptr,
                &startup_info,
                &process_info)) {
            throw std::runtime_error("failed to start wpr.exe for playback marker");
        }
        CloseHandle(process_info.hThread);
        const DWORD wait_result = WaitForSingleObject(process_info.hProcess, 30000);
        if (wait_result != WAIT_OBJECT_0) {
            CloseHandle(process_info.hProcess);
            throw std::runtime_error("timed out while writing playback WPR marker");
        }
        DWORD exit_code = 0;
        const bool completed = GetExitCodeProcess(process_info.hProcess, &exit_code) != FALSE;
        CloseHandle(process_info.hProcess);
        if (!completed || exit_code != 0) {
            throw std::runtime_error("wpr.exe failed to write playback marker");
        }
    }
};

class PlaybackMetrics final {
public:
    explicit PlaybackMetrics(
        WprPlaybackMarkers* etw_markers = nullptr)
        : etw_markers_(etw_markers) {
    }

    void begin_request() {
        std::lock_guard<std::mutex> lock(mutex_);
        started_at_ = std::chrono::steady_clock::now();
        first_waveout_submission_ms_.reset();
        chunks_.clear();
        playback_completed_ = false;
        if (etw_markers_ != nullptr) {
            etw_markers_->request_start();
            ++etw_playback_marker_count_;
        }
    }

    void mark_first_waveout_submission() {
        std::lock_guard<std::mutex> lock(mutex_);
        if (started_at_.has_value() && !first_waveout_submission_ms_.has_value()) {
            first_waveout_submission_ms_ = elapsed_ms(started_at_.value(), std::chrono::steady_clock::now());
        }
    }

    [[nodiscard]] std::optional<std::size_t> record_chunk(
        std::chrono::steady_clock::time_point callback_arrival,
        std::chrono::steady_clock::time_point admission,
        double audio_duration_ms,
        double queued_audio_before_ms,
        double queued_audio_after_ms,
        bool queue_empty_before_later_chunk) {
        std::lock_guard<std::mutex> lock(mutex_);
        if (!started_at_.has_value()) {
            return std::nullopt;
        }

        const double arrival_ms =
            elapsed_ms(started_at_.value(), callback_arrival);
        const double admission_ms =
            elapsed_ms(started_at_.value(), admission);
        PlaybackChunkMetric metric;
        metric.arrival_ms = arrival_ms;
        metric.admission_ms = admission_ms;
        metric.backpressure_wait_ms = admission_ms - arrival_ms;
        metric.audio_duration_ms = audio_duration_ms;
        metric.queued_audio_before_ms = queued_audio_before_ms;
        metric.queued_audio_after_ms = queued_audio_after_ms;
        metric.queue_empty_before_later_chunk = queue_empty_before_later_chunk;
        if (!chunks_.empty()) {
            metric.inter_arrival_ms = arrival_ms - chunks_.back().arrival_ms;
        }
        chunks_.push_back(metric);
        if (queue_empty_before_later_chunk) {
            return chunks_.size() - 1;
        }
        return std::nullopt;
    }

    void mark_queue_empty_after_submit(std::size_t chunk_index) {
        std::lock_guard<std::mutex> lock(mutex_);
        if (etw_markers_ != nullptr) {
            etw_markers_->queue_empty_before_later_chunk(chunk_index);
            ++etw_playback_marker_count_;
        }
    }

    void mark_playback_completed() {
        std::lock_guard<std::mutex> lock(mutex_);
        playback_completed_ = true;
    }

    void write_json_file(const std::string& file_name) const {
        std::vector<PlaybackChunkMetric> chunks;
        bool playback_completed = false;
        std::optional<double> first_waveout_submission_ms;
        std::size_t etw_playback_marker_count = 0;
        {
            std::lock_guard<std::mutex> lock(mutex_);
            if (!started_at_.has_value()) {
                throw std::runtime_error("playback metrics were not started");
            }
            chunks = chunks_;
            playback_completed = playback_completed_;
            first_waveout_submission_ms = first_waveout_submission_ms_;
            etw_playback_marker_count = etw_playback_marker_count_;
        }

        std::size_t queue_empty_before_later_chunk_count = 0;
        double total_audio_duration_ms = 0.0;
        for (const PlaybackChunkMetric& chunk : chunks) {
            total_audio_duration_ms += chunk.audio_duration_ms;
            if (chunk.queue_empty_before_later_chunk) {
                ++queue_empty_before_later_chunk_count;
            }
        }

        std::ostringstream json;
        json << std::fixed << std::setprecision(3);
        json << "{\n"
             << "  \"schema_version\": 2,\n"
             << "  \"measurement\": \"waveout_queue_starvation_proxy\",\n"
             << "  \"first_waveout_submission_ms\": ";
        if (first_waveout_submission_ms.has_value()) {
            json << first_waveout_submission_ms.value();
        }
        else {
            json << "null";
        }
        json << ",\n"
             << "  \"etw_playback_markers_enabled\": "
             << (etw_markers_ != nullptr ? "true" : "false") << ",\n"
             << "  \"etw_playback_marker_count\": " << etw_playback_marker_count << ",\n"
             << "  \"playback_completed\": " << (playback_completed ? "true" : "false") << ",\n"
             << "  \"audio_chunk_count\": " << chunks.size() << ",\n"
             << "  \"total_audio_duration_ms\": " << total_audio_duration_ms << ",\n"
             << "  \"queue_empty_before_later_chunk_count\": "
             << queue_empty_before_later_chunk_count << ",\n"
             << "  \"chunks\": [\n";
        for (std::size_t index = 0; index < chunks.size(); ++index) {
            const PlaybackChunkMetric& chunk = chunks[index];
            json << "    {\"arrival_ms\": " << chunk.arrival_ms << ", \"inter_arrival_ms\": ";
            if (chunk.inter_arrival_ms.has_value()) {
                json << chunk.inter_arrival_ms.value();
            }
            else {
                json << "null";
            }
            json << ", \"admission_ms\": " << chunk.admission_ms
                 << ", \"backpressure_wait_ms\": " << chunk.backpressure_wait_ms
                 << ", \"audio_duration_ms\": " << chunk.audio_duration_ms
                 << ", \"queued_audio_before_ms\": " << chunk.queued_audio_before_ms
                 << ", \"queued_audio_after_ms\": " << chunk.queued_audio_after_ms
                 << ", \"queue_empty_before_later_chunk\": "
                 << (chunk.queue_empty_before_later_chunk ? "true" : "false") << "}";
            if (index + 1 != chunks.size()) {
                json << ',';
            }
            json << '\n';
        }
        json << "  ]\n}\n";

        const std::filesystem::path target = std::filesystem::u8path(file_name);
        if (std::filesystem::exists(target)) {
            throw std::runtime_error("refusing to overwrite existing playback metrics file: " + file_name);
        }
        const std::filesystem::path temporary =
            std::filesystem::path(
                target.native() + L".tmp." + std::to_wstring(GetCurrentProcessId()));
        try {
            std::ofstream output(temporary, std::ios::binary | std::ios::trunc);
            if (!output) {
                throw std::runtime_error("failed to open playback metrics file: " + temporary.string());
            }
            output << json.str();
            output.close();
            if (!output) {
                throw std::runtime_error("failed to write playback metrics file: " + temporary.string());
            }
            std::filesystem::rename(temporary, target);
        }
        catch (...) {
            std::error_code ignored;
            std::filesystem::remove(temporary, ignored);
            throw;
        }
    }

private:
    static double elapsed_ms(
        std::chrono::steady_clock::time_point start,
        std::chrono::steady_clock::time_point end) {
        return std::chrono::duration<double, std::milli>(end - start).count();
    }

    mutable std::mutex mutex_;
    std::optional<std::chrono::steady_clock::time_point> started_at_;
    std::optional<double> first_waveout_submission_ms_;
    std::vector<PlaybackChunkMetric> chunks_;
    bool playback_completed_ = false;
    WprPlaybackMarkers* etw_markers_ = nullptr;
    std::size_t etw_playback_marker_count_ = 0;
};

enum class PlaybackSinkMode {
    WaveOut,
    Disabled,
    Mock,
};

class WaveOutPlayer final {
public:
    static constexpr double kMaxQueuedAudioMs = 250.0;

    explicit WaveOutPlayer(
        PlaybackSinkMode sink_mode,
        PlaybackMetrics* metrics = nullptr,
        std::size_t prebuffer_chunks = 1,
        std::optional<std::size_t> mock_fail_after_submissions = std::nullopt,
        std::optional<MockPlaybackFailureStage> mock_failure_stage = std::nullopt);

    ~WaveOutPlayer();

    WaveOutPlayer(const WaveOutPlayer&) = delete;
    WaveOutPlayer& operator=(const WaveOutPlayer&) = delete;

    void enqueue(std::uint64_t playback_epoch, const PcmChunk& chunk);

    /// Stops queued and currently playing audio, invalidating prior callback epochs.
    /// It never cancels worker inference.
    [[nodiscard]] std::uint64_t reset();

    /// Resets playback only when the caller still owns the expected epoch.
    ///
    /// A stale callback may finish after a replacement request has already
    /// started. In that case it must not reset the newer playback session.
    [[nodiscard]] bool reset_if_epoch(std::uint64_t expected_epoch);

    [[nodiscard]] std::uint64_t playback_epoch() const;

    void set_reset_wait_hook_for_test(std::function<void()> hook);

    [[nodiscard]] std::size_t buffered_chunk_count_for_test() const;

    [[nodiscard]] std::uint64_t next_stream_frame_for_test() const;

    [[nodiscard]] bool unhealthy_for_test() const;

    void close_for_test() noexcept;

    /// Stops playback and returns a short fade built from the samples nearest
    /// the sink's current playout cursor. Buffered producer-side PCM that has
    /// not reached the device is discarded.
    std::pair<std::uint64_t, std::optional<PcmChunk>> interrupt_with_fade(
        std::uint32_t fade_ms,
        RequestId old_request_id = 0);

    std::optional<std::pair<std::uint64_t, std::optional<PcmChunk>>>
    interrupt_with_fade_if_epoch(
        std::uint64_t expected_epoch,
        std::uint32_t fade_ms,
        RequestId old_request_id = 0);

private:
    std::pair<std::uint64_t, std::optional<PcmChunk>> interrupt_with_fade_locked(
        std::unique_lock<std::mutex>& lock,
        std::uint32_t fade_ms,
        RequestId old_request_id);

public:

    void note_request_started(RequestId request_id);

    void note_request_terminal(RequestId request_id, const char* terminal_state);

    PlaybackCursorSnapshot playback_cursor_snapshot(
        std::uint64_t playback_epoch,
        RequestId request_id) const;

    void write_interruption_diagnostics_file(const std::string& file_name) const;

private:
    std::uint64_t reset_locked(
        std::unique_lock<std::mutex>& lock,
        PlaybackInterruptionDiagnostic* diagnostic = nullptr);

public:
    void wait_until_idle(std::chrono::milliseconds timeout);

private:
    struct Buffer {
        std::vector<std::byte> bytes;
        WAVEHDR header{};
        bool prepared = false;
        double duration_ms = 0.0;
        RequestId request_id = 0;
        std::uint64_t utterance_first_sample = 0;
        std::uint64_t start_frame = 0;
        std::uint64_t frame_count = 0;
        std::optional<std::chrono::steady_clock::time_point> mock_start;
        std::optional<std::chrono::steady_clock::time_point> mock_completion;
    };

    static bool formats_match(const AudioFormat& left, const AudioFormat& right);

    static void check_mmresult(MMRESULT result, const char* operation);

    static double pcm_duration_ms(const AudioFormat& format, std::size_t byte_count);

    static std::size_t pcm_frame_bytes(const AudioFormat& format);

    static std::uint64_t pcm_frame_count(
        const AudioFormat& format,
        std::size_t byte_count);

    std::optional<std::uint64_t> device_position_locked() const;

    void reset_stream_position_locked();

    double elapsed_since_start_ms(std::chrono::steady_clock::time_point value) const;

    std::optional<PcmChunk> interruption_tail_locked(
        std::uint32_t fade_ms,
        PlaybackInterruptionDiagnostic& diagnostic);

    double queued_audio_duration_ms_locked() const;

    std::optional<std::uint64_t> current_playout_cursor_frame_locked() const;

    double queued_audio_ahead_ms_locked() const;

    void validate_pending_format_locked(const AudioFormat& format);

    void flush_pending_locked();

    bool should_inject_mock_failure(MockPlaybackFailureStage stage);

    void clear_pending_locked();

    void abandon_driver_owned_resources_locked() noexcept;

    void throw_if_unhealthy_locked() const;

    void unprepare_header_or_fail_locked(Buffer& buffer);

    void open_or_validate_locked(const AudioFormat& format);

    void reap_finished_locked();

    void close_noexcept() noexcept;

    mutable std::mutex mutex_;
    HWAVEOUT m_handle = nullptr;
    AudioFormat m_format;
    std::vector<std::unique_ptr<Buffer>> buffers_;
    std::vector<std::unique_ptr<Buffer>> pending_buffers_;
    std::vector<std::unique_ptr<Buffer>> orphaned_buffers_;
    std::optional<AudioFormat> pending_format_;
    std::uint64_t playback_epoch_ = 1;
    PlaybackSinkMode sink_mode_ = PlaybackSinkMode::WaveOut;
    std::size_t prebuffer_chunks_ = 1;
    bool playback_started_ = false;
    PlaybackMetrics* metrics_ = nullptr;
    std::uint64_t next_stream_frame_ = 0;
    std::uint64_t device_position_base_ = 0;
    bool device_position_base_valid_ = false;
    const std::chrono::steady_clock::time_point started_at_ =
        std::chrono::steady_clock::now();
    std::vector<PlaybackInterruptionDiagnostic> interruption_diagnostics_;
    std::optional<std::size_t> last_interruption_diagnostic_index_;
    std::uint64_t late_audio_after_terminal_count_ = 0;
    std::optional<std::size_t> mock_fail_after_submissions_;
    MockPlaybackFailureStage mock_failure_stage_ = MockPlaybackFailureStage::Write;
    std::size_t mock_submission_count_ = 0;
    bool mock_failure_injected_ = false;
    std::function<void()> reset_wait_hook_for_test_;
    bool unhealthy_ = false;
    std::string unhealthy_reason_;
};


} // namespace qwen_tts_bridge::playback
