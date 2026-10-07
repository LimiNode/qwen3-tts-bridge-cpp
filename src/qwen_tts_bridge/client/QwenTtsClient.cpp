#include <qwen_tts_bridge/client/QwenTtsClient.hpp>
#include <qwen_tts_bridge/protocol/control/control_codec.hpp>

#include <algorithm>
#include <chrono>
#include <exception>
#include <limits>
#include <optional>
#include <type_traits>
#include <utility>
#include <variant>
#include <vector>

namespace qwen_tts_bridge {
namespace {

constexpr std::size_t outbound_command_fixed_overhead = 64u;

std::optional<std::size_t> bytes_per_sample(const AudioFormat& format) {
    if (format.sample_format == "u8") {
        return 1u;
    }
    if (format.sample_format == "s16le") {
        return 2u;
    }
    if (format.sample_format == "s24le") {
        return 3u;
    }
    if (format.sample_format == "s32le" ||
        format.sample_format == "f32le") {
        return 4u;
    }
    return std::nullopt;
}

std::optional<std::uint32_t> sample_count_for_audio(
    const AudioFormat& format,
    std::size_t byte_count) {
    const auto sample_bytes = bytes_per_sample(format);
    if (!sample_bytes.has_value() || format.channels == 0) {
        return std::nullopt;
    }
    const std::size_t frame_bytes =
        sample_bytes.value() * static_cast<std::size_t>(format.channels);
    if (frame_bytes == 0 || byte_count % frame_bytes != 0) {
        return std::nullopt;
    }
    const std::size_t frames = byte_count / frame_bytes;
    if (frames > std::numeric_limits<std::uint32_t>::max()) {
        return std::nullopt;
    }
    return static_cast<std::uint32_t>(frames);
}

TtsError make_local_error(
    RequestId request_id,
    std::string category,
    std::string code,
    std::string message) {
    TtsError error;
    error.request_id = request_id;
    error.category = std::move(category);
    error.code = std::move(code);
    error.message = std::move(message);
    return error;
}

bool is_valid_utf8(const std::string& value) {
    const auto* bytes = reinterpret_cast<const unsigned char*>(value.data());
    std::size_t index = 0;
    while (index < value.size()) {
        const unsigned char lead = bytes[index++];
        std::uint32_t code_point = 0;
        std::size_t continuation_count = 0;
        if (lead <= 0x7Fu) {
            continue;
        }
        if (lead >= 0xC2u && lead <= 0xDFu) {
            code_point = lead & 0x1Fu;
            continuation_count = 1;
        }
        else if (lead >= 0xE0u && lead <= 0xEFu) {
            code_point = lead & 0x0Fu;
            continuation_count = 2;
        }
        else if (lead >= 0xF0u && lead <= 0xF4u) {
            code_point = lead & 0x07u;
            continuation_count = 3;
        }
        else {
            return false;
        }

        if (index + continuation_count > value.size()) {
            return false;
        }
        for (std::size_t offset = 0; offset < continuation_count; ++offset) {
            const unsigned char continuation = bytes[index++];
            if ((continuation & 0xC0u) != 0x80u) {
                return false;
            }
            code_point = (code_point << 6u) | (continuation & 0x3Fu);
        }
        if ((continuation_count == 2 && code_point < 0x800u) ||
            (continuation_count == 3 && code_point < 0x10000u) ||
            code_point > 0x10FFFFu ||
            (code_point >= 0xD800u && code_point <= 0xDFFFu)) {
            return false;
        }
    }
    return true;
}

bool is_unicode_space(std::uint32_t code_point) {
    return code_point == 0x0009u ||
        code_point == 0x000Au ||
        code_point == 0x000Bu ||
        code_point == 0x000Cu ||
        code_point == 0x000Du ||
        code_point == 0x0020u ||
        code_point == 0x00A0u ||
        code_point == 0x1680u ||
        (code_point >= 0x2000u && code_point <= 0x200Au) ||
        code_point == 0x2028u ||
        code_point == 0x2029u ||
        code_point == 0x202Fu ||
        code_point == 0x205Fu ||
        code_point == 0x3000u;
}

std::size_t count_non_space_utf8_bytes(const std::string& value) {
    std::size_t result = 0;
    std::size_t index = 0;
    while (index < value.size()) {
        const unsigned char lead =
            static_cast<unsigned char>(value[index]);
        std::size_t width = 1;
        std::uint32_t code_point = lead;
        if (lead >= 0xC2u && lead <= 0xDFu) {
            width = 2;
            code_point = lead & 0x1Fu;
        }
        else if (lead >= 0xE0u && lead <= 0xEFu) {
            width = 3;
            code_point = lead & 0x0Fu;
        }
        else if (lead >= 0xF0u && lead <= 0xF4u) {
            width = 4;
            code_point = lead & 0x07u;
        }
        for (std::size_t offset = 1; offset < width; ++offset) {
            code_point = (code_point << 6u) |
                (static_cast<unsigned char>(value[index + offset]) & 0x3Fu);
        }
        if (!is_unicode_space(code_point)) {
            result += width;
        }
        index += width;
    }
    return result;
}

void refresh_prepared_text_metrics(PreparedText& prepared) {
    prepared.utf8_bytes = prepared.effective_text.size();
    prepared.non_space_utf8_bytes =
        count_non_space_utf8_bytes(prepared.effective_text);
    prepared.was_modified = prepared.original_text != prepared.effective_text;
}

SynthesizeMessage to_control_message(const TtsRequest& request) {
    SynthesizeMessage message;
    message.text = request.text;
    message.language = request.language;
    message.speaker = request.speaker;
    message.instruction = request.instruction;
    message.voice_id = request.voice_id;
    message.reference_audio_path = request.reference_audio_path;
    message.reference_text = request.reference_text;
    message.x_vector_only = request.x_vector_only;
    message.has_seed = request.has_seed;
    message.seed = request.seed;
    message.sampling.temperature = request.sampling.temperature;
    message.sampling.top_k = request.sampling.top_k;
    message.sampling.top_p = request.sampling.top_p;
    message.sampling.repetition_penalty = request.sampling.repetition_penalty;
    message.sampling.do_sample = request.sampling.do_sample;
    message.output = request.output;
    return message;
}

} // namespace

QwenTtsClient::QwenTtsClient() = default;

QwenTtsClient::~QwenTtsClient() {
    stop();
}

bool QwenTtsClient::start(
    std::unique_ptr<ITransport> transport,
    QwenTtsClientOptions options) {
    if (transport == nullptr ||
        options.max_outbound_commands == 0 ||
        options.max_outbound_command_bytes == 0) {
        return false;
    }

    {
        std::lock_guard<std::mutex> lock(mutex_);
        if (running_ || stopping_) {
            return false;
        }
    }
    reap_finished_threads();

    {
        std::lock_guard<std::mutex> lock(mutex_);
        if (running_ ||
            stopping_ ||
            session_ != nullptr ||
            writer_thread_.joinable() ||
            dispatcher_thread_.joinable()) {
            return false;
        }
    }

    auto session = std::make_unique<WorkerSession>(
        std::move(transport),
        options.session);
    if (!session->start()) {
        session->stop();
        return false;
    }

    {
        std::lock_guard<std::mutex> lock(mutex_);
        options_ = std::move(options);
        session_ = std::move(session);
        active_requests_.clear();
        clear_outbound_queue_locked();
        next_request_id_ = 1;
        running_ = true;
        stopping_ = false;
        terminal_failure_handled_ = false;
        late_audio_after_terminal_count_ = 0;
        duplicate_terminal_event_count_ = 0;
    }

    try {
        writer_thread_ = std::thread(&QwenTtsClient::writer_loop, this);
        dispatcher_thread_ = std::thread(&QwenTtsClient::dispatcher_loop, this);
    }
    catch (...) {
        stop();
        return false;
    }

    return true;
}

bool QwenTtsClient::start(
    const StdIoTransportOptions& transport_options,
    QwenTtsClientOptions options) {
    return start(
        std::make_unique<StdIoTransport>(transport_options),
        std::move(options));
}

bool QwenTtsClient::start(const std::string& worker_executable) {
    StdIoTransportOptions transport_options;
    transport_options.arguments.push_back(worker_executable);
    return start(transport_options);
}

bool QwenTtsClient::prepare_text(
    const TtsRequest& request,
    PreparedText& prepared,
    TtsError& error) const {
    QwenTtsClientOptions::TextPreparer text_preparer;
    std::function<std::string(const TtsRequest&)> text_preprocessor;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        text_preparer = options_.text_preparer;
        text_preprocessor = options_.text_preprocessor;
    }

