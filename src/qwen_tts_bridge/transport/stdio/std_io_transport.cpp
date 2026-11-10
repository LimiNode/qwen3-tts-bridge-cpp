#include "std_io_transport.hpp"

#include <process.hpp>

#include <condition_variable>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <limits>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <thread>
#include <type_traits>
#include <utility>

#if defined(_WIN32)
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#endif

#if !defined(_WIN32)
extern char** environ;
#endif

namespace qwen_tts_bridge {
namespace {

enum class ProcessState {
    Stopped,
    Starting,
    Running,
    Stopping
};

enum class CallbackEventType {
    Receive,
    Error,
    Exit,
    Stderr
};

struct CallbackEvent {
    CallbackEventType type = CallbackEventType::Error;
    ITransport::Bytes bytes;
    std::string message;
    int exit_status = -1;
};

static_assert(std::is_nothrow_move_assignable<CallbackEvent>::value,
    "Retaining Exit during callback failure must not allocate or throw");

std::size_t callback_event_payload_size(const CallbackEvent& event) {
    return event.bytes.size() + event.message.size();
}

TinyProcessLib::Process::string_type to_process_string(const std::string& value) {
#if defined(_WIN32) && defined(UNICODE)
    if (value.empty()) {
        return {};
    }

    if (value.size() > static_cast<std::size_t>(std::numeric_limits<int>::max())) {
        throw std::invalid_argument("process string is too large to convert from UTF-8");
    }

    const auto input_size = static_cast<int>(value.size());
    const int required_size = MultiByteToWideChar(
        CP_UTF8,
        MB_ERR_INVALID_CHARS,
        value.data(),
        input_size,
        nullptr,
        0);

    if (required_size <= 0) {
        throw std::invalid_argument("invalid UTF-8 process string");
    }

    TinyProcessLib::Process::string_type converted(
        static_cast<std::size_t>(required_size),
        L'\0');
    const int written_size = MultiByteToWideChar(
        CP_UTF8,
        MB_ERR_INVALID_CHARS,
        value.data(),
        input_size,
        converted.data(),
        required_size);

    if (written_size != required_size) {
        throw std::invalid_argument("failed to convert process string from UTF-8");
    }

    return converted;
#else
    return value;
#endif
}

std::string from_process_string(const TinyProcessLib::Process::string_type& value) {
#if defined(_WIN32) && defined(UNICODE)
    if (value.empty()) {
        return {};
    }

    if (value.size() > static_cast<std::size_t>(std::numeric_limits<int>::max())) {
        throw std::invalid_argument("process string is too large to convert to UTF-8");
    }

    const auto input_size = static_cast<int>(value.size());
    const int required_size = WideCharToMultiByte(
        CP_UTF8,
        WC_ERR_INVALID_CHARS,
        value.data(),
        input_size,
        nullptr,
        0,
        nullptr,
        nullptr);

    if (required_size <= 0) {
        throw std::invalid_argument("invalid process environment string");
    }

    std::string converted(static_cast<std::size_t>(required_size), '\0');
    const int written_size = WideCharToMultiByte(
        CP_UTF8,
        WC_ERR_INVALID_CHARS,
        value.data(),
        input_size,
        converted.data(),
        required_size,
        nullptr,
        nullptr);

    if (written_size != required_size) {
        throw std::invalid_argument("failed to convert process string to UTF-8");
    }

    return converted;
#else
    return value;
#endif
}

bool is_started_process_id(TinyProcessLib::Process::id_type id) {
#if defined(_WIN32)
    return id != 0;
#else
    return id > 0;
#endif
}

std::vector<TinyProcessLib::Process::string_type> to_process_arguments(
    const std::vector<std::string>& arguments) {
    std::vector<TinyProcessLib::Process::string_type> converted;
    converted.reserve(arguments.size());
    for (const auto& argument : arguments) {
        converted.push_back(to_process_string(argument));
    }
    return converted;
}

bool environment_key_equals(const std::string& left, const std::string& right) {
#if defined(_WIN32) && defined(UNICODE)
    const auto converted_left = to_process_string(left);
    const auto converted_right = to_process_string(right);
    return CompareStringOrdinal(
        converted_left.data(),
        static_cast<int>(converted_left.size()),
        converted_right.data(),
        static_cast<int>(converted_right.size()),
        TRUE) == CSTR_EQUAL;
#elif defined(_WIN32)
    return _stricmp(left.c_str(), right.c_str()) == 0;
#else
    return left == right;
#endif
}

void set_environment_override(
    std::unordered_map<std::string, std::string>& environment,
    const std::string& name,
    const std::string& value) {
    for (auto it = environment.begin(); it != environment.end();) {
        if (environment_key_equals(it->first, name)) {
            it = environment.erase(it);
        }
        else {
            ++it;
        }
    }

    environment.emplace(name, value);
}

std::unordered_map<std::string, std::string> current_process_environment() {
    std::unordered_map<std::string, std::string> environment;

#if defined(_WIN32)
#if defined(UNICODE)
    LPWCH environment_block = GetEnvironmentStringsW();
#else
    LPCH environment_block = GetEnvironmentStringsA();
#endif
    if (environment_block == nullptr) {
        throw std::runtime_error("failed to read current process environment");
    }

    try {
        auto* entry = environment_block;
        while (*entry != 0) {
            TinyProcessLib::Process::string_type item(entry);
            entry += item.size() + 1;

            const auto separator = item.find(
                static_cast<TinyProcessLib::Process::string_type::value_type>('='),
                1);
            if (separator == TinyProcessLib::Process::string_type::npos) {
                continue;
            }

            environment.emplace(
                from_process_string(item.substr(0, separator)),
                from_process_string(item.substr(separator + 1)));
        }
    }
    catch (...) {
        FreeEnvironmentStrings(environment_block);
        throw;
    }

    FreeEnvironmentStrings(environment_block);
#else
    for (char** entry = ::environ; entry != nullptr && *entry != nullptr; ++entry) {
        const std::string item(*entry);
        const auto separator = item.find('=');
        if (separator == std::string::npos) {
            continue;
        }

        environment.emplace(item.substr(0, separator), item.substr(separator + 1));
    }
#endif

    return environment;
}

std::unordered_map<std::string, std::string> merged_process_environment(
    const std::unordered_map<std::string, std::string>& overrides) {
    auto environment = current_process_environment();
    for (const auto& item : overrides) {
        set_environment_override(environment, item.first, item.second);
    }
    return environment;
}

TinyProcessLib::Process::environment_type to_process_environment(
    const std::unordered_map<std::string, std::string>& environment) {
    TinyProcessLib::Process::environment_type converted;
    for (const auto& item : environment) {
        converted.emplace(to_process_string(item.first), to_process_string(item.second));
    }
    return converted;
}

} // namespace

class StdIoTransport::Impl {
public:
    explicit Impl(StdIoTransportOptions options)
        : options_(std::move(options)) {}

