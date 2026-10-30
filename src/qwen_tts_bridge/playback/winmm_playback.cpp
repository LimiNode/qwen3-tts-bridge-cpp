#include "winmm_playback.hpp"

#include "playback_interruption_diagnostics.hpp"

namespace qwen_tts_bridge::playback {

WaveOutPlayer::WaveOutPlayer(
    PlaybackSinkMode sink_mode,
    PlaybackMetrics* metrics,
    std::size_t prebuffer_chunks,
    std::optional<std::size_t> mock_fail_after_submissions,
    std::optional<MockPlaybackFailureStage> mock_failure_stage)
    : sink_mode_(sink_mode),
      prebuffer_chunks_(prebuffer_chunks),
      metrics_(metrics),
      mock_fail_after_submissions_(mock_fail_after_submissions),
      mock_failure_stage_(mock_failure_stage.value_or(MockPlaybackFailureStage::Write)) {
    if (prebuffer_chunks_ == 0) {
        throw std::runtime_error("playback prebuffer must contain at least one chunk");
    }
}

WaveOutPlayer::~WaveOutPlayer() {
    close_noexcept();
}

void WaveOutPlayer::enqueue(std::uint64_t playback_epoch, const PcmChunk& chunk) {
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

[[nodiscard]] std::uint64_t WaveOutPlayer::reset() {
    std::unique_lock<std::mutex> lock(mutex_);
    return reset_locked(lock);
}

[[nodiscard]] bool WaveOutPlayer::reset_if_epoch(std::uint64_t expected_epoch) {
    std::unique_lock<std::mutex> lock(mutex_);
    if (playback_epoch_ != expected_epoch) {
        return false;
    }
    static_cast<void>(reset_locked(lock));
    return true;
}

[[nodiscard]] std::uint64_t WaveOutPlayer::playback_epoch() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return playback_epoch_;
}

void WaveOutPlayer::set_reset_wait_hook_for_test(std::function<void()> hook) {
    std::lock_guard<std::mutex> lock(mutex_);
    reset_wait_hook_for_test_ = std::move(hook);
}

[[nodiscard]] std::size_t WaveOutPlayer::buffered_chunk_count_for_test() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return buffers_.size() + pending_buffers_.size();
}

[[nodiscard]] std::uint64_t WaveOutPlayer::next_stream_frame_for_test() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return next_stream_frame_;
}

[[nodiscard]] bool WaveOutPlayer::unhealthy_for_test() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return unhealthy_;
}

void WaveOutPlayer::close_for_test() noexcept {
    close_noexcept();
}

std::pair<std::uint64_t, std::optional<PcmChunk>> WaveOutPlayer::interrupt_with_fade(
    std::uint32_t fade_ms,
    RequestId old_request_id) {
    std::unique_lock<std::mutex> lock(mutex_);
    return interrupt_with_fade_locked(lock, fade_ms, old_request_id);
}

std::optional<std::pair<std::uint64_t, std::optional<PcmChunk>>>
WaveOutPlayer::interrupt_with_fade_if_epoch(
    std::uint64_t expected_epoch,
    std::uint32_t fade_ms,
    RequestId old_request_id) {
    std::unique_lock<std::mutex> lock(mutex_);
    if (playback_epoch_ != expected_epoch) {
        return std::nullopt;
    }
    return interrupt_with_fade_locked(lock, fade_ms, old_request_id);
}

std::pair<std::uint64_t, std::optional<PcmChunk>> WaveOutPlayer::interrupt_with_fade_locked(
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

void WaveOutPlayer::note_request_started(RequestId request_id) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (last_interruption_diagnostic_index_.has_value()) {
        interruption_diagnostics_[last_interruption_diagnostic_index_.value()].new_request_id =
            request_id;
        last_interruption_diagnostic_index_.reset();
    }
}