    if (text_preparer) {
        try {
            if (!text_preparer(request, prepared, error)) {
                if (error.code.empty()) {
                    error = make_local_error(
                        request.id,
                        "client_error",
                        "text_preprocessing_failed",
                        "structured text preparation failed");
                }
                return false;
            }
        }
        catch (const std::exception& exception) {
            error = make_local_error(
                request.id,
                "client_error",
                "text_preprocessing_failed",
                std::string("text preprocessing failed: ") + exception.what());
            return false;
        }
        catch (...) {
            error = make_local_error(
                request.id,
                "client_error",
                "text_preprocessing_failed",
                "text preprocessing failed: unknown exception");
            return false;
        }

        if (prepared.original_text != request.text) {
            error = make_local_error(
                request.id,
                "client_error",
                "prepared_text_mismatch",
                "structured text preparation returned a mismatched source text");
            return false;
        }
        if (!is_valid_utf8(prepared.effective_text)) {
            error = make_local_error(
                request.id,
                "client_error",
                "invalid_utf8_text",
                "text preparation returned invalid UTF-8");
            return false;
        }
        if (prepared.effective_text.empty()) {
            error = make_local_error(
                request.id,
                "request_error",
                "empty_text",
                "synthesis text is empty after preprocessing");
            return false;
        }
        refresh_prepared_text_metrics(prepared);
        return true;
    }