    ~Impl() {
        stop();
    }

    bool start(
        ReceiveHandler receive_handler,
        ErrorHandler error_handler,
        ExitHandler exit_handler) {
        std::unique_lock<std::mutex> lifecycle_lock(lifecycle_mutex_);

        if (options_.arguments.empty()) {
            lifecycle_lock.unlock();
            call_error(error_handler, "stdio transport requires at least one process argument");
            return false;
        }

        if (options_.max_callback_queue_events == 0 || options_.max_callback_queue_bytes == 0) {
            lifecycle_lock.unlock();
            call_error(error_handler, "stdio transport callback queue limits must be greater than zero");
            return false;
        }

        if (is_callback_thread()) {
            lifecycle_lock.unlock();
            call_error(error_handler, "stdio transport cannot be started from a transport callback");
            return false;
        }

        bool already_started = false;
        {
            std::lock_guard<std::mutex> lock(state_mutex_);
            already_started = state_ != ProcessState::Stopped || process_ != nullptr;
        }
        if (already_started) {
            lifecycle_lock.unlock();
            call_error(error_handler, "stdio transport is already started");
            return false;
        }

        join_exit_thread_if_needed();
        request_callback_thread_stop();
        join_callback_thread_if_needed();

        {
            std::lock_guard<std::mutex> lock(state_mutex_);
            state_ = ProcessState::Starting;
            receive_handler_ = std::move(receive_handler);
            error_handler_ = std::move(error_handler);
            exit_handler_ = std::move(exit_handler);
            exited_ = false;
            exit_status_ = -1;
        }

        try {
            start_callback_thread();

            TinyProcessLib::Config config;
            config.buffer_size = options_.read_buffer_size;
            config.show_window = TinyProcessLib::Config::ShowWindow::hide;

            auto stdout_handler = [this](const char* bytes, std::size_t size) {
                handle_stdout(bytes, size);
            };
            auto stderr_handler = [this](const char* bytes, std::size_t size) {
                handle_stderr(bytes, size);
            };

            auto arguments = to_process_arguments(options_.arguments);
            const auto working_directory = to_process_string(options_.working_directory);

            std::shared_ptr<TinyProcessLib::Process> process;
            if (options_.environment.empty() && options_.environment_overrides.empty()) {
                process = std::make_shared<TinyProcessLib::Process>(
                    arguments,
                    working_directory,
                    stdout_handler,
                    stderr_handler,
                    true,
                    config);
            }
            else {
                const auto source_environment = options_.environment.empty()
                    ? merged_process_environment(options_.environment_overrides)
                    : options_.environment;
                auto environment = to_process_environment(source_environment);
                process = std::make_shared<TinyProcessLib::Process>(
                    arguments,
                    working_directory,
                    environment,
                    stdout_handler,
                    stderr_handler,
                    true,
                    config);
            }

            if (!is_started_process_id(process->get_id())) {
                const auto handler = fail_start();
                lifecycle_lock.unlock();
                call_error(handler, "failed to start stdio worker process");
                return false;
            }

            bool stop_on_registration = false;
            {
                std::lock_guard<std::mutex> lock(state_mutex_);
                process_ = process;
                stop_on_registration = state_ != ProcessState::Starting;
                if (!stop_on_registration) {
                    state_ = ProcessState::Running;
                }
            }

            exit_thread_ = std::thread([this, process]() {
                watch_process_exit(std::move(process));
            });

            // Readers may enqueue stdout during the Process constructor, but
            // callbacks must not run until both process ownership and the
            // terminal-event producer are registered.
            {
                std::lock_guard<std::mutex> lock(callback_mutex_);
                callback_dispatch_ready_ = true;
            }
            callback_condition_.notify_all();
            if (stop_on_registration) {
                process->kill(true);
            }
            return !stop_on_registration;
        }
        catch (const std::exception& exc) {
            const auto handler = fail_start();
            lifecycle_lock.unlock();
            call_error(handler, exc.what());
            return false;
        }
        catch (...) {
            const auto handler = fail_start();
            lifecycle_lock.unlock();
            call_error(handler, "unknown stdio transport startup error");
            return false;
        }
    }

