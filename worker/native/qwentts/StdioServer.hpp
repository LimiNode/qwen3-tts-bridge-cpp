#pragma once

#include "NativeEngine.hpp"

#include <qwen_tts_bridge/protocol/framing.hpp>

#include <atomic>
#include <condition_variable>
#include <cstddef>
#include <cstdint>
#include <deque>
#include <memory>
#include <mutex>
#include <thread>
#include <unordered_map>
#include <unordered_set>
#include <vector>

namespace qwen_tts_bridge::native_worker {

class StdioServer final {
public:
    explicit StdioServer(NativeEngine& engine);
    ~StdioServer();

    StdioServer(const StdioServer&) = delete;
    StdioServer& operator=(const StdioServer&) = delete;

    int run();

private:
    enum class RequestState { Queued, Running };

    struct RequestSlot {
        RequestId id = 0;
        SynthesizeMessage request;
        RequestState state = RequestState::Queued;
        std::atomic<bool> cancelled{false};
        std::atomic<bool> terminal{false};
    };

    class OutputWriter;

    void read_loop();
    bool handle_frame(Frame frame);
    void handle_hello(RequestId request_id);
    void handle_ping(RequestId request_id, const PingMessage& message);
    void handle_synthesize(RequestId request_id, SynthesizeMessage message);
    void handle_cancel(RequestId request_id);
    bool handle_shutdown(RequestId request_id, const ShutdownMessage& message);
    void request_shutdown(bool send_ack);
    void engine_loop();
    std::shared_ptr<RequestSlot> take_next_request();
    void run_request(const std::shared_ptr<RequestSlot>& slot);
    bool terminalize(const std::shared_ptr<RequestSlot>& slot);
    void send_control(RequestId request_id, ControlMessage message);
    void send_error(
        RequestId request_id,
        std::string category,
        std::string code,
        std::string message);
    void fail_fatal(const std::string& message);

    NativeEngine& engine_;
    FrameParser parser_;
    std::unique_ptr<OutputWriter> writer_;
    std::thread engine_thread_;
    std::mutex mutex_;
    std::condition_variable condition_;
    std::deque<std::shared_ptr<RequestSlot>> pending_;
    std::unordered_map<RequestId, std::shared_ptr<RequestSlot>> active_;
    std::unordered_set<RequestId> terminal_ids_;
    bool hello_seen_ = false;
    bool ready_sent_ = false;
    bool shutdown_requested_ = false;
    bool shutdown_ack_needed_ = false;
    bool shutdown_terminals_enqueued_ = false;
    bool fatal_error_ = false;
};

std::vector<std::byte> float_pcm_to_s16le(const float* samples, int count);

} // namespace qwen_tts_bridge::native_worker