    std::string processed_text;
    try {
        processed_text = text_preprocessor
            ? text_preprocessor(request)
            : request.text;
    }
    catch (const std::exception& exception) {
        error = make_local_error(
            request.id,
            "client_error",
            "text_preprocessing_failed",
            std::string("text preprocessing failed: ") + exception.what());
        return false;
    }
    catch (...) {
        error = make_local_error(
            request.id,
            "client_error",
            "text_preprocessing_failed",
            "text preprocessing failed: unknown exception");
        return false;
    }
    if (!is_valid_utf8(processed_text)) {
        error = make_local_error(
            request.id,
            "client_error",
            "invalid_utf8_text",
            "text preprocessing returned invalid UTF-8");
        return false;
    }
    if (processed_text.empty()) {
        error = make_local_error(
            request.id,
            "request_error",
            "empty_text",
            "synthesis text is empty after preprocessing");
        return false;
    }
    prepared.original_text = request.text;
    prepared.effective_text = std::move(processed_text);
    refresh_prepared_text_metrics(prepared);
    return true;
}

RequestId QwenTtsClient::synthesize_async(
    TtsRequest request,
    TtsCallbacks callbacks) {
    PreparedText prepared;
    TtsError error;
    if (!prepare_text(request, prepared, error)) {
        try {
            if (callbacks.on_error) {
                callbacks.on_error(error);
            }
        }
        catch (...) {
        }
        return 0;
    }

    PreparedTtsRequest prepared_request;
    prepared_request.request = std::move(request);
    prepared_request.text = std::move(prepared);
    return synthesize_async(std::move(prepared_request), std::move(callbacks));
}

RequestId QwenTtsClient::synthesize_async(
    PreparedTtsRequest prepared_request,
    TtsCallbacks callbacks) {
    TtsRequest request = std::move(prepared_request.request);
    PreparedText prepared = std::move(prepared_request.text);
    if (prepared.original_text != request.text) {
        try {
            if (callbacks.on_error) {
                callbacks.on_error(make_local_error(
                    request.id,
                    "client_error",
                    "prepared_text_mismatch",
                    "prepared text does not match the request source text"));
            }
        }
        catch (...) {
        }
        return 0;
    }
    if (prepared.effective_text.empty() ||
        !is_valid_utf8(prepared.effective_text)) {
        try {
            if (callbacks.on_error) {
                callbacks.on_error(make_local_error(
                    request.id,
                    "client_error",
                    "invalid_prepared_text",
                    "prepared text must be non-empty valid UTF-8"));
            }
        }
        catch (...) {
        }
        return 0;
    }
    // PreparedText is a public value type. Callers may have edited the
    // effective text after routing, so never trust cached measurements when
    // accepting the request for synthesis.
    refresh_prepared_text_metrics(prepared);
    // Keep the complete preparation receipt for downstream sideband
    // consumers while sending the exact effective text to the worker.
    request.text = prepared.effective_text;

    SynthesizeMessage message = to_control_message(request);
    ControlMessage control_message{message};
    if (!encode_control_message(control_message)) {
        return 0;
    }

    ActiveRequest active_request;
    active_request.callbacks = std::move(callbacks);
    active_request.audio_format = request.output;
    active_request.prepared_text = std::move(prepared);

    RequestId request_id = 0;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        if (!running_ || stopping_ || session_ == nullptr) {
            return 0;
        }

        request_id = allocate_request_id_locked(request.id);
        if (request_id == 0) {
            return 0;
        }

        OutboundCommand command;
        command.request_id = request_id;
        command.message = std::move(control_message);

        active_requests_.emplace(request_id, std::move(active_request));
        if (!enqueue_outbound_locked(std::move(command))) {
            active_requests_.erase(request_id);
            return 0;
        }
    }

    outbound_condition_.notify_one();
    return request_id;
}