    SendResult send(const std::byte* data, std::size_t size) {
        if (data == nullptr && size != 0) {
            report_error("cannot send a non-zero byte count from a null pointer");
            return SendResult::Failed;
        }

        if (size == 0) {
            return SendResult::Accepted;
        }

        std::shared_ptr<TinyProcessLib::Process> process;
        {
            std::lock_guard<std::mutex> lock(state_mutex_);
            if (state_ == ProcessState::Running && !exited_) {
                process = process_;
            }
        }

        if (process == nullptr) {
            report_error("stdio transport is not running");
            return SendResult::Closed;
        }

        bool ok = false;
        std::string write_error;

        {
            std::lock_guard<std::mutex> write_lock(write_mutex_);

            {
                std::lock_guard<std::mutex> state_lock(state_mutex_);
                if (state_ != ProcessState::Running || process_ != process || exited_) {
                    report_error("stdio transport is not running");
                    return SendResult::Closed;
                }
            }

            try {
                ok = process->write(reinterpret_cast<const char*>(data), size);
            }
            catch (const std::exception& exc) {
                ok = false;
                write_error = exc.what();
            }
            catch (...) {
                ok = false;
                write_error = "unknown worker stdin write error";
            }
        }

        if (!ok) {
            const auto message = write_error.empty()
                ? std::string("failed to write bytes to worker stdin")
                : write_error;
            report_error(message);
            return SendResult::Failed;
        }

        return SendResult::Accepted;
    }

    bool is_running() const {
        std::lock_guard<std::mutex> lock(state_mutex_);
        return state_ == ProcessState::Running && process_ != nullptr && !exited_;
    }

