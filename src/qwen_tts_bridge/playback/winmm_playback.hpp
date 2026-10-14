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
#ifdef QWEN_TTS_BRIDGE_HAS_SPEECH_ANIMATION
#include <qwen_tts_bridge/integration/speech_animation/PlaybackAnimationRuntime.hpp>
#endif

namespace qwen_tts_bridge::playback {

using qwen_tts_bridge::AudioFormat;
using qwen_tts_bridge::PcmChunk;
using qwen_tts_bridge::RequestId;
using qwen_tts_bridge::audio::PlayoutBuffer;
#ifdef QWEN_TTS_BRIDGE_HAS_SPEECH_ANIMATION
using PlaybackCursorSnapshot = ::speech_animation::integration::PlaybackCursorSnapshot;
#endif

enum class MockPlaybackFailureStage {
    Prepare,
    Write,
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
        std::optional<MockPlaybackFailureStage> mock_failure_stage = std::nullopt)
        : sink_mode_(sink_mode),
          prebuffer_chunks_(prebuffer_chunks),
          metrics_(metrics),
          mock_fail_after_submissions_(mock_fail_after_submissions),
          mock_failure_stage_(mock_failure_stage.value_or(MockPlaybackFailureStage::Write)) {
        if (prebuffer_chunks_ == 0) {
            throw std::runtime_error("playback prebuffer must contain at least one chunk");
        }
    }

    ~WaveOutPlayer() {
        close_noexcept();
    }

    WaveOutPlayer(const WaveOutPlayer&) = delete;
    WaveOutPlayer& operator=(const WaveOutPlayer&) = delete;

    void enqueue(std::uint64_t playback_epoch, const PcmChunk& chunk) {
        const auto callback_arrival = std::chrono::steady_clock::now();
        if (sink_mode_ == PlaybackSinkMode::Disabled) {
            return;
        }
        if (chunk.format.sample_format != "s16le") {
            throw std::runtime_error("default-device playback requires s16le PCM");
        }
        if (chunk.format.sample_rate == 0 ||
            chunk.format.channels == 0 ||
            chunk.format.channels > std::numeric_limits<WORD>::max()) {
            throw std::runtime_error("invalid PCM format for default-device playback");
        }
        if (chunk.bytes.empty()) {
            return;
        }

        std::unique_lock<std::mutex> lock(mutex_);
        throw_if_unhealthy_locked();
        if (playback_epoch != playback_epoch_) {
            ++late_audio_after_terminal_count_;
            return;
        }
        while (playback_started_ &&
               queued_audio_ahead_ms_locked() >= kMaxQueuedAudioMs) {
            reap_finished_locked();
            if (queued_audio_ahead_ms_locked() < kMaxQueuedAudioMs) {
                break;
            }
            lock.unlock();
            std::this_thread::sleep_for(std::chrono::milliseconds(2));
            lock.lock();
            if (playback_epoch != playback_epoch_) {
                ++late_audio_after_terminal_count_;
                return;
            }
        }
        reap_finished_locked();
        validate_pending_format_locked(chunk.format);
        const double queued_audio_before_ms = queued_audio_ahead_ms_locked();
        const bool queue_empty_before_later_chunk =
            playback_started_ && buffers_.empty();
        const auto admission = std::chrono::steady_clock::now();

        auto buffer = std::make_unique<Buffer>();
        buffer->bytes = chunk.bytes;
        buffer->request_id = chunk.request_id;
        buffer->utterance_first_sample = chunk.first_sample;
        buffer->frame_count = pcm_frame_count(chunk.format, buffer->bytes.size());
        buffer->header.lpData = reinterpret_cast<LPSTR>(buffer->bytes.data());
        buffer->header.dwBufferLength = static_cast<DWORD>(buffer->bytes.size());
        buffer->duration_ms = pcm_duration_ms(chunk.format, buffer->bytes.size());

        pending_buffers_.push_back(std::move(buffer));
        std::optional<std::size_t> queue_empty_marker_index;
        if (metrics_ != nullptr) {
            queue_empty_marker_index = metrics_->record_chunk(
                callback_arrival,
                admission,
                pcm_duration_ms(chunk.format, chunk.bytes.size()),
                queued_audio_before_ms,
                queued_audio_ahead_ms_locked(),
                queue_empty_before_later_chunk);
        }
        if (playback_started_ || pending_buffers_.size() >= prebuffer_chunks_) {
            flush_pending_locked();
        }
        if (queue_empty_marker_index.has_value()) {
            metrics_->mark_queue_empty_after_submit(queue_empty_marker_index.value());
        }
    }