RequestId QwenTtsClient::synthesize_async(
    const std::string& text,
    TtsCallbacks callbacks) {
    TtsRequest request;
    request.text = text;
    return synthesize_async(std::move(request), std::move(callbacks));
}

bool QwenTtsClient::cancel(RequestId request_id) {
    if (request_id == 0) {
        return false;
    }

    {
        std::lock_guard<std::mutex> lock(mutex_);
        if (!running_ ||
            stopping_ ||
            session_ == nullptr ||
            active_requests_.find(request_id) == active_requests_.end()) {
            return false;
        }

        OutboundCommand command;
        command.request_id = request_id;
        command.message = ControlMessage{CancelMessage{}};
        if (!enqueue_outbound_locked(std::move(command))) {
            return false;
        }
    }

    outbound_condition_.notify_one();
    return true;
}

bool QwenTtsClient::is_running() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return running_ && !stopping_ && session_ != nullptr;
}

std::uint64_t QwenTtsClient::late_audio_after_terminal_count() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return late_audio_after_terminal_count_;
}

std::uint64_t QwenTtsClient::duplicate_terminal_event_count() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return duplicate_terminal_event_count_;
}

bool QwenTtsClient::ready_message(ReadyMessage& ready) const {
    std::lock_guard<std::mutex> lock(mutex_);
    return running_ && !stopping_ && session_ != nullptr && session_->ready_message(ready);
}

std::vector<std::string> QwenTtsClient::available_voice_ids() const {
    std::lock_guard<std::mutex> lock(mutex_);
    ReadyMessage ready;
    if (!running_ || stopping_ || session_ == nullptr ||
        !session_->ready_message(ready)) {
        return {};
    }
    return ready.voice_ids;
}

void QwenTtsClient::stop() {
    WorkerSession* session = nullptr;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        running_ = false;
        stopping_ = true;
        clear_outbound_queue_locked();
        session = session_.get();
    }
    outbound_condition_.notify_all();

    if (session != nullptr) {
        session->stop();
    }

    join_threads();

    fail_all_requests(make_local_error(
        0,
        "client_error",
        "client_stopped",
        "QwenTtsClient stopped before request reached a terminal event"));

    const bool called_from_dispatcher = is_current_dispatcher_thread();
    std::lock_guard<std::mutex> lock(mutex_);
    if (!writer_thread_.joinable() &&
        (!dispatcher_thread_.joinable() || called_from_dispatcher)) {
        session_.reset();
        clear_outbound_queue_locked();
        stopping_ = false;
        running_ = false;
        terminal_failure_handled_ = false;
    }
}

RequestId QwenTtsClient::allocate_request_id_locked(RequestId requested_id) {
    if (requested_id != 0) {
        if (active_requests_.find(requested_id) != active_requests_.end()) {
            return 0;
        }
        if (requested_id >= next_request_id_) {
            next_request_id_ = requested_id + 1;
            if (next_request_id_ == 0) {
                next_request_id_ = 1;
            }
        }
        return requested_id;
    }

    const RequestId first_candidate = next_request_id_;
    do {
        const RequestId candidate = next_request_id_;
        ++next_request_id_;
        if (next_request_id_ == 0) {
            next_request_id_ = 1;
        }
        if (active_requests_.find(candidate) == active_requests_.end()) {
            return candidate;
        }
    } while (next_request_id_ != first_candidate);

    return 0;
}

