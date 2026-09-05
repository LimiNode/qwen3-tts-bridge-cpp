#include "StdioServer.hpp"

#include <qwen_tts_bridge/protocol/control.hpp>

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <io.h>

#include <algorithm>
#include <array>
#include <cmath>
#include <iostream>
#include <limits>
#include <stdexcept>
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

} // namespace

class StdioServer::OutputWriter final {
public:
    void start() {
        thread_ = std::thread([this]() { run(); });
    }

    bool send(std::vector<std::byte> frame) {
        std::unique_lock<std::mutex> lock(mutex_);
        not_full_.wait(lock, [this]() {
            return queue_.size() < max_frames_ || stopping_ || failed_;
        });
        if (stopping_ || failed_) {
            return false;
        }
        queue_.push_back(std::move(frame));
        not_empty_.notify_one();
        return true;
    }

    void stop_when_drained() {
        {
            std::lock_guard<std::mutex> lock(mutex_);
            stopping_ = true;
        }
        not_empty_.notify_all();
        not_full_.notify_all();
        if (thread_.joinable()) {
            thread_.join();
        }
    }

    bool failed() const {
        std::lock_guard<std::mutex> lock(mutex_);
        return failed_;
    }

private:
    void run() {
        for (;;) {
            std::vector<std::byte> frame;
            {
                std::unique_lock<std::mutex> lock(mutex_);
                not_empty_.wait(lock, [this]() { return !queue_.empty() || stopping_; });
                if (queue_.empty() && stopping_) {
                    return;
                }
                frame = std::move(queue_.front());
                queue_.pop_front();
                not_full_.notify_one();
            }

            std::cout.write(
                reinterpret_cast<const char*>(frame.data()),
                static_cast<std::streamsize>(frame.size()));
            std::cout.flush();
            if (!std::cout) {
                std::lock_guard<std::mutex> lock(mutex_);
                failed_ = true;
                stopping_ = true;
                queue_.clear();
                not_full_.notify_all();
                return;
            }
        }
    }

    static constexpr std::size_t max_frames_ = 128;
    mutable std::mutex mutex_;
    std::condition_variable not_empty_;
    std::condition_variable not_full_;
    std::deque<std::vector<std::byte>> queue_;
    std::thread thread_;
    bool stopping_ = false;
    bool failed_ = false;
};

StdioServer::StdioServer(NativeEngine& engine)
    : engine_(engine), writer_(std::make_unique<OutputWriter>()) {}

StdioServer::~StdioServer() {
    request_shutdown(false);
    if (engine_thread_.joinable()) {
        engine_thread_.join();
    }
    if (writer_) {
        writer_->stop_when_drained();
    }
}

int StdioServer::run() {
    writer_->start();
    engine_thread_ = std::thread([this]() { engine_loop(); });
    read_loop();
    request_shutdown(false);
    if (engine_thread_.joinable()) {
        engine_thread_.join();
    }
    writer_->stop_when_drained();
    return fatal_error_ || writer_->failed() ? 1 : 0;
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
    ready.warmed_up = false;
    ready.capabilities = engine_.capabilities();
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
    bool duplicate = false;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        shutting_down = shutdown_requested_;
        duplicate = active_.count(request_id) != 0 || terminal_ids_.count(request_id) != 0;
        if (!shutting_down && !duplicate) {
            active_.emplace(request_id, slot);
            pending_.push_back(slot);
            position = static_cast<std::uint32_t>(pending_.size());
        }
    }
    if (shutting_down) {
        send_error(request_id, "protocol_error", "shutdown_in_progress", "native worker is shutting down");
        return;
    }
    if (duplicate) {
        send_error(request_id, "request_error", "duplicate_request_id", "request_id was already used in this session");
        return;
    }
    QueuedMessage queued;
    queued.has_position = true;
    queued.position = position;
    send_control(request_id, queued);
    condition_.notify_one();
}

void StdioServer::handle_cancel(RequestId request_id) {
    std::shared_ptr<RequestSlot> cancelled_slot;
    bool unknown = false;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        const auto it = active_.find(request_id);
        if (it == active_.end()) {
            unknown = terminal_ids_.count(request_id) == 0;
        }
        else {
            const auto& slot = it->second;
            slot->cancelled.store(true, std::memory_order_relaxed);
            if (slot->state == RequestState::Queued) {
                pending_.erase(std::remove(pending_.begin(), pending_.end(), slot), pending_.end());
                if (!slot->terminal.exchange(true)) {
                    active_.erase(it);
                    terminal_ids_.insert(request_id);
                    cancelled_slot = slot;
                }
            }
        }
    }
    condition_.notify_all();
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
                terminal_ids_.insert(slot->id);
                queued.push_back(std::move(slot));
            }
        }
        for (auto& entry : active_) {
            entry.second->cancelled.store(true, std::memory_order_relaxed);
        }
    }
    for (const auto& slot : queued) {
        send_control(slot->id, CancelledMessage{});
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
}

std::shared_ptr<StdioServer::RequestSlot> StdioServer::take_next_request() {
    std::unique_lock<std::mutex> lock(mutex_);
    condition_.wait(lock, [this]() {
        return !pending_.empty() ||
            (shutdown_requested_ && shutdown_terminals_enqueued_) || fatal_error_;
    });
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

    const SynthesisResult result = engine_.synthesize(
        slot->request,
        slot->cancelled,
        [this, &slot](const float* samples, int count) {
            if (slot->cancelled.load(std::memory_order_relaxed) || slot->terminal.load()) {
                return false;
            }
            if (samples == nullptr || count <= 0) {
                fail_fatal("qwen.dll emitted an invalid audio chunk");
                return false;
            }
            auto pcm = float_pcm_to_s16le(samples, count);
            const bool sent = writer_->send(make_frame(FrameType::AudioPcm, slot->id, std::move(pcm)));
            if (!sent) {
                fail_fatal("stdout writer failed while streaming native audio");
            }
            return sent && !slot->cancelled.load(std::memory_order_relaxed);
        });

    if (!terminalize(slot)) {
        return;
    }
    const auto emit_finished_metric = [&](const char* terminal_state, const char* outcome) {
        std::cerr << "qtb_metric {\"event\":\"request_finished\",\"request_id\":"
                  << slot->id << ",\"terminal_state\":\"" << terminal_state << "\"";
        if (outcome != nullptr) {
            std::cerr << ",\"execution_outcome\":\"" << outcome << "\"";
        }
        std::cerr << "}\n" << std::flush;
    };
    if (result.outcome == SynthesisOutcome::Completed) {
        CompletedMessage completed;
        completed.has_execution_outcome = true;
        completed.execution_outcome = result.execution_outcome.empty()
            ? "completed"
            : result.execution_outcome;
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
    std::lock_guard<std::mutex> lock(mutex_);
    active_.erase(slot->id);
    terminal_ids_.insert(slot->id);
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

void StdioServer::fail_fatal(const std::string& message) {
    std::cerr << "[native-worker:error] " << message << '\n';
    {
        std::lock_guard<std::mutex> lock(mutex_);
        fatal_error_ = true;
        for (auto& entry : active_) {
            entry.second->cancelled.store(true, std::memory_order_relaxed);
        }
    }
    condition_.notify_all();
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
