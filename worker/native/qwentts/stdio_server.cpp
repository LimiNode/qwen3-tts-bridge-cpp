#include "stdio_server.hpp"
#include "diagnostics.hpp"
#include "stdout_writer.hpp"

#include <qwen_tts_bridge/protocol/control.hpp>

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <io.h>

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <limits>
#include <new>
#include <stdexcept>
#include <sstream>
#include <utility>

namespace qwen_tts_bridge::native_worker {
namespace {

std::vector<std::byte> make_frame(
    FrameType type,
    RequestId request_id,
    std::vector<std::byte> payload) {
    EncodeResult encoded = encode_frame(type, request_id, payload);
    if (!encoded) {
        throw std::runtime_error("unable to encode QTB frame: " + encoded.message);
    }
    return std::move(encoded.bytes);
}

std::string make_session_id() {
    const auto ticks = GetTickCount64();
    return "native-" + std::to_string(GetCurrentProcessId()) + "-" + std::to_string(ticks);
}

struct PcmSignalStats {
    double peak_abs = 0.0;
    double rms = 0.0;
};

PcmSignalStats float_pcm_stats(const float* samples, int count) {
    PcmSignalStats stats;
    if (samples == nullptr || count <= 0) {
        return stats;
    }
    long double sum_squares = 0.0L;
    for (int index = 0; index < count; ++index) {
        const double value = std::isfinite(samples[index]) ? samples[index] : 0.0;
        stats.peak_abs = std::max(stats.peak_abs, std::abs(value));
        sum_squares += value * value;
    }
    stats.rms = std::sqrt(static_cast<double>(sum_squares / count));
    return stats;
}

PcmSignalStats s16le_pcm_stats(const std::vector<std::byte>& pcm) {
    PcmSignalStats stats;
    if (pcm.size() < 2) {
        return stats;
    }
    long double sum_squares = 0.0L;
    const std::size_t sample_count = pcm.size() / 2u;
    for (std::size_t index = 0; index < sample_count; ++index) {
        const auto low = std::to_integer<std::uint8_t>(pcm[index * 2u]);
        const auto high = std::to_integer<std::uint8_t>(pcm[index * 2u + 1u]);
        const auto sample = static_cast<std::int16_t>(static_cast<std::uint16_t>(low) |
            (static_cast<std::uint16_t>(high) << 8u));
        const double value = sample;
        stats.peak_abs = std::max(stats.peak_abs, std::abs(value));
        sum_squares += value * value;
    }
    stats.rms = std::sqrt(static_cast<double>(sum_squares / sample_count));
    return stats;
}

void write_admission_released_metric(
    RequestId request_id,
    std::size_t admission_limit,
    std::size_t admitted_requests) {
    std::ostringstream metric;
    metric << "qtb_metric {\"event\":\"request_admission_released\",\"request_id\":"
           << request_id << ",\"admission_limit\":" << admission_limit
           << ",\"admitted_requests\":" << admitted_requests << "}";
    write_diagnostic_line(metric.str());
}

} // namespace

class StdioServer::OutputWriter final {
public:
    void start() {
        thread_ = std::thread([this]() { run(); });
    }

    bool send(
        std::vector<std::byte> frame,
        std::chrono::steady_clock::time_point deadline =
            std::chrono::steady_clock::time_point::max()) {
        const auto frame_size = frame.size();
        if (frame_size > max_bytes_) {
            return false;
        }
        std::unique_lock<std::mutex> lock(mutex_);
        const auto ready = [this, frame_size]() {
            return (
                       queue_.size() < max_frames_
                       && queued_bytes_ + in_flight_bytes_ + frame_size <= max_bytes_)
                || stopping_ || failed_;
        };
        if (deadline == std::chrono::steady_clock::time_point::max()) {
            not_full_.wait(lock, ready);
        }
        else if (!not_full_.wait_until(lock, deadline, ready)) {
            return false;
        }
        if (stopping_ || failed_) {
            return false;
        }
        queued_bytes_ += frame_size;
        queue_.push_back(std::move(frame));
        not_empty_.notify_one();
        return true;
    }

    void stop_accepting() {
        {
            std::lock_guard<std::mutex> lock(mutex_);
            stopping_ = true;
        }
        not_empty_.notify_all();
        not_full_.notify_all();
    }