bool QwenTtsClient::enqueue_outbound_locked(OutboundCommand command) {
    const std::size_t command_bytes = outbound_command_size(command);
    if (outbound_queue_.size() >= options_.max_outbound_commands) {
        return false;
    }
    if (command_bytes > options_.max_outbound_command_bytes ||
        queued_outbound_bytes_ >
            options_.max_outbound_command_bytes - command_bytes) {
        return false;
    }

    command.queued_bytes = command_bytes;
    queued_outbound_bytes_ += command_bytes;
    outbound_queue_.push_back(std::move(command));
    return true;
}

void QwenTtsClient::clear_outbound_queue_locked() {
    outbound_queue_.clear();
    queued_outbound_bytes_ = 0;
}

std::size_t QwenTtsClient::outbound_command_size(
    const OutboundCommand& command) const {
    return std::visit(
        [](const auto& message) -> std::size_t {
            using Message = std::decay_t<decltype(message)>;

            if constexpr (std::is_same_v<Message, HelloMessage>) {
                return outbound_command_fixed_overhead +
                    message.client_name.size() +
                    message.client_version.size();
            }
            else if constexpr (std::is_same_v<Message, SynthesizeMessage>) {
                return outbound_command_fixed_overhead +
                    message.text.size() +
                    message.language.size() +
                    message.speaker.size() +
                    message.instruction.size() +
                    message.voice_id.size() +
                    message.reference_audio_path.size() +
                    message.reference_text.size() +
                    message.output.sample_format.size() +
                    (message.has_seed ? 32u : 0u);
            }
            else if constexpr (std::is_same_v<Message, ShutdownMessage>) {
                return outbound_command_fixed_overhead + message.mode.size();
            }
            else {
                return outbound_command_fixed_overhead;
            }
        },
        command.message);
}

void QwenTtsClient::reap_finished_threads() {
    join_threads();

    std::lock_guard<std::mutex> lock(mutex_);
    if (!running_ &&
        !stopping_ &&
        !writer_thread_.joinable() &&
        !dispatcher_thread_.joinable()) {
        session_.reset();
        clear_outbound_queue_locked();
        terminal_failure_handled_ = false;
    }
}

bool QwenTtsClient::is_current_dispatcher_thread() const {
    return dispatcher_thread_.joinable() &&
        dispatcher_thread_.get_id() == std::this_thread::get_id();
}

void QwenTtsClient::writer_loop() {
    while (true) {
        OutboundCommand command;
        WorkerSession* session = nullptr;

        {
            std::unique_lock<std::mutex> lock(mutex_);
            outbound_condition_.wait(lock, [this]() {
                return stopping_ || !outbound_queue_.empty();
            });

            if (outbound_queue_.empty()) {
                if (stopping_) {
                    break;
                }
                continue;
            }

            command = std::move(outbound_queue_.front());
            queued_outbound_bytes_ -= std::min(
                queued_outbound_bytes_,
                command.queued_bytes);
            outbound_queue_.pop_front();
            session = session_.get();
        }

        if (session == nullptr) {
            continue;
        }

        session->send_control(command.request_id, command.message);
    }
}

void QwenTtsClient::dispatcher_loop() {
    while (true) {
        WorkerSession* session = nullptr;
        {
            std::lock_guard<std::mutex> lock(mutex_);
            session = session_.get();
        }

        if (session == nullptr) {
            break;
        }

        WorkerSessionEvent event;
        if (session->wait_for_event(event, std::chrono::milliseconds(100))) {
            handle_event(std::move(event));
            continue;
        }

        std::lock_guard<std::mutex> lock(mutex_);
        if (stopping_) {
            break;
        }
    }
}

void QwenTtsClient::handle_event(WorkerSessionEvent event) {
    switch (event.type) {
    case WorkerSessionEventType::Control:
        handle_control_event(event);
        break;
    case WorkerSessionEventType::Audio:
        handle_audio_event(std::move(event));
        break;
    case WorkerSessionEventType::WorkerError:
        handle_worker_error(event);
        break;
    case WorkerSessionEventType::TransportError:
        handle_local_error(event, "transport_error", "transport_error");
        break;
    case WorkerSessionEventType::ProtocolError:
        handle_local_error(event, "protocol_error", "protocol_error");
        break;
    case WorkerSessionEventType::SessionError:
        handle_local_error(event, "session_error", "session_error");
        break;
    case WorkerSessionEventType::Exited:
        handle_local_error(event, "transport_error", "worker_exited");
        break;
    }
}