void WaveOutPlayer::note_request_terminal(RequestId request_id, const char* terminal_state) {
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

PlaybackCursorSnapshot WaveOutPlayer::playback_cursor_snapshot(
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

void WaveOutPlayer::write_interruption_diagnostics_file(const std::string& file_name) const {
    std::vector<PlaybackInterruptionDiagnostic> diagnostics;
    std::uint64_t late_audio_after_terminal_count = 0;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        diagnostics = interruption_diagnostics_;
        late_audio_after_terminal_count = late_audio_after_terminal_count_;
    }
    const std::string json = detail::format_interruption_diagnostics_json(
        diagnostics,
        late_audio_after_terminal_count);
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
        output << json;
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

std::uint64_t WaveOutPlayer::reset_locked(
    std::unique_lock<std::mutex>& lock,
    PlaybackInterruptionDiagnostic* diagnostic) {
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
        if (should_inject_mock_failure(MockPlaybackFailureStage::Reset)) {
            unhealthy_ = true;
            unhealthy_reason_ = "injected mock waveOutReset failure";
            throw std::runtime_error(unhealthy_reason_);
        }
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
    try {
        check_mmresult(waveOutReset(m_handle), "waveOutReset");
    }
    catch (const std::exception& error) {
        unhealthy_ = true;
        unhealthy_reason_ = error.what();
        throw;
    }
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
            unhealthy_ = true;
            unhealthy_reason_ =
                "timed out waiting for default audio device reset";
            throw std::runtime_error(unhealthy_reason_);
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

void WaveOutPlayer::wait_until_idle(std::chrono::milliseconds timeout) {
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

bool WaveOutPlayer::formats_match(const AudioFormat& left, const AudioFormat& right) {
    return left.sample_format == right.sample_format &&
        left.sample_rate == right.sample_rate &&
        left.channels == right.channels;
}

void WaveOutPlayer::check_mmresult(MMRESULT result, const char* operation) {
    if (result == MMSYSERR_NOERROR) {
        return;
    }
    char message[MAXERRORLENGTH]{};
    waveOutGetErrorTextA(result, message, static_cast<UINT>(sizeof(message)));
    throw std::runtime_error(std::string(operation) + " failed: " + message);
}

double WaveOutPlayer::pcm_duration_ms(const AudioFormat& format, std::size_t byte_count) {
    const std::uint64_t bytes_per_second =
        static_cast<std::uint64_t>(format.sample_rate) * format.channels * sizeof(std::int16_t);
    if (bytes_per_second == 0) {
        throw std::runtime_error("invalid PCM format for duration measurement");
    }
    return static_cast<double>(byte_count) * 1000.0 /
        static_cast<double>(bytes_per_second);
}

std::size_t WaveOutPlayer::pcm_frame_bytes(const AudioFormat& format) {
    const std::uint64_t bytes =
        static_cast<std::uint64_t>(format.channels) * sizeof(std::int16_t);
    if (bytes == 0 || bytes > std::numeric_limits<std::size_t>::max()) {
        throw std::runtime_error("invalid PCM frame size");
    }
    return static_cast<std::size_t>(bytes);
}

std::uint64_t WaveOutPlayer::pcm_frame_count(
    const AudioFormat& format,
    std::size_t byte_count) {
    const std::size_t frame_bytes = pcm_frame_bytes(format);
    if (byte_count % frame_bytes != 0) {
        throw std::runtime_error("PCM buffer does not contain complete frames");
    }
    return static_cast<std::uint64_t>(byte_count / frame_bytes);
}

std::optional<std::uint64_t> WaveOutPlayer::device_position_locked() const {
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

void WaveOutPlayer::reset_stream_position_locked() {
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

double WaveOutPlayer::elapsed_since_start_ms(std::chrono::steady_clock::time_point value) const {
    return std::chrono::duration<double, std::milli>(value - started_at_).count();
}

std::optional<PcmChunk> WaveOutPlayer::interruption_tail_locked(
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

double WaveOutPlayer::queued_audio_duration_ms_locked() const {
    double duration_ms = 0.0;
    for (const std::unique_ptr<Buffer>& buffer : buffers_) {
        duration_ms += buffer->duration_ms;
    }
    for (const std::unique_ptr<Buffer>& buffer : pending_buffers_) {
        duration_ms += buffer->duration_ms;
    }
    return duration_ms;
}

std::optional<std::uint64_t> WaveOutPlayer::current_playout_cursor_frame_locked() const {
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

double WaveOutPlayer::queued_audio_ahead_ms_locked() const {
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

void WaveOutPlayer::validate_pending_format_locked(const AudioFormat& format) {
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

void WaveOutPlayer::flush_pending_locked() {
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
            buffer->prepared = true;
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

bool WaveOutPlayer::should_inject_mock_failure(MockPlaybackFailureStage stage) {
    if (!mock_fail_after_submissions_.has_value() ||
        mock_failure_injected_ ||
        mock_failure_stage_ != stage ||
        mock_submission_count_ < mock_fail_after_submissions_.value()) {
        return false;
    }
    mock_failure_injected_ = true;
    return true;
}

void WaveOutPlayer::clear_pending_locked() {
    pending_buffers_.clear();
    pending_format_.reset();
}

void WaveOutPlayer::abandon_driver_owned_resources_locked() noexcept {
    // A failed reset, unprepare, or close leaves the driver's ownership
    // unconfirmed. Deliberately leak the affected storage instead of
    // destroying WAVEHDR/PCM memory that WinMM may still reference.
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
}

void WaveOutPlayer::throw_if_unhealthy_locked() const {
    if (unhealthy_) {
        throw std::runtime_error(
            unhealthy_reason_.empty()
                ? "default audio playback is unhealthy"
                : unhealthy_reason_);
    }
}

void WaveOutPlayer::unprepare_header_or_fail_locked(Buffer& buffer) {
    if (sink_mode_ == PlaybackSinkMode::Mock) {
        if (should_inject_mock_failure(MockPlaybackFailureStage::Unprepare)) {
            unhealthy_ = true;
            unhealthy_reason_ = "injected mock waveOutUnprepareHeader failure";
            throw std::runtime_error(unhealthy_reason_);
        }
        buffer.prepared = false;
        return;
    }
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

void WaveOutPlayer::open_or_validate_locked(const AudioFormat& format) {
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

void WaveOutPlayer::reap_finished_locked() {
    if (sink_mode_ == PlaybackSinkMode::Mock) {
        const auto now = std::chrono::steady_clock::now();
        for (auto it = buffers_.begin(); it != buffers_.end();) {
            if (!(*it)->mock_completion.has_value() ||
                (*it)->mock_completion.value() > now) {
                ++it;
                continue;
            }
            if ((*it)->prepared) {
                unprepare_header_or_fail_locked(**it);
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

void WaveOutPlayer::close_noexcept() noexcept {
    bool reset_succeeded = true;
    try {
        static_cast<void>(reset());
    }
    catch (...) {
        reset_succeeded = false;
    }

    std::lock_guard<std::mutex> lock(mutex_);
    if (sink_mode_ == PlaybackSinkMode::Mock &&
        should_inject_mock_failure(MockPlaybackFailureStage::Close)) {
        unhealthy_ = true;
        unhealthy_reason_ = "injected mock waveOutClose failure";
    }
    if (!reset_succeeded) {
        unhealthy_ = true;
        if (unhealthy_reason_.empty()) {
            unhealthy_reason_ = "default audio playback teardown failed";
        }
    }
    if (unhealthy_) {
        abandon_driver_owned_resources_locked();
        return;
    }
    if (m_handle != nullptr) {
        const MMRESULT result = waveOutClose(m_handle);
        if (result != MMSYSERR_NOERROR) {
            unhealthy_ = true;
            char message[MAXERRORLENGTH]{};
            waveOutGetErrorTextA(result, message, static_cast<UINT>(sizeof(message)));
            unhealthy_reason_ = std::string("waveOutClose failed: ") + message;
            abandon_driver_owned_resources_locked();
            return;
        }
        m_handle = nullptr;
    }
}

void winmm_playback_link_anchor() {}

} // namespace qwen_tts_bridge::playback