    bool stop_when_drained(std::chrono::milliseconds timeout) {
        stop_accepting();
        if (thread_.joinable()) {
            std::unique_lock<std::mutex> lock(mutex_);
            const bool finished = finished_
                || finished_condition_.wait_for(lock, timeout, [this]() {
                    return finished_;
                });
            if (!finished) {
                // A condition variable cannot interrupt a synchronous
                // WriteFile.  Ask Windows to cancel that specific I/O before
                // the caller applies its forced process-teardown policy.
                CancelSynchronousIo(reinterpret_cast<HANDLE>(thread_.native_handle()));
                if (!finished_condition_.wait_for(lock, std::chrono::seconds(1), [this]() {
                        return finished_;
                    })) {
                    return false;
                }
            }
            lock.unlock();
            thread_.join();
        }
        return true;
    }

    bool failed() const {
        std::lock_guard<std::mutex> lock(mutex_);
        return failed_;
    }

private:
    void run() {
        const auto mark_finished_locked = [this]() {
            finished_ = true;
            finished_condition_.notify_all();
        };
        const HANDLE stdout_handle = GetStdHandle(STD_OUTPUT_HANDLE);
        for (;;) {
            std::vector<std::byte> frame;
            {
                std::unique_lock<std::mutex> lock(mutex_);
                not_empty_.wait(lock, [this]() { return !queue_.empty() || stopping_; });
                if (queue_.empty() && stopping_) {
                    mark_finished_locked();
                    return;
                }
                frame = std::move(queue_.front());
                queue_.pop_front();
                queued_bytes_ -= frame.size();
                in_flight_bytes_ += frame.size();
                not_full_.notify_one();
            }

            const auto result = write_stdout_frame(stdout_handle, frame);
            if (!result.success) {
                std::ostringstream diagnostic;
                diagnostic << "[native-worker:error] stdout WriteFile failed after "
                           << result.bytes_written << " of " << frame.size()
                           << " bytes, error=" << result.error_code;
                write_diagnostic_line(diagnostic.str());
                std::lock_guard<std::mutex> lock(mutex_);
                failed_ = true;
                stopping_ = true;
                queue_.clear();
                queued_bytes_ = 0;
                in_flight_bytes_ = 0;
                not_full_.notify_all();
                mark_finished_locked();
                return;
            }

            {
                std::lock_guard<std::mutex> lock(mutex_);
                in_flight_bytes_ -= frame.size();
                not_full_.notify_all();
            }
        }
    }

    static constexpr std::size_t max_frames_ = 128;
    // Queue accounting includes the fixed v1 frame header, so the full
    // 16 MiB payload limit remains admissible.
    static constexpr std::size_t max_bytes_ =
        qwen_tts_bridge::ProtocolLimits::max_frame_payload_bytes +
        qwen_tts_bridge::ProtocolLimits::min_header_size;
    mutable std::mutex mutex_;
    std::condition_variable not_empty_;
    std::condition_variable not_full_;
    std::condition_variable finished_condition_;
    std::deque<std::vector<std::byte>> queue_;
    std::size_t queued_bytes_ = 0;
    std::size_t in_flight_bytes_ = 0;
    std::thread thread_;
    bool stopping_ = false;
    bool failed_ = false;
    bool finished_ = false;
};

StdioServer::StdioServer(NativeEngine& engine, std::size_t max_admitted_requests)
    : engine_(engine),
      writer_(std::make_unique<OutputWriter>()),
      max_admitted_requests_(max_admitted_requests) {
    if (max_admitted_requests_ < 1 || max_admitted_requests_ > 65536) {
        throw std::invalid_argument("max_admitted_requests must be in [1, 65536]");
    }
}

StdioServer::~StdioServer() {
    request_shutdown(false);
    if (writer_) {
        writer_->stop_accepting();
    }
    if (engine_thread_.joinable()) {
        engine_thread_.join();
    }
    if (writer_) {
        writer_->stop_when_drained(std::chrono::milliseconds::max());
    }
    if (fatal_watchdog_thread_.joinable()) {
        fatal_watchdog_thread_.join();
    }
}

int StdioServer::run() {
    std::ostringstream metric;
    metric << "qtb_metric {\"event\":\"worker_admission_started\",\"admission_limit\":"
           << max_admitted_requests_ << ",\"admitted_requests\":0}";
    write_diagnostic_line(metric.str());
    writer_->start();
    engine_thread_ = std::thread([this]() { engine_loop(); });
    read_loop();
    request_shutdown(false);
    bool engine_finished = false;
    {
        std::unique_lock<std::mutex> lock(mutex_);
        engine_finished = condition_.wait_for(
            lock, std::chrono::seconds(5), [this]() { return engine_finished_; });
    }
    if (!engine_finished) {
        // Normal shutdown keeps the writer accepting frames so queued terminal
        // events preserve order.  If the engine is stuck waiting for output
        // capacity, switch to the forced phase and release blocked producers.
        writer_->stop_accepting();
        std::unique_lock<std::mutex> lock(mutex_);
        engine_finished = condition_.wait_for(
            lock, std::chrono::seconds(2), [this]() { return engine_finished_; });
        lock.unlock();
        if (!engine_finished) {
            write_diagnostic_line(
                "[native-worker:error] engine thread did not stop after output backpressure");
            TerminateProcess(GetCurrentProcess(), ERROR_TIMEOUT);
            return 1;
        }
    }
    if (engine_thread_.joinable()) {
        engine_thread_.join();
    }
    if (!writer_->stop_when_drained(std::chrono::seconds(5))) {
        write_diagnostic_line(
            "[native-worker:error] stdout writer did not stop after cancelling blocked output");
        TerminateProcess(GetCurrentProcess(), ERROR_TIMEOUT);
        return 1;
    }
    const int status = fatal_error_ || writer_->failed() ? 1 : 0;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        run_finished_ = true;
    }
    condition_.notify_all();
    if (fatal_watchdog_thread_.joinable()) {
        fatal_watchdog_thread_.join();
    }
    return status;
}