void QwenTtsClient::handle_control_event(const WorkerSessionEvent& event) {
    switch (control_message_type(event.control)) {
    case ControlMessageType::Started: {
        const auto& started = std::get<StartedMessage>(event.control);
        TtsCallbacks callbacks;
        std::optional<PreparedText> prepared_text;
        {
            std::lock_guard<std::mutex> lock(mutex_);
            auto it = active_requests_.find(event.request_id);
            if (it != active_requests_.end()) {
                it->second.audio_format = started.audio_format;
                if (it->second.prepared_text.has_value() &&
                    !it->second.text_context_delivered) {
                    callbacks = it->second.callbacks;
                    prepared_text = it->second.prepared_text;
                    it->second.text_context_delivered = true;
                }
            }
        }
        if (prepared_text.has_value() && callbacks.on_text_prepared) {
            invoke_user_callback([&callbacks, &prepared_text]() {
                callbacks.on_text_prepared(prepared_text.value());
            });
        }
        break;
    }
    case ControlMessageType::Completed:
        complete_request(event.request_id, std::get<CompletedMessage>(event.control));
        break;
    case ControlMessageType::Cancelled:
        cancel_request_locally(event.request_id);
        break;
    case ControlMessageType::Ready:
    case ControlMessageType::Queued:
    case ControlMessageType::Pong:
    case ControlMessageType::ShutdownAck:
    case ControlMessageType::Hello:
    case ControlMessageType::Synthesize:
    case ControlMessageType::Cancel:
    case ControlMessageType::Ping:
    case ControlMessageType::Shutdown:
        break;
    }
}

void QwenTtsClient::handle_audio_event(WorkerSessionEvent event) {
    TtsCallbacks callbacks;
    AudioFormat format;
    std::optional<PreparedText> prepared_text;
    std::uint64_t first_sample = 0;
    std::uint32_t sample_count = 0;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        auto it = active_requests_.find(event.request_id);
        if (it == active_requests_.end()) {
            ++late_audio_after_terminal_count_;
            return;
        }
        callbacks = it->second.callbacks;
        format = it->second.audio_format;
        if (it->second.prepared_text.has_value() &&
            !it->second.text_context_delivered) {
            prepared_text = it->second.prepared_text;
            it->second.text_context_delivered = true;
        }
        first_sample = it->second.next_sample;
        if (const auto count = sample_count_for_audio(format, event.audio.size());
            count.has_value()) {
            sample_count = count.value();
            it->second.next_sample += sample_count;
        }
    }

    if (prepared_text.has_value() && callbacks.on_text_prepared) {
        invoke_user_callback([&callbacks, &prepared_text]() {
            callbacks.on_text_prepared(prepared_text.value());
        });
    }

    PcmChunk chunk;
    chunk.request_id = event.request_id;
    chunk.format = format;
    chunk.first_sample = first_sample;
    chunk.sample_count = sample_count;
    chunk.bytes = std::move(event.audio);

    if (!chunk.bytes.empty()) {
        if (callbacks.on_audio) {
            invoke_user_callback([&callbacks, &chunk]() {
                callbacks.on_audio(chunk);
            });
        }
        if (callbacks.on_timing && chunk.sample_count != 0) {
            SpeechTimingChunk timing;
            timing.request_id = chunk.request_id;
            timing.first_sample = chunk.first_sample;
            timing.sample_count = chunk.sample_count;
            timing.sample_rate = chunk.format.sample_rate;
            invoke_user_callback([&callbacks, &timing]() {
                callbacks.on_timing(timing);
            });
        }
    }
}

void QwenTtsClient::handle_worker_error(const WorkerSessionEvent& event) {
    TtsError error;
    error.request_id = event.request_id;
    error.category = event.error.category;
    error.code = event.error.code;
    error.message = event.error.message;

    if (event.request_id == 0) {
        fail_all_requests(std::move(error));
    }
    else {
        fail_request(event.request_id, std::move(error));
    }
}

void QwenTtsClient::handle_local_error(
    const WorkerSessionEvent& event,
    const std::string& category,
    const std::string& code) {
    WorkerSession* session = nullptr;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        if (terminal_failure_handled_) {
            return;
        }
        terminal_failure_handled_ = true;
        running_ = false;
        stopping_ = true;
        clear_outbound_queue_locked();
        session = session_.get();
    }
    outbound_condition_.notify_all();

    if (session != nullptr) {
        session->stop();
    }

    const std::string message = event.message.empty()
        ? code
        : event.message;

    fail_all_requests(make_local_error(
        event.request_id,
        category,
        code,
        message));
}