    /// Stops queued and currently playing audio, invalidating prior callback epochs.
    /// It never cancels worker inference.
    [[nodiscard]] std::uint64_t reset() {
        std::unique_lock<std::mutex> lock(mutex_);
        return reset_locked(lock);
    }

    /// Resets playback only when the caller still owns the expected epoch.
    ///
    /// A stale callback may finish after a replacement request has already
    /// started. In that case it must not reset the newer playback session.
    [[nodiscard]] bool reset_if_epoch(std::uint64_t expected_epoch) {
        std::unique_lock<std::mutex> lock(mutex_);
        if (playback_epoch_ != expected_epoch) {
            return false;
        }
        static_cast<void>(reset_locked(lock));
        return true;
    }

    [[nodiscard]] std::uint64_t playback_epoch() const {
        std::lock_guard<std::mutex> lock(mutex_);
        return playback_epoch_;
    }

    void set_reset_wait_hook_for_test(std::function<void()> hook) {
        std::lock_guard<std::mutex> lock(mutex_);
        reset_wait_hook_for_test_ = std::move(hook);
    }

    [[nodiscard]] std::size_t buffered_chunk_count_for_test() const {
        std::lock_guard<std::mutex> lock(mutex_);
        return buffers_.size() + pending_buffers_.size();
    }

    [[nodiscard]] std::uint64_t next_stream_frame_for_test() const {
        std::lock_guard<std::mutex> lock(mutex_);
        return next_stream_frame_;
    }

    /// Stops playback and returns a short fade built from the samples nearest
    /// the sink's current playout cursor. Buffered producer-side PCM that has
    /// not reached the device is discarded.
    std::pair<std::uint64_t, std::optional<PcmChunk>> interrupt_with_fade(
        std::uint32_t fade_ms,
        RequestId old_request_id = 0) {
        std::unique_lock<std::mutex> lock(mutex_);
        return interrupt_with_fade_locked(lock, fade_ms, old_request_id);
    }

    std::optional<std::pair<std::uint64_t, std::optional<PcmChunk>>>
    interrupt_with_fade_if_epoch(
        std::uint64_t expected_epoch,
        std::uint32_t fade_ms,
        RequestId old_request_id = 0) {
        std::unique_lock<std::mutex> lock(mutex_);
        if (playback_epoch_ != expected_epoch) {
            return std::nullopt;
        }
        return interrupt_with_fade_locked(lock, fade_ms, old_request_id);
    }

private:
    std::pair<std::uint64_t, std::optional<PcmChunk>> interrupt_with_fade_locked(
        std::unique_lock<std::mutex>& lock,
        std::uint32_t fade_ms,
        RequestId old_request_id) {
        const bool record_diagnostic = old_request_id != 0;
        if (sink_mode_ != PlaybackSinkMode::Disabled) {
            reap_finished_locked();
        }
        PlaybackInterruptionDiagnostic diagnostic;
        diagnostic.event_index = interruption_diagnostics_.size();
        diagnostic.requested_fade_ms = fade_ms;
        diagnostic.old_request_id = old_request_id;
        diagnostic.queued_buffer_count = buffers_.size();
        diagnostic.queued_audio_ms = queued_audio_ahead_ms_locked();
        diagnostic.submitted_head_frame = next_stream_frame_;
        std::optional<PcmChunk> tail;
        if (fade_ms != 0 && sink_mode_ != PlaybackSinkMode::Disabled) {
            tail = interruption_tail_locked(fade_ms, diagnostic);
        }
        const std::uint64_t playback_epoch =
            reset_locked(lock, record_diagnostic ? &diagnostic : nullptr);
        if (record_diagnostic) {
            diagnostic.interruption_completed_ms =
                elapsed_since_start_ms(std::chrono::steady_clock::now());
        }
        if (record_diagnostic && tail.has_value()) {
            diagnostic.fade_frame_count = pcm_frame_count(
                tail->format,
                tail->bytes.size());
        }
        if (record_diagnostic) {
            interruption_diagnostics_.push_back(std::move(diagnostic));
            last_interruption_diagnostic_index_ = interruption_diagnostics_.size() - 1;
        }
        return {playback_epoch, std::move(tail)};
    }

public:

    void note_request_started(RequestId request_id) {
        std::lock_guard<std::mutex> lock(mutex_);
        if (last_interruption_diagnostic_index_.has_value()) {
            interruption_diagnostics_[last_interruption_diagnostic_index_.value()].new_request_id =
                request_id;
            last_interruption_diagnostic_index_.reset();
        }
    }

    void note_request_terminal(RequestId request_id, const char* terminal_state) {
        std::lock_guard<std::mutex> lock(mutex_);
        for (auto& event : interruption_diagnostics_) {
            if (event.old_request_id == request_id && event.old_terminal_state.empty()) {
                event.old_terminal_state = terminal_state;
            }
            if (event.new_request_id == request_id && event.new_terminal_state.empty()) {
                event.new_terminal_state = terminal_state;
            }
        }
    }

#ifdef QWEN_TTS_BRIDGE_HAS_SPEECH_ANIMATION
    PlaybackCursorSnapshot playback_cursor_snapshot(
        std::uint64_t playback_epoch,
        RequestId request_id) const {
        std::lock_guard<std::mutex> lock(mutex_);
        PlaybackCursorSnapshot snapshot;
        snapshot.playback_epoch = playback_epoch;
        snapshot.request_id = request_id;
        if (playback_epoch != playback_epoch_ || request_id == 0 ||
            !playback_started_ || buffers_.empty()) {
            return snapshot;
        }
        const auto cursor_frame = current_playout_cursor_frame_locked();
        if (!cursor_frame.has_value()) {
            return snapshot;
        }
        const Buffer* selected = nullptr;
        std::uint64_t local_offset = 0;
        for (const auto& item : buffers_) {
            const Buffer& buffer = *item;
            const auto end = buffer.start_frame + buffer.frame_count;
            if (cursor_frame.value() < buffer.start_frame) {
                selected = &buffer;
                break;
            }
            if (cursor_frame.value() < end) {
                selected = &buffer;
                local_offset = cursor_frame.value() - buffer.start_frame;
                break;
            }
        }
        if (selected == nullptr || selected->request_id != request_id ||
            selected->utterance_first_sample >
                std::numeric_limits<std::uint64_t>::max() - local_offset) {
            return snapshot;
        }
        snapshot.utterance_sample =
            selected->utterance_first_sample + local_offset;
        snapshot.sample_rate = m_format.sample_rate;
        snapshot.position_available = snapshot.sample_rate != 0;
        return snapshot;
    }
#endif