void StdioServer::read_loop() {
    std::array<char, 64 * 1024> buffer{};
    while (true) {
        {
            std::lock_guard<std::mutex> lock(mutex_);
            if (shutdown_requested_ || fatal_error_) {
                return;
            }
        }
        const int raw_count = _read(_fileno(stdin), buffer.data(), static_cast<unsigned int>(buffer.size()));
        const std::streamsize count = raw_count < 0 ? 0 : raw_count;
        if (count <= 0) {
            return;
        }
        parser_.append(reinterpret_cast<const std::byte*>(buffer.data()), static_cast<std::size_t>(count));
        for (;;) {
            ParseResult result = parser_.parse_next();
            if (result.status == ParseStatus::NeedMoreData) {
                break;
            }
            if (result.status == ParseStatus::FatalError) {
                fail_fatal("fatal QTB framing error: " + result.message);
                return;
            }
            if (!handle_frame(std::move(result.frame))) {
                return;
            }
        }
    }
}

bool StdioServer::handle_frame(Frame frame) {
    if (frame.header.frame_type != FrameType::ControlJson) {
        send_error(
            frame.header.request_id,
            "protocol_error",
            "invalid_message_direction",
            "native worker accepts only client-to-worker control_json frames");
        return true;
    }

    ControlDecodeResult decoded = decode_control_message(
        frame.payload,
        ControlMessageDirection::ClientToWorker);
    if (!decoded) {
        send_error(
            frame.header.request_id,
            "protocol_error",
            control_codec_error_code(decoded.error),
            decoded.diagnostic);
        return true;
    }

    const ControlMessageType type = control_message_type(decoded.message);
    bool not_ready = false;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        not_ready = !ready_sent_ && type != ControlMessageType::Hello &&
            type != ControlMessageType::Ping && type != ControlMessageType::Shutdown;
    }
    if (not_ready) {
        send_error(
            frame.header.request_id,
            "protocol_error",
            "invalid_session_state",
            "native worker is not ready");
        return true;
    }

    switch (type) {
    case ControlMessageType::Hello:
        handle_hello(frame.header.request_id);
        return true;
    case ControlMessageType::Synthesize:
        handle_synthesize(
            frame.header.request_id,
            std::get<SynthesizeMessage>(std::move(decoded.message)));
        return true;
    case ControlMessageType::Cancel:
        handle_cancel(frame.header.request_id);
        return true;
    case ControlMessageType::Ping:
        handle_ping(frame.header.request_id, std::get<PingMessage>(decoded.message));
        return true;
    case ControlMessageType::Shutdown:
        return handle_shutdown(frame.header.request_id, std::get<ShutdownMessage>(decoded.message));
    default:
        send_error(
            frame.header.request_id,
            "protocol_error",
            "invalid_message_direction",
            "message is not accepted by the native worker");
        return true;
    }
}