    void stop() {
        const bool called_from_callback_thread = is_callback_thread();
        // A callback may re-enter stop() while another thread is already
        // shutting the transport down. That thread may hold lifecycle_mutex_
        // while waiting for this callback thread to finish. Waiting for the
        // same mutex here would deadlock the shutdown. External start/stop
        // calls remain serialized by the lifecycle mutex; the callback path
        // only performs the idempotent shutdown work below and never joins
        // itself.
        std::unique_lock<std::mutex> lifecycle_lock(lifecycle_mutex_, std::defer_lock);
        if (!called_from_callback_thread) {
            lifecycle_lock.lock();
        }

        {
            // Callback and external stop calls may overlap after the callback
            // path bypasses lifecycle_mutex_. Serialize the actual process
            // teardown separately, and release it before an external caller
            // joins the callback thread.
            std::lock_guard<std::mutex> shutdown_lock(shutdown_mutex_);

            std::shared_ptr<TinyProcessLib::Process> process;
            {
                std::lock_guard<std::mutex> lock(state_mutex_);
                process = process_;
                if (state_ == ProcessState::Running || state_ == ProcessState::Starting) {
                    state_ = ProcessState::Stopping;
                }
            }

            if (process != nullptr) {
                close_stdin_if_write_is_idle(process);
                wait_for_process_or_kill(process);
                join_exit_thread_if_needed();
            }
            {
                std::lock_guard<std::mutex> lock(state_mutex_);
                process_.reset();
                state_ = ProcessState::Stopped;
            }

            request_callback_thread_stop();
        }

        if (!called_from_callback_thread) {
            join_callback_thread_if_needed();

            std::lock_guard<std::mutex> lock(state_mutex_);
            clear_handlers_locked();
        }
    }

private:
    ErrorHandler fail_start() {
        ErrorHandler handler;
        std::shared_ptr<TinyProcessLib::Process> process;
        {
            std::lock_guard<std::mutex> lock(state_mutex_);
            process = process_;
            handler = error_handler_;
        }

        if (process != nullptr && is_started_process_id(process->get_id())) {
            process->kill(true);
        }

        join_exit_thread_if_needed();
        request_callback_thread_stop();
        join_callback_thread_if_needed();

        {
            std::lock_guard<std::mutex> lock(state_mutex_);
            process_.reset();
            state_ = ProcessState::Stopped;
            exited_ = false;
            clear_handlers_locked();
        }

        return handler;
    }

    void watch_process_exit(std::shared_ptr<TinyProcessLib::Process> process) {
        // Tiny-process get_exit_status() closes pipes and joins stdout/stderr
        // reader threads before returning. Queue Exit only after that, so all
        // Receive/Stderr events produced by those readers are already queued.
        const int status = process->get_exit_status();

        {
            std::lock_guard<std::mutex> lock(state_mutex_);
            exit_status_ = status;
            exited_ = true;
            if (process_ == process && state_ != ProcessState::Stopped) {
                state_ = ProcessState::Stopped;
            }
        }
        exit_condition_.notify_all();

        CallbackEvent event;
        event.type = CallbackEventType::Exit;
        event.exit_status = status;
        enqueue_event(std::move(event));
    }

    void handle_stdout(const char* bytes, std::size_t size) {
        if (bytes == nullptr || size == 0) {
            return;
        }

        Bytes out(size);
        std::memcpy(out.data(), bytes, size);

        CallbackEvent event;
        event.type = CallbackEventType::Receive;
        event.bytes = std::move(out);
        enqueue_event(std::move(event));
    }

    void handle_stderr(const char* bytes, std::size_t size) {
        if (bytes == nullptr || size == 0 || !options_.stderr_handler) {
            return;
        }

        CallbackEvent event;
        event.type = CallbackEventType::Stderr;
        event.message.assign(bytes, size);
        enqueue_event(std::move(event));
    }

    void report_error(const std::string& message) {
        CallbackEvent event;
        event.type = CallbackEventType::Error;
        event.message = message;
        enqueue_event(std::move(event));
    }

    void start_callback_thread() {
        {
            std::lock_guard<std::mutex> lock(callback_mutex_);
            callback_events_.clear();
            callback_queued_bytes_ = 0;
            callback_queue_overflowed_ = false;
            callback_stop_requested_ = false;
            callback_accepting_events_ = true;
            callback_failed_ = false;
            callback_dispatch_ready_ = false;
        }

        callback_thread_ = std::thread([this]() {
            callback_loop();
        });
    }