void QwenTtsClient::complete_request(
    RequestId request_id,
    const CompletedMessage& completed) {
    TtsCallbacks callbacks;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        auto it = active_requests_.find(request_id);
        if (it == active_requests_.end()) {
            ++duplicate_terminal_event_count_;
            return;
        }
        callbacks = std::move(it->second.callbacks);
        active_requests_.erase(it);
    }

    if (callbacks.on_completion_metadata) {
        TtsCompletion completion;
        completion.execution_outcome = completed.execution_outcome;
        completion.has_generation_trace = completed.has_generation_trace;
        completion.termination_reason = completed.generation_trace.termination_reason;
        completion.hit_eos = completed.generation_trace.hit_eos;
        completion.hit_max_seq_len = completed.generation_trace.hit_max_seq_len;
        completion.hit_max_new_tokens = completed.generation_trace.hit_max_new_tokens;
        completion.codec_frame_count = completed.generation_trace.codec_frame_count;
        completion.generated_steps = completed.generation_trace.generated_steps;
        completion.emitted_steps = completed.generation_trace.emitted_steps;
        completion.terminal_step_index = completed.generation_trace.terminal_step_index;
        invoke_user_callback([&callbacks, &completion]() {
            callbacks.on_completion_metadata(completion);
        });
    }

    if (callbacks.on_completed) {
        invoke_user_callback(callbacks.on_completed);
    }
}

void QwenTtsClient::cancel_request_locally(RequestId request_id) {
    TtsCallbacks callbacks;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        auto it = active_requests_.find(request_id);
        if (it == active_requests_.end()) {
            ++duplicate_terminal_event_count_;
            return;
        }
        callbacks = std::move(it->second.callbacks);
        active_requests_.erase(it);
    }

    if (callbacks.on_cancelled) {
        invoke_user_callback(callbacks.on_cancelled);
    }
}

void QwenTtsClient::fail_request(RequestId request_id, TtsError error) {
    TtsCallbacks callbacks;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        auto it = active_requests_.find(request_id);
        if (it == active_requests_.end()) {
            ++duplicate_terminal_event_count_;
            return;
        }
        callbacks = std::move(it->second.callbacks);
        active_requests_.erase(it);
    }

    if (callbacks.on_error) {
        invoke_user_callback([&callbacks, &error]() {
            callbacks.on_error(error);
        });
    }
}

void QwenTtsClient::fail_all_requests(TtsError error) {
    std::vector<std::pair<RequestId, TtsCallbacks>> callbacks;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        callbacks.reserve(active_requests_.size());
        for (auto& item : active_requests_) {
            callbacks.emplace_back(item.first, std::move(item.second.callbacks));
        }
        active_requests_.clear();
    }

    for (auto& item : callbacks) {
        auto& callback_set = item.second;
        if (callback_set.on_error) {
            TtsError request_error = error;
            if (request_error.request_id == 0) {
                request_error.request_id = item.first;
            }
            invoke_user_callback([&callback_set, &request_error]() {
                callback_set.on_error(request_error);
            });
        }
    }
}

void QwenTtsClient::invoke_user_callback(
    const std::function<void()>& callback) noexcept {
    if (!callback) {
        return;
    }

    try {
        callback();
    }
    catch (...) {
        report_callback_exception(std::current_exception());
    }
}

void QwenTtsClient::report_callback_exception(
    std::exception_ptr exception) noexcept {
    std::function<void(std::exception_ptr)> handler;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        handler = options_.on_callback_exception;
    }

    if (!handler) {
        return;
    }

    try {
        handler(std::move(exception));
    }
    catch (...) {
    }
}

void QwenTtsClient::join_threads() {
    const auto current_thread = std::this_thread::get_id();

    if (writer_thread_.joinable() &&
        writer_thread_.get_id() != current_thread) {
        writer_thread_.join();
    }

    if (dispatcher_thread_.joinable() &&
        dispatcher_thread_.get_id() != current_thread) {
        dispatcher_thread_.join();
    }
}

} // namespace qwen_tts_bridge