void StdioServer::handle_hello(RequestId request_id) {
    bool invalid = false;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        if (request_id != 0 || hello_seen_ || shutdown_requested_) {
            invalid = true;
        }
        else {
            hello_seen_ = true;
            ready_sent_ = true;
        }
    }
    if (invalid) {
        send_error(
            request_id,
            "protocol_error",
            "invalid_session_state",
            "hello is invalid in the current session state");
        return;
    }

    ReadyMessage ready;
    ready.worker_version = "0.2.0-native-qwentts/" + engine_.engine_version();
    ready.session_id = make_session_id();
    ready.has_warmed_up = true;
    ready.warmed_up = engine_.warmed_up();
    ready.capabilities = engine_.capabilities();
    ready.voice_ids = engine_.voice_ids();
    send_control(0, std::move(ready));
}

void StdioServer::handle_ping(RequestId request_id, const PingMessage& message) {
    if (request_id != 0) {
        send_error(
            request_id,
            "protocol_error",
            "invalid_session_state",
            "ping must use request_id = 0");
        return;
    }
    PongMessage pong;
    pong.has_sequence = message.has_sequence;
    pong.sequence = message.sequence;
    send_control(0, pong);
}

void StdioServer::handle_synthesize(RequestId request_id, SynthesizeMessage message) {
    if (request_id == 0) {
        send_error(0, "request_error", "missing_required_field", "synthesize requires a non-zero request_id");
        return;
    }
    try {
        engine_.validate_request(message);
    }
    catch (const std::invalid_argument& error) {
        const std::string text = error.what();
        const std::string code = text.find("output") != std::string::npos
            ? "unsupported_audio_format"
            : "invalid_native_request";
        send_error(request_id, "request_error", code, text);
        return;
    }
    catch (const std::exception& error) {
        send_error(request_id, "worker_error", "worker_not_ready", error.what());
        return;
    }

    auto slot = std::make_shared<RequestSlot>();
    slot->id = request_id;
    slot->request = std::move(message);
    std::uint32_t position = 0;
    bool shutting_down = false;
    bool fatal = false;
    bool duplicate = false;
    bool admission_rejected = false;
    std::size_t admitted_requests = 0;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        shutting_down = shutdown_requested_;
        fatal = fatal_error_;
        duplicate = active_.count(request_id) != 0 || request_id <= accepted_id_high_water_;
        if (!shutting_down && !duplicate && admitted_requests_ >= max_admitted_requests_) {
            admission_rejected = true;
        }
        // Fatal state closes admission atomically with the request registry.
        // Do not publish a worker_fatal response after first inserting the
        // request: that would consume capacity and leave a rejected request
        // visible as active/pending.
        if (!shutting_down && !fatal && !duplicate && !admission_rejected) {
            accepted_id_high_water_ = request_id;
            ++admitted_requests_;
            active_.emplace(request_id, slot);
            pending_.push_back(slot);
            position = static_cast<std::uint32_t>(pending_.size());
        }
        admitted_requests = admitted_requests_;
    }
    if (shutting_down) {
        send_error(request_id, "protocol_error", "shutdown_in_progress", "native worker is shutting down");
        return;
    }
    if (fatal) {
        send_error(request_id, "worker_error", "worker_fatal", "native worker has entered a terminal failure state");
        return;
    }
    if (duplicate) {
        send_error(request_id, "request_error", "duplicate_request_id", "request_id was already used in this session");
        return;
    }
    if (admission_rejected) {
        std::ostringstream metric;
        metric << "qtb_metric {\"event\":\"request_admission_rejected\",\"request_id\":"
               << request_id << ",\"reason\":\"resource_exhausted\",\"admission_limit\":"
               << max_admitted_requests_ << ",\"admitted_requests\":" << admitted_requests
               << "}";
        write_diagnostic_line(metric.str());
        send_error(request_id, "resource_error", "resource_exhausted", "worker admission limit reached");
        return;
    }
    QueuedMessage queued;
    queued.has_position = true;
    queued.position = position;
    send_control(request_id, queued);
    condition_.notify_one();
}