    void callback_loop() {
        while (true) {
            CallbackEvent event;

            {
                std::unique_lock<std::mutex> lock(callback_mutex_);
                callback_condition_.wait(lock, [this]() {
                    return callback_stop_requested_
                        || (callback_dispatch_ready_ && !callback_events_.empty());
                });

                if (callback_stop_requested_
                    && (!callback_dispatch_ready_ || callback_events_.empty())) {
                    break;
                }

                event = std::move(callback_events_.front());
                callback_events_.pop_front();
                callback_queued_bytes_ -= callback_event_payload_size(event);
            }

            const bool is_exit = event.type == CallbackEventType::Exit;
            try {
                dispatch_event(std::move(event));
            }
            catch (...) {
                // Transport callbacks are internal session hooks, but they
                // still cross a user-owned boundary indirectly.  Letting an
                // exception escape this thread would terminate the process.
                // Fail closed instead and make the worker lifecycle stop.
                fail_callback_dispatch();
                if (is_exit) {
                    break;
                }
                continue;
            }

            if (is_exit) {
                break;
            }
        }
    }

    void fail_callback_dispatch() noexcept {
        std::shared_ptr<TinyProcessLib::Process> process;
        try {
            {
                std::lock_guard<std::mutex> callback_lock(callback_mutex_);
                callback_accepting_events_ = false;
                callback_failed_ = true;
                // Discard ordinary events, but retain an Exit that was already
                // queued before the failing callback. The exit watcher may have
                // completed before this method runs, so dropping it would leave
                // the callback thread waiting forever for an event that cannot be
                // published again.
                auto exit_event = callback_events_.end();
                for (auto it = callback_events_.begin(); it != callback_events_.end(); ++it) {
                    if (it->type == CallbackEventType::Exit) {
                        exit_event = it;
                        break;
                    }
                }
                if (exit_event == callback_events_.end()) {
                    callback_events_.clear();
                }
                else {
                    if (exit_event != callback_events_.begin()) {
                        callback_events_.front() = std::move(*exit_event);
                    }
                    while (callback_events_.size() > 1) {
                        callback_events_.pop_back();
                    }
                }
                callback_queued_bytes_ = 0;
                for (const auto& event : callback_events_) {
                    callback_queued_bytes_ += callback_event_payload_size(event);
                }
            }
            {
                std::lock_guard<std::mutex> state_lock(state_mutex_);
                process = process_;
                if (state_ == ProcessState::Running || state_ == ProcessState::Starting) {
                    state_ = ProcessState::Stopping;
                }
            }
        }
        catch (...) {
            callback_condition_.notify_all();
            return;
        }
        callback_condition_.notify_all();

        if (process != nullptr) {
            try {
                process->kill(true);
            }
            catch (...) {
                // The exit watcher still owns the final lifecycle cleanup.
            }
        }
    }

    void dispatch_event(CallbackEvent event) {
        if (event.type == CallbackEventType::Receive) {
            ReceiveHandler handler;
            {
                std::lock_guard<std::mutex> lock(state_mutex_);
                handler = receive_handler_;
            }
            if (handler) {
                handler(std::move(event.bytes));
            }
            return;
        }

        if (event.type == CallbackEventType::Error) {
            ErrorHandler handler;
            {
                std::lock_guard<std::mutex> lock(state_mutex_);
                handler = error_handler_;
            }
            call_error(handler, event.message);
            return;
        }

        if (event.type == CallbackEventType::Exit) {
            ExitHandler handler;
            {
                std::lock_guard<std::mutex> lock(state_mutex_);
                handler = exit_handler_;
            }
            if (handler) {
                handler(event.exit_status);
            }
            return;
        }

        if (event.type == CallbackEventType::Stderr && options_.stderr_handler) {
            options_.stderr_handler(std::move(event.message));
        }
    }

    void enqueue_event(CallbackEvent event) {
        bool should_stop = false;
        {
            std::lock_guard<std::mutex> lock(callback_mutex_);
            if (!callback_accepting_events_
                && !(callback_failed_ && event.type == CallbackEventType::Exit)) {
                return;
            }

            if (callback_queue_overflowed_ && event.type != CallbackEventType::Exit) {
                return;
            }

            if (event.type != CallbackEventType::Exit
                && would_overflow_regular_callback_queue(event)) {
                if (!callback_queue_overflowed_) {
                    callback_queue_overflowed_ = true;
                    enqueue_callback_event_locked(make_callback_queue_overflow_error());
                    should_stop = true;
                }
            }
            else {
                enqueue_callback_event_locked(std::move(event));
            }
        }
        callback_condition_.notify_one();

        if (should_stop) {
            stop_after_callback_queue_overflow();
        }
    }

    bool would_overflow_regular_callback_queue(const CallbackEvent& event) const {
        const auto event_size = callback_event_payload_size(event);
        return callback_events_.size() >= options_.max_callback_queue_events
            || event_size > options_.max_callback_queue_bytes
            || callback_queued_bytes_ > options_.max_callback_queue_bytes - event_size;
    }