    void write_interruption_diagnostics_file(const std::string& file_name) const {
        std::vector<PlaybackInterruptionDiagnostic> diagnostics;
        std::uint64_t late_audio_after_terminal_count = 0;
        {
            std::lock_guard<std::mutex> lock(mutex_);
            diagnostics = interruption_diagnostics_;
            late_audio_after_terminal_count = late_audio_after_terminal_count_;
        }
        std::ostringstream json;
        json << std::fixed << std::setprecision(3);
        json << "{\n"
             << "  \"schema_version\": 2,\n"
             << "  \"measurement\": \"waveout_interruption_cursor\",\n"
             << "  \"late_audio_after_terminal_count\": "
             << late_audio_after_terminal_count << ",\n"
             << "  \"events\": [\n";
        for (std::size_t index = 0; index < diagnostics.size(); ++index) {
            const auto& event = diagnostics[index];
            json << "    {\"event_index\": " << event.event_index
                 << ", \"requested_fade_ms\": " << event.requested_fade_ms
                 << ", \"old_request_id\": " << event.old_request_id
                 << ", \"new_request_id\": " << event.new_request_id
                 << ", \"old_terminal_state\": \"" << event.old_terminal_state
                 << "\", \"new_terminal_state\": \"" << event.new_terminal_state
                 << "\", \"cursor_available\": "
                 << (event.cursor_available ? "true" : "false")
                 << ", \"cursor_frame\": " << event.cursor_frame
                 << ", \"selected_buffer_start_frame\": "
                 << event.selected_buffer_start_frame
                 << ", \"selected_buffer_frame_count\": "
                 << event.selected_buffer_frame_count
                 << ", \"selected_local_offset_frames\": "
                 << event.selected_local_offset_frames
                 << ", \"queued_buffer_count\": " << event.queued_buffer_count
                 << ", \"queued_audio_ms\": " << event.queued_audio_ms
                 << ", \"submitted_head_frame\": " << event.submitted_head_frame
                 << ", \"producer_ahead_frames\": " << event.producer_ahead_frames
                 << ", \"fade_frame_count\": " << event.fade_frame_count
                 << ", \"waveout_reset_called\": "
                 << (event.waveout_reset_called ? "true" : "false")
                 << ", \"waveout_reset_started_ms\": ";
            if (event.waveout_reset_started_ms.has_value()) {
                json << event.waveout_reset_started_ms.value();
            }
            else {
                json << "null";
            }
            json << ", \"waveout_reset_completed_ms\": ";
            if (event.waveout_reset_completed_ms.has_value()) {
                json << event.waveout_reset_completed_ms.value();
            }
            else {
                json << "null";
            }
            json << ", \"interruption_completed_ms\": ";
            if (event.interruption_completed_ms.has_value()) {
                json << event.interruption_completed_ms.value();
            }
            else {
                json << "null";
            }
            json << "}";
            if (index + 1 != diagnostics.size()) {
                json << ',';
            }
            json << '\n';
        }
        json << "  ]\n}\n";
        const std::filesystem::path target = std::filesystem::u8path(file_name);
        if (std::filesystem::exists(target)) {
            throw std::runtime_error(
                "refusing to overwrite existing interruption diagnostics file: " +
                file_name);
        }
        const std::filesystem::path temporary =
            std::filesystem::path(
                target.native() + L".tmp." + std::to_wstring(GetCurrentProcessId()));
        try {
            std::ofstream output(temporary, std::ios::binary | std::ios::trunc);
            if (!output) {
                throw std::runtime_error(
                    "failed to open interruption diagnostics file: " + file_name);
            }
            output << json.str();
            output.close();
            if (!output) {
                throw std::runtime_error(
                    "failed to write interruption diagnostics file: " + file_name);
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
    std::uint64_t reset_locked(
        std::unique_lock<std::mutex>& lock,
        PlaybackInterruptionDiagnostic* diagnostic = nullptr) {
        ++playback_epoch_;
        if (playback_epoch_ == 0) {
            ++playback_epoch_;
        }
        const std::uint64_t reset_epoch = playback_epoch_;
        throw_if_unhealthy_locked();
        if (reset_wait_hook_for_test_) {
            auto hook = std::move(reset_wait_hook_for_test_);
            reset_wait_hook_for_test_ = {};
            lock.unlock();
            hook();
            lock.lock();
            if (playback_epoch_ != reset_epoch) {
                return reset_epoch;
            }
        }
        if (sink_mode_ == PlaybackSinkMode::Mock) {
            mock_submission_count_ = 0;
        }
        if (sink_mode_ == PlaybackSinkMode::Disabled) {
            reset_stream_position_locked();
            return reset_epoch;
        }
        if (sink_mode_ == PlaybackSinkMode::Mock) {
            buffers_.clear();
            clear_pending_locked();
            playback_started_ = false;
            reset_stream_position_locked();
            return reset_epoch;
        }
        if (m_handle == nullptr) {
            clear_pending_locked();
            playback_started_ = false;
            reset_stream_position_locked();
            return reset_epoch;
        }

        if (diagnostic != nullptr) {
            diagnostic->waveout_reset_called = true;
            diagnostic->waveout_reset_started_ms =
                elapsed_since_start_ms(std::chrono::steady_clock::now());
        }
        check_mmresult(waveOutReset(m_handle), "waveOutReset");
        if (diagnostic != nullptr) {
            diagnostic->waveout_reset_completed_ms =
                elapsed_since_start_ms(std::chrono::steady_clock::now());
        }
        const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(2);
        while (!buffers_.empty()) {
            reap_finished_locked();
            if (buffers_.empty()) {
                break;
            }
            if (std::chrono::steady_clock::now() >= deadline) {
                throw std::runtime_error("timed out waiting for default audio device reset");
            }
            lock.unlock();
            std::this_thread::sleep_for(std::chrono::milliseconds(5));
            lock.lock();
            if (playback_epoch_ != reset_epoch) {
                return reset_epoch;
            }
        }
        clear_pending_locked();
        playback_started_ = false;
        reset_stream_position_locked();
        return reset_epoch;
    }

public:
    void wait_until_idle(std::chrono::milliseconds timeout) {
        if (sink_mode_ == PlaybackSinkMode::Disabled) {
            return;
        }
        std::unique_lock<std::mutex> lock(mutex_);
        throw_if_unhealthy_locked();
        flush_pending_locked();
        const auto deadline = std::chrono::steady_clock::now() + timeout;
        while (!buffers_.empty()) {
            reap_finished_locked();
            if (buffers_.empty()) {
                return;
            }
            if (std::chrono::steady_clock::now() >= deadline) {
                throw std::runtime_error("timed out waiting for default audio playback");
            }
            lock.unlock();
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
            lock.lock();
        }
    }

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

    static bool formats_match(const AudioFormat& left, const AudioFormat& right) {
        return left.sample_format == right.sample_format &&
            left.sample_rate == right.sample_rate &&
            left.channels == right.channels;
    }

    static void check_mmresult(MMRESULT result, const char* operation) {
        if (result == MMSYSERR_NOERROR) {
            return;
        }
        char message[MAXERRORLENGTH]{};
        waveOutGetErrorTextA(result, message, static_cast<UINT>(sizeof(message)));
        throw std::runtime_error(std::string(operation) + " failed: " + message);
    }

    static double pcm_duration_ms(const AudioFormat& format, std::size_t byte_count) {
        const std::uint64_t bytes_per_second =
            static_cast<std::uint64_t>(format.sample_rate) * format.channels * sizeof(std::int16_t);
        if (bytes_per_second == 0) {
            throw std::runtime_error("invalid PCM format for duration measurement");
        }
        return static_cast<double>(byte_count) * 1000.0 /
            static_cast<double>(bytes_per_second);
    }

    static std::size_t pcm_frame_bytes(const AudioFormat& format) {
        const std::uint64_t bytes =
            static_cast<std::uint64_t>(format.channels) * sizeof(std::int16_t);
        if (bytes == 0 || bytes > std::numeric_limits<std::size_t>::max()) {
            throw std::runtime_error("invalid PCM frame size");
        }
        return static_cast<std::size_t>(bytes);
    }

    static std::uint64_t pcm_frame_count(
        const AudioFormat& format,
        std::size_t byte_count) {
        const std::size_t frame_bytes = pcm_frame_bytes(format);
        if (byte_count % frame_bytes != 0) {
            throw std::runtime_error("PCM buffer does not contain complete frames");
        }
        return static_cast<std::uint64_t>(byte_count / frame_bytes);
    }

    std::optional<std::uint64_t> device_position_locked() const {
        if (m_handle == nullptr) {
            return std::nullopt;
        }
        MMTIME position{};
        position.wType = TIME_SAMPLES;
        if (waveOutGetPosition(
                m_handle,
                &position,
                sizeof(position)) != MMSYSERR_NOERROR ||
            position.wType != TIME_SAMPLES) {
            return std::nullopt;
        }
        return static_cast<std::uint64_t>(position.u.sample);
    }

    void reset_stream_position_locked() {
        next_stream_frame_ = 0;
        if (const auto position = device_position_locked(); position.has_value()) {
            device_position_base_ = position.value();
            device_position_base_valid_ = true;
        }
        else {
            device_position_base_ = 0;
            device_position_base_valid_ = false;
        }
    }

    double elapsed_since_start_ms(std::chrono::steady_clock::time_point value) const {
        return std::chrono::duration<double, std::milli>(value - started_at_).count();
    }

    std::optional<PcmChunk> interruption_tail_locked(
        std::uint32_t fade_ms,
        PlaybackInterruptionDiagnostic& diagnostic) {
        if (buffers_.empty()) {
            return std::nullopt;
        }
        const std::optional<std::uint64_t> cursor_frame =
            current_playout_cursor_frame_locked();
        if (!cursor_frame.has_value()) {
            return std::nullopt;
        }
        diagnostic.cursor_available = cursor_frame.has_value();
        if (cursor_frame.has_value()) {
            diagnostic.cursor_frame = cursor_frame.value();
            diagnostic.producer_ahead_frames =
                next_stream_frame_ > cursor_frame.value()
                    ? next_stream_frame_ - cursor_frame.value()
                    : 0;
        }
        std::vector<PlayoutBuffer> snapshot;
        snapshot.reserve(buffers_.size());
        for (const std::unique_ptr<Buffer>& buffer : buffers_) {
            PcmChunk chunk;
            chunk.request_id = buffer->request_id;
            chunk.format = m_format;
            chunk.bytes = buffer->bytes;
            snapshot.push_back(PlayoutBuffer{std::move(chunk), buffer->start_frame});
        }
        if (!cursor_frame.has_value()) {
            return std::nullopt;
        }
        for (const std::unique_ptr<Buffer>& buffer : buffers_) {
            const std::uint64_t end = buffer->start_frame + buffer->frame_count;
            if (cursor_frame.value() < buffer->start_frame) {
                diagnostic.selected_buffer_start_frame = buffer->start_frame;
                diagnostic.selected_buffer_frame_count = buffer->frame_count;
                diagnostic.selected_local_offset_frames = 0;
                break;
            }
            if (cursor_frame.value() < end) {
                diagnostic.selected_buffer_start_frame = buffer->start_frame;
                diagnostic.selected_buffer_frame_count = buffer->frame_count;
                diagnostic.selected_local_offset_frames =
                    cursor_frame.value() - buffer->start_frame;
                break;
            }
        }
        return make_playout_cursor_fade(snapshot, cursor_frame.value(), fade_ms);
    }

    double queued_audio_duration_ms_locked() const {
        double duration_ms = 0.0;
        for (const std::unique_ptr<Buffer>& buffer : buffers_) {
            duration_ms += buffer->duration_ms;
        }
        for (const std::unique_ptr<Buffer>& buffer : pending_buffers_) {
            duration_ms += buffer->duration_ms;
        }
        return duration_ms;
    }

    std::optional<std::uint64_t> current_playout_cursor_frame_locked() const {
        if (!playback_started_ || buffers_.empty()) {
            return std::nullopt;
        }
        if (sink_mode_ == PlaybackSinkMode::Mock) {
            const auto now = std::chrono::steady_clock::now();
            for (const std::unique_ptr<Buffer>& item : buffers_) {
                const Buffer& buffer = *item;
                if (!buffer.mock_completion.has_value() ||
                    buffer.mock_completion.value() <= now) {
                    continue;
                }
                std::uint64_t cursor = buffer.start_frame;
                if (buffer.mock_start.has_value() && now > buffer.mock_start.value()) {
                    const double elapsed =
                        std::chrono::duration<double, std::milli>(
                            now - buffer.mock_start.value()).count();
                    cursor += static_cast<std::uint64_t>(
                        elapsed * m_format.sample_rate / 1000.0);
                    cursor = std::min(
                        cursor,
                        buffer.start_frame + buffer.frame_count);
                }
                return cursor;
            }
            return next_stream_frame_;
        }
        if (sink_mode_ != PlaybackSinkMode::WaveOut) {
            return std::nullopt;
        }
        const auto position = device_position_locked();
        if (!position.has_value()) {
            return std::nullopt;
        }
        if (device_position_base_valid_ &&
            position.value() >= device_position_base_) {
            return position.value() - device_position_base_;
        }
        return 0;
    }

    double queued_audio_ahead_ms_locked() const {
        if (!playback_started_) {
            return queued_audio_duration_ms_locked();
        }
        const auto cursor = current_playout_cursor_frame_locked();
        if (!cursor.has_value() || m_format.sample_rate == 0) {
            return queued_audio_duration_ms_locked();
        }
        std::uint64_t frames =
            next_stream_frame_ > cursor.value()
                ? next_stream_frame_ - cursor.value()
                : 0;
        for (const std::unique_ptr<Buffer>& buffer : pending_buffers_) {
            if (buffer->frame_count >
                std::numeric_limits<std::uint64_t>::max() - frames) {
                return queued_audio_duration_ms_locked();
            }
            frames += buffer->frame_count;
        }
        return static_cast<double>(frames) * 1000.0 /
            static_cast<double>(m_format.sample_rate);
    }

    void validate_pending_format_locked(const AudioFormat& format) {
        if (sink_mode_ == PlaybackSinkMode::Mock && playback_started_) {
            if (!formats_match(m_format, format)) {
                throw std::runtime_error(
                    "mock playback sink cannot change PCM format while audio is queued");
            }
            pending_format_ = format;
            return;
        }
        if (m_handle != nullptr) {
            if (!formats_match(m_format, format)) {
                throw std::runtime_error(
                    "default-device playback cannot change PCM format while audio is queued");
            }
            return;
        }
        if (pending_format_.has_value() && !formats_match(pending_format_.value(), format)) {
            throw std::runtime_error(
                "default-device playback cannot change PCM format while audio is buffered");
        }
        pending_format_ = format;
    }

    void flush_pending_locked() {
        if (pending_buffers_.empty()) {
            return;
        }
        if (m_handle == nullptr && !pending_format_.has_value()) {
            throw std::runtime_error("missing PCM format for buffered playback");
        }

        if (sink_mode_ == PlaybackSinkMode::Mock) {
            auto completion = std::chrono::steady_clock::now();
            if (!buffers_.empty() && buffers_.back()->mock_completion.has_value() &&
                buffers_.back()->mock_completion.value() > completion) {
                completion = buffers_.back()->mock_completion.value();
            }
            m_format = pending_format_.value();
            buffers_.reserve(buffers_.size() + pending_buffers_.size());
            while (!pending_buffers_.empty()) {
                std::unique_ptr<Buffer> buffer = std::move(pending_buffers_.front());
                pending_buffers_.erase(pending_buffers_.begin());
                if (should_inject_mock_failure(MockPlaybackFailureStage::Prepare)) {
                    pending_buffers_.insert(
                        pending_buffers_.begin(), std::move(buffer));
                    throw std::runtime_error("injected mock waveOutPrepareHeader failure");
                }
                if (should_inject_mock_failure(MockPlaybackFailureStage::Write)) {
                    pending_buffers_.insert(
                        pending_buffers_.begin(), std::move(buffer));
                    throw std::runtime_error("injected mock waveOutWrite failure");
                }
                const std::uint64_t start_frame = next_stream_frame_;
                buffer->start_frame = start_frame;
                buffer->mock_start = completion;
                completion += std::chrono::duration_cast<std::chrono::steady_clock::duration>(
                    std::chrono::duration<double, std::milli>(buffer->duration_ms));
                buffer->mock_completion = completion;
                buffers_.push_back(std::move(buffer));
                next_stream_frame_ = start_frame + buffers_.back()->frame_count;
                ++mock_submission_count_;
                if (!playback_started_) {
                    playback_started_ = true;
                    if (metrics_ != nullptr) {
                        metrics_->mark_first_waveout_submission();
                    }
                }
            }
            pending_format_.reset();
            return;
        }

        open_or_validate_locked(
            m_handle != nullptr ? m_format : pending_format_.value());
        if (!device_position_base_valid_) {
            const auto position = device_position_locked();
            device_position_base_ = position.value_or(0);
            device_position_base_valid_ = position.has_value();
        }
        buffers_.reserve(buffers_.size() + pending_buffers_.size());
        while (!pending_buffers_.empty()) {
            std::unique_ptr<Buffer> buffer = std::move(pending_buffers_.front());
            pending_buffers_.erase(pending_buffers_.begin());
            try {
                check_mmresult(
                    waveOutPrepareHeader(m_handle, &buffer->header, sizeof(WAVEHDR)),
                    "waveOutPrepareHeader");
            }
            catch (...) {
                pending_buffers_.insert(
                    pending_buffers_.begin(), std::move(buffer));
                throw;
            }
            buffer->prepared = true;
            try {
                check_mmresult(
                    waveOutWrite(m_handle, &buffer->header, sizeof(WAVEHDR)),
                    "waveOutWrite");
            }
            catch (...) {
                try {
                    unprepare_header_or_fail_locked(*buffer);
                    pending_buffers_.insert(
                        pending_buffers_.begin(), std::move(buffer));
                }
                catch (...) {
                    orphaned_buffers_.push_back(std::move(buffer));
                    throw;
                }
                throw;
            }
            const std::uint64_t start_frame = next_stream_frame_;
            buffer->start_frame = start_frame;
            next_stream_frame_ = start_frame + buffer->frame_count;
            buffers_.push_back(std::move(buffer));
            if (!playback_started_) {
                playback_started_ = true;
                if (metrics_ != nullptr) {
                    metrics_->mark_first_waveout_submission();
                }
            }
        }
        pending_format_.reset();
    }

    bool should_inject_mock_failure(MockPlaybackFailureStage stage) {
        if (!mock_fail_after_submissions_.has_value() ||
            mock_failure_injected_ ||
            mock_failure_stage_ != stage ||
            mock_submission_count_ < mock_fail_after_submissions_.value()) {
            return false;
        }
        mock_failure_injected_ = true;
        return true;
    }

    void clear_pending_locked() {
        pending_buffers_.clear();
        pending_format_.reset();
    }

    void throw_if_unhealthy_locked() const {
        if (unhealthy_) {
            throw std::runtime_error(
                unhealthy_reason_.empty()
                    ? "default audio playback is unhealthy"
                    : unhealthy_reason_);
        }
    }

    void unprepare_header_or_fail_locked(Buffer& buffer) {
        const MMRESULT result =
            waveOutUnprepareHeader(m_handle, &buffer.header, sizeof(WAVEHDR));
        if (result != MMSYSERR_NOERROR) {
            char message[MAXERRORLENGTH]{};
            waveOutGetErrorTextA(result, message, static_cast<UINT>(sizeof(message)));
            unhealthy_ = true;
            unhealthy_reason_ = std::string("waveOutUnprepareHeader failed: ") + message;
            throw std::runtime_error(unhealthy_reason_);
        }
        buffer.prepared = false;
    }

    void open_or_validate_locked(const AudioFormat& format) {
        if (m_handle != nullptr) {
            if (!formats_match(m_format, format)) {
                throw std::runtime_error(
                    "default-device playback cannot change PCM format while audio is queued");
            }
            return;
        }

        WAVEFORMATEX wave_format{};
        wave_format.wFormatTag = WAVE_FORMAT_PCM;
        wave_format.nChannels = static_cast<WORD>(format.channels);
        wave_format.nSamplesPerSec = format.sample_rate;
        wave_format.wBitsPerSample = 16;
        wave_format.nBlockAlign = static_cast<WORD>(
            wave_format.nChannels * (wave_format.wBitsPerSample / 8));
        wave_format.nAvgBytesPerSec = wave_format.nSamplesPerSec * wave_format.nBlockAlign;

        check_mmresult(
            waveOutOpen(&m_handle, WAVE_MAPPER, &wave_format, 0, 0, CALLBACK_NULL),
            "waveOutOpen");
        m_format = format;
    }

    void reap_finished_locked() {
        if (sink_mode_ == PlaybackSinkMode::Mock) {
            const auto now = std::chrono::steady_clock::now();
            for (auto it = buffers_.begin(); it != buffers_.end();) {
                if (!(*it)->mock_completion.has_value() ||
                    (*it)->mock_completion.value() > now) {
                    ++it;
                    continue;
                }
                it = buffers_.erase(it);
            }
            return;
        }
        for (auto it = buffers_.begin(); it != buffers_.end();) {
            Buffer& buffer = **it;
            if ((buffer.header.dwFlags & WHDR_DONE) == 0) {
                ++it;
                continue;
            }
            if (buffer.prepared) {
                unprepare_header_or_fail_locked(buffer);
            }
            it = buffers_.erase(it);
        }
    }

    void close_noexcept() noexcept {
        try {
            static_cast<void>(reset());
        }
        catch (...) {
        }

        std::lock_guard<std::mutex> lock(mutex_);
        if (unhealthy_) {
            // A failed unprepare means the driver may still own a prepared
            // header. Keep the ownership isolated rather than closing the
            // device or destroying storage that the driver may reference.
            for (auto& buffer : buffers_) {
                static_cast<void>(buffer.release());
            }
            for (auto& buffer : pending_buffers_) {
                static_cast<void>(buffer.release());
            }
            for (auto& buffer : orphaned_buffers_) {
                static_cast<void>(buffer.release());
            }
            buffers_.clear();
            pending_buffers_.clear();
            orphaned_buffers_.clear();
            m_handle = nullptr;
            return;
        }
        if (m_handle != nullptr) {
            waveOutClose(m_handle);
            m_handle = nullptr;
        }
    }

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