void StdioServer::handle_cancel(RequestId request_id) {
    if (request_id == 0) {
        send_error(0, "request_error", "unknown_request_id", "cancel requires a non-zero request_id");
        return;
    }

    std::shared_ptr<RequestSlot> cancelled_slot;
    bool unknown = false;
    bool admission_released = false;
    std::size_t admitted_requests_after = 0;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        const auto it = active_.find(request_id);
        if (it == active_.end()) {
            unknown = request_id > accepted_id_high_water_;
        }
        else {
            const auto& slot = it->second;
            slot->cancelled.store(true, std::memory_order_relaxed);
            if (slot->state == RequestState::Queued) {
                pending_.erase(std::remove(pending_.begin(), pending_.end(), slot), pending_.end());
            if (!slot->terminal.exchange(true)) {
                active_.erase(it);
                --admitted_requests_;
                admission_released = true;
                admitted_requests_after = admitted_requests_;
                cancelled_slot = slot;
                }
            }
        }
    }
    condition_.notify_all();
    if (admission_released) {
        write_admission_released_metric(
            request_id, max_admitted_requests_, admitted_requests_after);
    }
    if (unknown) {
        send_error(request_id, "request_error", "unknown_request_id", "request_id is not active");
    }
    else if (cancelled_slot) {
        send_control(request_id, CancelledMessage{});
    }
}

bool StdioServer::handle_shutdown(RequestId request_id, const ShutdownMessage& message) {
    if (request_id != 0 || message.mode != "cancel") {
        send_error(
            request_id,
            "protocol_error",
            "invalid_session_state",
            "shutdown must use request_id = 0 and mode = cancel");
        return true;
    }
    request_shutdown(true);
    return false;
}

void StdioServer::request_shutdown(bool send_ack) {
    std::vector<std::shared_ptr<RequestSlot>> queued;
    std::vector<std::pair<RequestId, std::size_t>> released_metrics;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        shutdown_ack_needed_ = shutdown_ack_needed_ || send_ack;
        if (shutdown_requested_) {
            condition_.notify_all();
            return;
        }
        shutdown_requested_ = true;
        while (!pending_.empty()) {
            auto slot = pending_.front();
            pending_.pop_front();
            slot->cancelled.store(true, std::memory_order_relaxed);
            if (!slot->terminal.exchange(true)) {
                active_.erase(slot->id);
                --admitted_requests_;
                released_metrics.emplace_back(slot->id, admitted_requests_);
                queued.push_back(std::move(slot));
            }
        }
        for (auto& entry : active_) {
            entry.second->cancelled.store(true, std::memory_order_relaxed);
        }
    }
    for (const auto& [request_id, admitted_requests] : released_metrics) {
        write_admission_released_metric(
            request_id, max_admitted_requests_, admitted_requests);
    }
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(5);
    for (const auto& slot : queued) {
        JsonPayloadEncodeResult payload = encode_control_message(CancelledMessage{});
        if (!payload) {
            fail_fatal("unable to encode cancellation control message: " + payload.diagnostic);
            break;
        }
        if (!writer_->send(
                make_frame(FrameType::ControlJson, slot->id, std::move(payload.payload)),
                deadline)) {
            fail_fatal("stdout writer timed out while publishing cancellation");
            break;
        }
    }
    {
        std::lock_guard<std::mutex> lock(mutex_);
        shutdown_terminals_enqueued_ = true;
    }
    condition_.notify_all();
}

void StdioServer::engine_loop() {
    for (;;) {
        auto slot = take_next_request();
        if (!slot) {
            break;
        }
        run_request(slot);
    }
    bool send_ack = false;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        send_ack = shutdown_ack_needed_;
    }
    if (send_ack) {
        send_control(0, ShutdownAckMessage{});
    }
    {
        std::lock_guard<std::mutex> lock(mutex_);
        engine_finished_ = true;
    }
    condition_.notify_all();
}

std::shared_ptr<StdioServer::RequestSlot> StdioServer::take_next_request() {
    std::unique_lock<std::mutex> lock(mutex_);
    condition_.wait(lock, [this]() {
        return !pending_.empty() ||
            (shutdown_requested_ && shutdown_terminals_enqueued_) || fatal_error_;
    });
    // A callback/engine failure is terminal for this worker instance.  Do not
    // run work that happened to be queued concurrently with fail_fatal().
    if (fatal_error_) {
        return {};
    }
    if (pending_.empty()) {
        return {};
    }
    auto slot = pending_.front();
    pending_.pop_front();
    slot->state = RequestState::Running;
    return slot;
}