    CallbackEvent make_callback_queue_overflow_error() const {
        CallbackEvent event;
        event.type = CallbackEventType::Error;
        event.message = "stdio transport callback queue overflow";
        return event;
    }

    void enqueue_callback_event_locked(CallbackEvent event) {
        callback_queued_bytes_ += callback_event_payload_size(event);
        callback_events_.push_back(std::move(event));
    }

    void stop_after_callback_queue_overflow() {
        std::shared_ptr<TinyProcessLib::Process> process;
        {
            std::lock_guard<std::mutex> lock(state_mutex_);
            process = process_;
            if (state_ == ProcessState::Running || state_ == ProcessState::Starting) {
                state_ = ProcessState::Stopping;
            }
        }

        if (process != nullptr) {
            process->kill(true);
        }
    }

    void request_callback_thread_stop() {
        {
            std::lock_guard<std::mutex> lock(callback_mutex_);
            callback_accepting_events_ = false;
            callback_stop_requested_ = true;
        }
        callback_condition_.notify_all();
    }

    void close_stdin_if_write_is_idle(const std::shared_ptr<TinyProcessLib::Process>& process) {
        std::unique_lock<std::mutex> write_lock(write_mutex_, std::try_to_lock);
        if (!write_lock.owns_lock()) {
            return;
        }

        process->close_stdin();
    }

    void wait_for_process_or_kill(const std::shared_ptr<TinyProcessLib::Process>& process) {
        bool timed_out = false;
        {
            std::unique_lock<std::mutex> lock(state_mutex_);
            timed_out = !exit_condition_.wait_for(lock, options_.shutdown_timeout, [this]() {
                return exited_;
            });
        }

        if (timed_out) {
            process->kill(true);
        }
    }

    static void call_error(const ErrorHandler& handler, const std::string& message) {
        if (handler) {
            handler(message);
        }
    }

    void join_exit_thread_if_needed() {
        if (!exit_thread_.joinable()) {
            return;
        }

        if (exit_thread_.get_id() == std::this_thread::get_id()) {
            exit_thread_.detach();
            return;
        }

        exit_thread_.join();
    }

    bool is_callback_thread() const {
        return callback_thread_.joinable()
            && callback_thread_.get_id() == std::this_thread::get_id();
    }

    void join_callback_thread_if_needed() {
        if (!callback_thread_.joinable()) {
            return;
        }

        if (is_callback_thread()) {
            return;
        }

        callback_thread_.join();
    }

    void clear_handlers_locked() {
        receive_handler_ = nullptr;
        error_handler_ = nullptr;
        exit_handler_ = nullptr;
    }

    StdIoTransportOptions options_;

    mutable std::mutex lifecycle_mutex_;
    std::mutex shutdown_mutex_;
    mutable std::mutex state_mutex_;
    std::mutex write_mutex_;
    std::condition_variable exit_condition_;
    std::shared_ptr<TinyProcessLib::Process> process_;
    std::thread exit_thread_;
    std::thread callback_thread_;

    std::mutex callback_mutex_;
    std::condition_variable callback_condition_;
    std::deque<CallbackEvent> callback_events_;
    std::size_t callback_queued_bytes_ = 0;
    bool callback_stop_requested_ = false;
    bool callback_accepting_events_ = false;
    bool callback_failed_ = false;
    bool callback_dispatch_ready_ = false;
    bool callback_queue_overflowed_ = false;

    ReceiveHandler receive_handler_;
    ErrorHandler error_handler_;
    ExitHandler exit_handler_;

    ProcessState state_ = ProcessState::Stopped;
    bool exited_ = false;
    int exit_status_ = -1;
};

StdIoTransport::StdIoTransport(StdIoTransportOptions options)
    : impl_(std::make_unique<Impl>(std::move(options))) {}

StdIoTransport::~StdIoTransport() = default;

bool StdIoTransport::start(
    ReceiveHandler receive_handler,
    ErrorHandler error_handler,
    ExitHandler exit_handler) {
    return impl_->start(
        std::move(receive_handler),
        std::move(error_handler),
        std::move(exit_handler));
}

SendResult StdIoTransport::send(const std::byte* data, std::size_t size) {
    return impl_->send(data, size);
}

bool StdIoTransport::is_running() const {
    return impl_->is_running();
}

void StdIoTransport::stop() {
    impl_->stop();
}

} // namespace qwen_tts_bridge