void StdioServer::run_request(const std::shared_ptr<RequestSlot>& slot) {
    if (slot->cancelled.load(std::memory_order_relaxed)) {
        if (terminalize(slot)) {
            send_control(slot->id, CancelledMessage{});
        }
        return;
    }

    StartedMessage started;
    started.audio_format = slot->request.output;
    send_control(slot->id, started);

    const auto request_start = std::chrono::steady_clock::now();
    std::size_t chunk_index = 0;
    SynthesisResult result;
    try {
        result = engine_.synthesize(
            slot->request,
            slot->cancelled,
            [this, &slot, &request_start, &chunk_index](const float* samples, int count) {
            if (slot->cancelled.load(std::memory_order_relaxed) || slot->terminal.load()) {
                return false;
            }
#if defined(QTB_NATIVE_WORKER_TEST_HOOKS)
            // The fake-runtime E2E suite needs to exercise the same callback
            // boundary as a real qwentts plugin.  Keep the injection private
            // to test builds and opt-in through the child process environment.
            const char* failure_mode = std::getenv("QTB_TEST_NATIVE_CALLBACK_FAILURE");
            const bool fail_first = failure_mode != nullptr &&
                (std::strcmp(failure_mode, "runtime_error_first") == 0 ||
                 std::strcmp(failure_mode, "bad_alloc_first") == 0);
            const bool fail_after = failure_mode != nullptr &&
                (std::strcmp(failure_mode, "runtime_error_after") == 0 ||
                 std::strcmp(failure_mode, "bad_alloc_after") == 0);
            if ((fail_first && chunk_index == 0) || (fail_after && chunk_index > 0)) {
                if (std::strcmp(failure_mode, "bad_alloc_first") == 0 ||
                    std::strcmp(failure_mode, "bad_alloc_after") == 0) {
                    throw std::bad_alloc{};
                }
                throw std::runtime_error("injected native audio callback failure");
            }
#endif
            if (samples == nullptr || count <= 0) {
                fail_fatal("qwen.dll emitted an invalid audio chunk");
                return false;
            }
            if (chunk_index == 0) {
                const auto float_stats = float_pcm_stats(samples, count);
                const auto first_chunk_ms = std::chrono::duration<double, std::milli>(
                    std::chrono::steady_clock::now() - request_start).count();
                const auto pcm = float_pcm_to_s16le(samples, count);
                const auto s16_stats = s16le_pcm_stats(pcm);
                std::ostringstream metric;
                metric << "qtb_metric {\"event\":\"native_pcm_signal\",\"request_id\":"
                       << slot->id << ",\"chunk_index\":0,\"samples\":" << count
                       << ",\"first_chunk_ms\":" << first_chunk_ms
                       << ",\"float_peak_abs\":" << float_stats.peak_abs
                       << ",\"float_rms\":" << float_stats.rms
                       << ",\"s16_peak_abs\":" << s16_stats.peak_abs
                       << ",\"s16_rms\":" << s16_stats.rms << "}";
                write_diagnostic_line(metric.str());
                const bool sent = writer_->send(make_frame(FrameType::AudioPcm, slot->id, pcm));
                ++chunk_index;
                if (!sent) {
                    fail_fatal("stdout writer failed while streaming native audio");
                }
                return sent && !slot->cancelled.load(std::memory_order_relaxed);
            }
            auto pcm = float_pcm_to_s16le(samples, count);
            const bool sent = writer_->send(make_frame(FrameType::AudioPcm, slot->id, std::move(pcm)));
            ++chunk_index;
            if (!sent) {
                fail_fatal("stdout writer failed while streaming native audio");
            }
            return sent && !slot->cancelled.load(std::memory_order_relaxed);
            });
    }
    catch (const std::bad_alloc&) {
        result = {SynthesisOutcome::Failed, "internal_error", "native_request_bad_alloc",
                  "native request processing raised std::bad_alloc"};
    }
    catch (const std::exception& error) {
        result = {SynthesisOutcome::Failed, "internal_error", "native_request_exception", error.what()};
    }
    catch (...) {
        result = {SynthesisOutcome::Failed, "internal_error", "native_request_unknown_exception",
                  "native request processing raised an unknown exception"};
    }

    if (!terminalize(slot)) {
        return;
    }
    const bool unrecoverable_engine_failure =
        result.code == "audio_callback_bad_alloc" ||
        result.code == "audio_callback_exception" ||
        result.code == "audio_callback_unknown_exception" ||
        result.code == "native_synthesis_bad_alloc" ||
        result.code == "native_synthesis_exception" ||
        result.code == "native_synthesis_unknown_exception" ||
        result.code == "native_request_bad_alloc" ||
        result.code == "native_request_exception" ||
        result.code == "native_request_unknown_exception";
    const auto emit_finished_metric = [&](const char* terminal_state, const char* outcome) {
        std::ostringstream metric;
        metric << "qtb_metric {\"event\":\"request_finished\",\"request_id\":"
               << slot->id << ",\"terminal_state\":\"" << terminal_state << "\""
               << ",\"voice_reference_cache_hit\":"
               << (result.voice_reference_cache_hit ? "true" : "false")
               << ",\"voice_reference_extract_ms\":" << result.voice_reference_extract_ms
               << ",\"reference_audio_decode_ms\":" << result.reference_audio_decode_ms
               << ",\"synthesis_ms\":" << result.synthesis_ms
               << ",\"first_chunk_callback_ms\":" << result.first_chunk_callback_ms
               << ",\"qwen_prompt_build_ms\":" << result.qwen_prompt_build_ms
               << ",\"qwen_prefill_ms\":" << result.qwen_prefill_ms
               << ",\"qwen_ttfa_ms\":" << result.qwen_ttfa_ms
               << ",\"qwen_talker_ms\":" << result.qwen_talker_ms
               << ",\"qwen_predictor_ms\":" << result.qwen_predictor_ms
               << ",\"qwen_host_ms\":" << result.qwen_host_ms
               << ",\"qwen_codec_ms\":" << result.qwen_codec_ms
               << ",\"qwen_total_ms\":" << result.qwen_total_ms
               << ",\"qwen_n_frames\":" << result.qwen_n_frames;
        if (outcome != nullptr) {
            metric << ",\"execution_outcome\":\"" << outcome << "\"";
        }
        metric << "}";
        write_diagnostic_line(metric.str());
    };
    if (unrecoverable_engine_failure) {
        // Publish this request's terminal error before closing admission.  The
        // fatal transition then terminalizes any other accepted requests that
        // are still queued, so none are silently abandoned.
        terminalize(slot);
        emit_finished_metric("failed", nullptr);
        send_error(slot->id, result.category, result.code, result.message);
        fail_fatal("native engine state is not recoverable after request failure");
        return;
    }
    if (result.outcome == SynthesisOutcome::Completed) {
        CompletedMessage completed;
        completed.has_execution_outcome = true;
        completed.execution_outcome = result.execution_outcome.empty()
            ? "completed"
            : result.execution_outcome;
        completed.has_generation_trace = result.has_generation_trace;
        if (completed.has_generation_trace) {
            completed.generation_trace = result.generation_trace;
        }
        emit_finished_metric("completed", completed.execution_outcome.c_str());
        send_control(slot->id, std::move(completed));
    }
    else if (result.outcome == SynthesisOutcome::Cancelled) {
        emit_finished_metric("cancelled", nullptr);
        send_control(slot->id, CancelledMessage{});
    }
    else {
        emit_finished_metric("failed", nullptr);
        send_error(slot->id, result.category, result.code, result.message);
    }
}

bool StdioServer::terminalize(const std::shared_ptr<RequestSlot>& slot) {
    if (slot->terminal.exchange(true)) {
        return false;
    }
    std::size_t admitted_requests_after = 0;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        active_.erase(slot->id);
        if (admitted_requests_ > 0) {
            --admitted_requests_;
        }
        admitted_requests_after = admitted_requests_;
    }
    write_admission_released_metric(
        slot->id, max_admitted_requests_, admitted_requests_after);
    return true;
}

void StdioServer::send_control(RequestId request_id, ControlMessage message) {
    JsonPayloadEncodeResult payload = encode_control_message(message);
    if (!payload) {
        fail_fatal("unable to encode control message: " + payload.diagnostic);
        return;
    }
    if (!writer_->send(make_frame(FrameType::ControlJson, request_id, std::move(payload.payload)))) {
        fail_fatal("stdout writer rejected a control frame");
    }
}

void StdioServer::send_error(
    RequestId request_id,
    std::string category,
    std::string code,
    std::string message) {
    JsonPayloadEncodeResult payload = encode_error_message(
        ErrorMessage{std::move(category), std::move(code), std::move(message)});
    if (!payload) {
        fail_fatal("unable to encode error message: " + payload.diagnostic);
        return;
    }
    if (!writer_->send(make_frame(FrameType::ErrorJson, request_id, std::move(payload.payload)))) {
        fail_fatal("stdout writer rejected an error frame");
    }
}

void StdioServer::start_fatal_watchdog() {
    {
        std::lock_guard<std::mutex> lock(mutex_);
        if (fatal_watchdog_started_) {
            return;
        }
        fatal_watchdog_started_ = true;
    }
    fatal_watchdog_thread_ = std::thread([this]() {
        std::unique_lock<std::mutex> lock(mutex_);
        if (condition_.wait_for(lock, std::chrono::seconds(3), [this]() {
                return run_finished_;
            })) {
            return;
        }
        lock.unlock();
        // A fatal engine/output failure can leave read_loop() blocked in a
        // synchronous stdin read.  The process-level deadline is independent
        // of stderr/stdout publication and therefore cannot be wedged by a
        // stalled pipe.
        TerminateProcess(GetCurrentProcess(), ERROR_TIMEOUT);
    });
}

void StdioServer::fail_fatal(const std::string& message) {
    start_fatal_watchdog();
    write_diagnostic_line("[native-worker:error] " + message);
    std::vector<RequestId> abandoned;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        if (fatal_error_) {
            return;
        }
        fatal_error_ = true;
        abandoned.reserve(active_.size());
        for (auto it = active_.begin(); it != active_.end();) {
            const auto& slot = it->second;
            slot->cancelled.store(true, std::memory_order_relaxed);
            if (!slot->terminal.exchange(true)) {
                abandoned.push_back(slot->id);
                it = active_.erase(it);
                if (admitted_requests_ > 0) {
                    --admitted_requests_;
                }
            }
            else {
                it = active_.erase(it);
            }
        }
        for (const auto& slot : pending_) {
            slot->cancelled.store(true, std::memory_order_relaxed);
            if (!slot->terminal.exchange(true)) {
                abandoned.push_back(slot->id);
                active_.erase(slot->id);
                if (admitted_requests_ > 0) {
                    --admitted_requests_;
                }
            }
        }
        pending_.clear();
    }
    condition_.notify_all();

    // The diagnostic boundary is independent from the request terminalization
    // path and serializes all stderr records.
    // If stdout is still healthy, preserve the exactly-once terminal contract
    // for accepted requests.  A broken writer will reject the first frame and
    // the fatal guard above prevents recursive shutdown publication.
    for (const RequestId request_id : abandoned) {
        send_error(
            request_id,
            "worker_error",
            "worker_fatal",
            "native worker stopped after an unrecoverable engine failure");
    }
}

std::vector<std::byte> float_pcm_to_s16le(const float* samples, int count) {
    if (samples == nullptr || count <= 0) {
        return {};
    }
    std::vector<std::byte> output(static_cast<std::size_t>(count) * 2u);
    for (int index = 0; index < count; ++index) {
        const float value = std::isfinite(samples[index]) ? samples[index] : 0.0F;
        std::int32_t integer = 0;
        if (value <= -1.0F) {
            integer = -32768;
        }
        else if (value >= 1.0F) {
            integer = 32767;
        }
        else {
            integer = static_cast<std::int32_t>(std::lrint(value * 32768.0F));
            integer = std::clamp(integer, -32768, 32767);
        }
        const auto sample = static_cast<std::uint16_t>(static_cast<std::int16_t>(integer));
        output[static_cast<std::size_t>(index) * 2u] = static_cast<std::byte>(sample & 0xffu);
        output[static_cast<std::size_t>(index) * 2u + 1u] = static_cast<std::byte>((sample >> 8u) & 0xffu);
    }
    return output;
}

} // namespace qwen_tts_bridge::native_worker
