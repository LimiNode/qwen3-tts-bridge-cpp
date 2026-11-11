#include <qwen_tts_bridge/audio.hpp>

#include "play.hpp"

#include "common/pcm_capture.hpp"
#include "common/wav_capture.hpp"
#include "qwen_tts_play_completion_policy.hpp"

#ifdef QWEN_TTS_BRIDGE_HAS_SPEECH_ANIMATION
#include <qwen_tts_bridge/integration/speech_animation/playback_animation_runtime.hpp>
#endif

#define WIN32_LEAN_AND_MEAN
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <array>
#include <cctype>
#include <cmath>
#include <condition_variable>
#include <cstdint>
#include <cstring>
#include <deque>
#include <exception>
#include <filesystem>
#include <fstream>
#include <functional>
#include <iomanip>
#include <iostream>
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

using namespace qwen_tts_examples::play;

namespace {

using qwen_tts_bridge::AudioFormat;
using qwen_tts_bridge::PcmChunk;
using qwen_tts_bridge::PreparedText;
using qwen_tts_bridge::PreparedTtsRequest;
using qwen_tts_bridge::QwenTtsClient;
using qwen_tts_bridge::QwenTtsClientOptions;
using qwen_tts_bridge::ReadyMessage;
using qwen_tts_bridge::RequestId;
using qwen_tts_bridge::StdIoTransportOptions;
using qwen_tts_bridge::TtsCallbacks;
using qwen_tts_bridge::TtsCompletion;
using qwen_tts_bridge::TtsError;
using qwen_tts_bridge::TtsRequest;
using qwen_tts_bridge::audio::AudioPostProcessorChain;
using qwen_tts_bridge::audio::AudioTerminalReason;
using qwen_tts_bridge::audio::PlayoutBuffer;
using qwen_tts_bridge::audio::TerminalFadeOptions;
using qwen_tts_bridge::audio::TerminalFadePostProcessor;
using qwen_tts_examples::PcmCapture;
using qwen_tts_examples::WavCapture;
using qwen_tts_bridge::playback::MockPlaybackFailureStage;
using qwen_tts_bridge::playback::PlaybackInterruptionDiagnostic;
using qwen_tts_bridge::playback::PlaybackMetrics;
using qwen_tts_bridge::playback::PlaybackCursorSnapshot;
using qwen_tts_bridge::playback::PlaybackSinkMode;
using qwen_tts_bridge::playback::WaveOutPlayer;
using qwen_tts_bridge::playback::WprPlaybackMarkers;
using qwen_tts_examples::playback::completion_has_natural_eos;

class ConsoleCodePageGuard final {
public:
    ConsoleCodePageGuard()
        : input_code_page_(GetConsoleCP()),
          output_code_page_(GetConsoleOutputCP()) {
        if (input_code_page_ != 0) {
            SetConsoleCP(CP_UTF8);
        }
        if (output_code_page_ != 0) {
            SetConsoleOutputCP(CP_UTF8);
        }
    }

    ~ConsoleCodePageGuard() {
        if (input_code_page_ != 0) {
            SetConsoleCP(input_code_page_);
        }
        if (output_code_page_ != 0) {
            SetConsoleOutputCP(output_code_page_);
        }
    }

    ConsoleCodePageGuard(const ConsoleCodePageGuard&) = delete;
    ConsoleCodePageGuard& operator=(const ConsoleCodePageGuard&) = delete;

private:
    UINT input_code_page_ = 0;
    UINT output_code_page_ = 0;
};


#ifdef QWEN_TTS_BRIDGE_HAS_SPEECH_ANIMATION
struct PlaybackAnimationContext {
    std::mutex mutex;
    std::uint64_t playback_epoch = 0;
    RequestId request_id = 0;
};

using PlaybackAnimationDiagnostic =
    qwen_tts_bridge::speech_animation::PlaybackAnimationRuntime::AdapterDiagnostic;

struct PlaybackAnimationDiagnosticQueue {
    std::mutex mutex;
    std::deque<PlaybackAnimationDiagnostic> records;
};

class PlaybackAnimationLoop final {
public:
    PlaybackAnimationLoop() = default;
    PlaybackAnimationLoop(const PlaybackAnimationLoop&) = delete;
    PlaybackAnimationLoop& operator=(const PlaybackAnimationLoop&) = delete;

    void start(std::function<void()> tick, std::uint32_t fps) {
        if (thread_.joinable()) {
            throw std::logic_error("playback animation loop already started");
        }
        stop_.store(false, std::memory_order_release);
        thread_ = std::thread([
            this,
            tick = std::move(tick),
            interval = std::chrono::duration_cast<std::chrono::steady_clock::duration>(
                std::chrono::duration<double>(1.0 / static_cast<double>(fps)))] {
            auto deadline = std::chrono::steady_clock::now();
            while (!stop_.load(std::memory_order_acquire)) {
                tick();
                deadline += interval;
                const auto now = std::chrono::steady_clock::now();
                if (deadline < now) {
                    deadline = now;
                }
                std::this_thread::sleep_until(deadline);
            }
        });
    }

    ~PlaybackAnimationLoop() {
        stop();
    }

    void stop() noexcept {
        stop_.store(true, std::memory_order_release);
        if (thread_.joinable()) {
            thread_.join();
        }
    }

private:
    std::atomic<bool> stop_{false};
    std::thread thread_;
};

std::string json_escape(const std::string& value) {
    std::string escaped;
    escaped.reserve(value.size());
    for (const char character : value) {
        if (character == '\\' || character == '"') {
            escaped.push_back('\\');
        }
        escaped.push_back(character);
    }
    return escaped;
}
#endif

struct OneShotCompletionState {
    std::mutex mutex;
    std::optional<TtsCompletion> metadata;
};

void fail_playback_request(
    WaveOutPlayer& player,
    ActiveRequestState& active_state,
    RequestId request_id,
    std::uint64_t playback_epoch,
    OneShotState* one_shot_state,
    std::string message) {
    QwenTtsClient* request_client = nullptr;
    {
        std::lock_guard<std::mutex> lock(active_state.mutex);
        if (active_state.active_request_id != request_id) {
            return;
        }
        request_client = active_state.active_client;
        active_state.active_request_id = 0;
        active_state.active_client = nullptr;
        active_state.processors.reset();
    }

    if (request_client != nullptr) {
        static_cast<void>(request_client->cancel(request_id));
    }
    try {
        static_cast<void>(player.reset_if_epoch(playback_epoch));
    }
    catch (const std::exception& reset_error) {
        message += "; playback reset failed: ";
        message += reset_error.what();
    }
    player.note_request_terminal(request_id, "failed");
    mark_one_shot_terminal(one_shot_state, false, "playback failed: " + message);
    if (one_shot_state == nullptr) {
        std::cerr << "request " << request_id << " playback failed: "
                  << message << '\n';
    }
}

void append_optional_wav_capture(
    WavCapture* wav_capture,
    const PcmChunk& chunk) noexcept {
    if (wav_capture == nullptr || wav_capture->has_failed()) {
        return;
    }
    try {
        wav_capture->append(chunk);
    }
    catch (const std::exception& error) {
        std::cerr << "WAV capture failed; continuing synthesis/playback: "
                  << error.what() << '\n';
    }
    catch (...) {
        std::cerr << "WAV capture failed; continuing synthesis/playback\n";
    }
}

std::shared_ptr<AudioPostProcessorChain> make_audio_processors(
    const ProgramOptions& options) {
    auto processors = std::make_shared<AudioPostProcessorChain>();
    if (options.terminal_fade_enabled) {
        processors->add(std::make_unique<TerminalFadePostProcessor>(
            options.terminal_fade));
    }
    return processors;
}

std::uint64_t cancel_active_request(
    QwenTtsClient& client,
    WaveOutPlayer& player,
    ActiveRequestState& state,
    std::uint32_t interruption_fade_ms
#ifdef QWEN_TTS_BRIDGE_HAS_SPEECH_ANIMATION
    , qwen_tts_bridge::speech_animation::PlaybackAnimationRuntime* animation_runtime = nullptr
    , PlaybackAnimationContext* animation_context = nullptr
#endif
    ) {
    RequestId request_id = 0;
    QwenTtsClient* active_client = nullptr;
    std::shared_ptr<AudioPostProcessorChain> processors;
    {
        std::lock_guard<std::mutex> lock(state.mutex);
        request_id = state.active_request_id;
        active_client = state.active_client;
        processors = std::move(state.processors);
        state.active_request_id = 0;
        state.active_client = nullptr;
    }
    if (request_id != 0) {
        (active_client != nullptr ? *active_client : client).cancel(request_id);
    }
    // Producer-side processors must not release their newest buffered samples
    // here: those samples may already be far ahead of the physical sink.
    // The sink derives its interruption tail from the actual playout cursor.
    if (processors != nullptr) {
        processors->reset();
    }
    auto interruption = player.interrupt_with_fade(interruption_fade_ms, request_id);
    const std::uint64_t playback_epoch = interruption.first;
    if (interruption.second.has_value()) {
        player.enqueue(playback_epoch, interruption.second.value());
    }
#ifdef QWEN_TTS_BRIDGE_HAS_SPEECH_ANIMATION
    if (animation_runtime != nullptr) {
        animation_runtime->invalidate(playback_epoch);
        if (animation_context != nullptr) {
            std::lock_guard<std::mutex> lock(animation_context->mutex);
            animation_context->playback_epoch = playback_epoch;
            animation_context->request_id = 0;
        }
    }
#endif
    return playback_epoch;
}

PreparedTtsRequest prepare_request(
    QwenTtsClient& preparation_client,
    const ProgramOptions& options,
    const std::string& text) {
    PreparedTtsRequest prepared_request;
    prepared_request.request.text = text;
    prepared_request.request.language = options.language;
    prepared_request.request.speaker = options.speaker;
    prepared_request.request.instruction = options.instruction;
    prepared_request.request.voice_id = options.voice_id;
    prepared_request.request.reference_audio_path = options.reference_audio_path;
    prepared_request.request.reference_text = options.reference_text;
    prepared_request.request.x_vector_only = options.x_vector_only;
    prepared_request.request.sampling.temperature = options.temperature;
    prepared_request.request.sampling.top_k = options.top_k;
    prepared_request.request.sampling.top_p = options.top_p;
    prepared_request.request.sampling.repetition_penalty = options.repetition_penalty;
    prepared_request.request.sampling.do_sample = options.do_sample;
    if (options.seed.has_value()) {
        prepared_request.request.has_seed = true;
        prepared_request.request.seed = options.seed.value();
    }
    prepared_request.request.output = requested_audio_format(options);

    TtsError error;
    if (!preparation_client.prepare_text(
            prepared_request.request,
            prepared_request.text,
            error)) {
        throw std::runtime_error(
            error.category + "/" + error.code + ": " + error.message);
    }
    std::cout << "prepared text: utf8_bytes=" << prepared_request.text.utf8_bytes
              << ", non_space_utf8_bytes="
              << prepared_request.text.non_space_utf8_bytes
              << ", modified="
              << (prepared_request.text.was_modified ? "true" : "false")
              << '\n';
    return prepared_request;
}

RequestId submit_request(
    QwenTtsClient& client,
    WaveOutPlayer& player,
    ActiveRequestState& active_state,
    const ProgramOptions& options,
    PreparedTtsRequest prepared_request,
    OneShotState* one_shot_state = nullptr,
    OneShotCompletionState* completion_state = nullptr,
    PcmCapture* pcm_capture = nullptr,
    WavCapture* wav_capture = nullptr,
    std::optional<std::uint64_t> playback_epoch_override = std::nullopt
#ifdef QWEN_TTS_BRIDGE_HAS_SPEECH_ANIMATION
    , qwen_tts_bridge::speech_animation::PlaybackAnimationRuntime* animation_runtime = nullptr
    , PlaybackAnimationContext* animation_context = nullptr
#endif
    ) {
    const std::uint64_t playback_epoch = playback_epoch_override.value_or(
        cancel_active_request(
            client,
            player,
            active_state,
            options.terminal_fade_enabled ? options.terminal_fade.fade_ms : 0
#ifdef QWEN_TTS_BRIDGE_HAS_SPEECH_ANIMATION
            , animation_runtime, animation_context
#endif
        ));

    TtsRequest request = std::move(prepared_request.request);
    std::uint64_t animation_generation = 0;
    auto processors = make_audio_processors(options);
    {
        std::lock_guard<std::mutex> lock(active_state.mutex);
        if (active_state.next_request_id == 0) {
            throw std::runtime_error(
                "request ID space exhausted; restart the worker session");
        }
        request.id = active_state.next_request_id;
        if (request.id == std::numeric_limits<RequestId>::max()) {
            active_state.next_request_id = 0;
        }
        else {
            ++active_state.next_request_id;
        }
        active_state.active_request_id = request.id;
        active_state.active_client = &client;
        active_state.processors = processors;
    }

    const RequestId request_id = request.id;
    player.note_request_started(request_id);
#ifdef QWEN_TTS_BRIDGE_HAS_SPEECH_ANIMATION
    if (animation_runtime != nullptr) {
        if (animation_context != nullptr) {
            std::lock_guard<std::mutex> lock(animation_context->mutex);
            animation_context->playback_epoch = playback_epoch;
            animation_context->request_id = request_id;
        }
        animation_generation = animation_runtime->begin(
            playback_epoch,
            request_id,
            options.sample_rate);
    }
#endif
    TtsCallbacks callbacks;
    const bool require_natural_eos = options.require_natural_eos;
    callbacks.on_audio = [&player, &active_state, processors, playback_epoch, request_id,
        one_shot_state, pcm_capture, wav_capture
#ifdef QWEN_TTS_BRIDGE_HAS_SPEECH_ANIMATION
        , animation_runtime, animation_generation
#endif
        ](const PcmChunk& chunk) {
        if (!is_active_request(active_state, request_id)) {
            return;
        }
        try {
            if (pcm_capture != nullptr) {
                pcm_capture->append(chunk);
            }
            for (const PcmChunk& processed : processors->process(chunk)) {
                if (wav_capture != nullptr) {
                    append_optional_wav_capture(wav_capture, processed);
                }
                player.enqueue(playback_epoch, processed);
#ifdef QWEN_TTS_BRIDGE_HAS_SPEECH_ANIMATION
                if (animation_runtime != nullptr) {
                    animation_runtime->push_audio(
                        playback_epoch,
                        animation_generation,
                        processed);
                }
#endif
            }
        }
        catch (const std::exception& exc) {
            fail_playback_request(
                player,
                active_state,
                request_id,
                playback_epoch,
                one_shot_state,
                exc.what());
        }
    };
    callbacks.on_completed = [&player, &active_state, processors, playback_epoch,
        one_shot_state, completion_state, require_natural_eos, request_id, wav_capture
#ifdef QWEN_TTS_BRIDGE_HAS_SPEECH_ANIMATION
        , animation_runtime, animation_generation
#endif
        ] {
        if (!is_active_request(active_state, request_id)) {
            return;
        }
        if (one_shot_state != nullptr && require_natural_eos) {
            std::optional<TtsCompletion> completion;
            if (completion_state != nullptr) {
                std::lock_guard<std::mutex> lock(completion_state->mutex);
                completion = completion_state->metadata;
            }
            if (!completion_has_natural_eos(completion)) {
                fail_playback_request(
                    player,
                    active_state,
                    request_id,
                    playback_epoch,
                    one_shot_state,
                    completion.has_value()
                        ? "completion metadata did not confirm natural EOS"
                        : "completion metadata was missing");
                return;
            }
        }
        try {
            for (const PcmChunk& processed :
                 processors->finish(AudioTerminalReason::Completed)) {
                if (wav_capture != nullptr) {
                    append_optional_wav_capture(wav_capture, processed);
                }
                player.enqueue(playback_epoch, processed);
#ifdef QWEN_TTS_BRIDGE_HAS_SPEECH_ANIMATION
                if (animation_runtime != nullptr) {
                    animation_runtime->push_audio(
                        playback_epoch,
                        animation_generation,
                        processed);
                }
#endif
            }
        }
        catch (const std::exception& exc) {
            fail_playback_request(
                player,
                active_state,
                request_id,
                playback_epoch,
                one_shot_state,
                exc.what());
            return;
        }
        if (!complete_active_request(active_state, request_id)) {
            return;
        }
        player.note_request_terminal(request_id, "completed");
        if (one_shot_state != nullptr) {
            mark_one_shot_terminal(one_shot_state, true);
        }
        else {
            std::cout << "completed request " << request_id << '\n';
        }
    };
    callbacks.on_completion_metadata = [completion_state](const TtsCompletion& completion) {
        if (completion_state == nullptr) {
            return;
        }
        std::lock_guard<std::mutex> lock(completion_state->mutex);
        completion_state->metadata = completion;
    };
    const std::uint32_t interruption_fade_ms =
        options.terminal_fade_enabled ? options.terminal_fade.fade_ms : 0;
    callbacks.on_cancelled = [
        &player,
        &active_state,
        processors,
        playback_epoch,
        one_shot_state,
        request_id,
        interruption_fade_ms] {
        if (clear_active_request(active_state, request_id)) {
            try {
                processors->reset();
                const auto interruption = player.interrupt_with_fade_if_epoch(
                    playback_epoch,
                    interruption_fade_ms,
                    request_id);
                if (interruption.has_value() && interruption->second.has_value()) {
                    player.enqueue(interruption->first, interruption->second.value());
                }
            }
            catch (const std::exception& exc) {
                std::cerr << "audio post-processing error: " << exc.what() << '\n';
            }
        }
        player.note_request_terminal(request_id, "cancelled");
        mark_one_shot_terminal(one_shot_state, false, "request cancelled");
    };
    callbacks.on_error = [
        &player,
        &active_state,
        processors,
        playback_epoch,
        one_shot_state,
        request_id](const TtsError& error) {
        if (clear_active_request(active_state, request_id)) {
            try {
                processors->reset();
                static_cast<void>(player.reset_if_epoch(playback_epoch));
            }
            catch (const std::exception& exc) {
                std::cerr << "audio post-processing error: " << exc.what() << '\n';
            }
        }
        player.note_request_terminal(request_id, "failed");
        mark_one_shot_terminal(
            one_shot_state,
            false,
            error.category + "/" + error.code + ": " + error.message);
        if (one_shot_state == nullptr) {
            std::cerr << "request " << request_id << " failed: " << error.category
                      << '/' << error.code << ": " << error.message << '\n';
        }
    };

#ifdef QWEN_TTS_BRIDGE_HAS_SPEECH_ANIMATION
    if (animation_runtime != nullptr) {
        callbacks = animation_runtime->make_callbacks(std::move(callbacks), false);
    }
#endif

    prepared_request.request = std::move(request);
    if (client.synthesize_async(
            std::move(prepared_request), std::move(callbacks)) != request_id) {
        clear_active_request(active_state, request_id);
        throw std::runtime_error("failed to enqueue synthesis request");
    }
    return request_id;
}

QwenTtsClient& client_for_text(
    const ProgramOptions& options,
    const PreparedText& prepared_text,
    QwenTtsClient& fast_client,
    QwenTtsClient* safe_client) {
    if (!options.auto_profile) {
        return fast_client;
    }
    if (safe_client == nullptr) {
        throw std::runtime_error("automatic profile routing has no safe worker");
    }
    const std::size_t estimated_bytes = prepared_text.non_space_utf8_bytes;
    const bool use_fast = estimated_bytes <= options.auto_fast_max_bytes;
    std::cout << "auto profile: " << (use_fast ? "cmp50hx-fastest" : "cmp50hx-safe")
              << " (non-space UTF-8 bytes=" << estimated_bytes << ")\n";
    return use_fast ? fast_client : *safe_client;
}

} // namespace

int wmain(int argc, wchar_t** argv) {
    try {
        ConsoleCodePageGuard console_code_page_guard;
        ProgramOptions options = parse_options(argc, argv);
        validate_options(options);
        if (options.help) {
            print_usage(std::cout, utf8_from_wide(argv[0]));
            return 0;
        }
        if (options.self_test_playback_lifecycle) {
            return run_playback_lifecycle_self_test();
        }

        QwenTtsClientOptions client_options;
        client_options.session.startup_timeout = options.startup_timeout;

        QwenTtsClient client;
        if (!client.start(make_transport_options(options), client_options)) {
            throw std::runtime_error("failed to start Qwen TTS worker");
        }
        std::unique_ptr<QwenTtsClient> safe_client;
        if (options.auto_profile) {
            safe_client = std::make_unique<QwenTtsClient>();
            if (!safe_client->start(make_transport_options(options, true), client_options)) {
                client.stop();
                throw std::runtime_error("failed to start automatic safe Qwen TTS worker");
            }
        }
        ReadyMessage ready;
        if (!client.ready_message(ready)) {
            if (safe_client != nullptr) {
                safe_client->stop();
            }
            client.stop();
            throw std::runtime_error("worker did not expose a ready payload");
        }
        if (safe_client != nullptr) {
            ReadyMessage safe_ready;
            if (!safe_client->ready_message(safe_ready)) {
                client.stop();
                safe_client->stop();
                throw std::runtime_error("safe worker did not expose a ready payload");
            }
            if (safe_ready.capabilities.voice_clone != ready.capabilities.voice_clone ||
                safe_ready.capabilities.voice_profiles != ready.capabilities.voice_profiles) {
                client.stop();
                safe_client->stop();
                throw std::runtime_error("automatic profile workers expose incompatible capabilities");
            }
        }
        options.sampling_overrides_supported = ready.capabilities.sampling_overrides;
        options.deterministic_seed_supported = ready.capabilities.deterministic_seed;
        options.voice_clone_supported = ready.capabilities.voice_clone;
        options.voice_profiles_supported = ready.capabilities.voice_profiles;
        options.voice_ids = ready.voice_ids;
        if (!options.reference_audio_path.empty() && !options.voice_clone_supported) {
            client.stop();
            throw std::runtime_error(
                "the active worker does not advertise voice clone support; "
                "launch a Qwen Base model with --reference-audio");
        }
        if (!options.voice_id.empty() && !options.voice_profiles_supported &&
            !uses_mock_worker(options)) {
            client.stop();
            throw std::runtime_error(
                "the active worker has no registered voice-profile registry; "
                "launch it with --voice-registry-path");
        }
        if (has_sampling_overrides(options) && !options.sampling_overrides_supported) {
            client.stop();
            throw std::runtime_error(
                "sampling overrides are disabled by the active worker profile; "
                "use the StyleExperiment launcher profile");
        }
        if (options.seed.has_value() && !options.deterministic_seed_supported) {
            client.stop();
            throw std::runtime_error(
                "the active worker profile does not guarantee deterministic explicit seeds");
        }

        std::unique_ptr<WprPlaybackMarkers> etw_playback_markers;
        if (options.etw_playback_markers) {
            etw_playback_markers = std::make_unique<WprPlaybackMarkers>();
        }
        std::unique_ptr<PlaybackMetrics> playback_metrics;
        if (!options.playback_metrics_file.empty()) {
            playback_metrics = std::make_unique<PlaybackMetrics>(etw_playback_markers.get());
        }
        const PlaybackSinkMode playback_sink_mode = !options.playback_enabled
            ? PlaybackSinkMode::Disabled
            : (options.use_mock_playback_sink
                    ? PlaybackSinkMode::Mock
                    : PlaybackSinkMode::WaveOut);
        std::unique_ptr<PcmCapture> pcm_capture;
        if (!options.pcm_capture_file.empty()) {
            pcm_capture = std::make_unique<PcmCapture>(options.pcm_capture_file);
        }
        std::unique_ptr<WavCapture> wav_capture;
        if (!options.wav_capture_file.empty()) {
            std::function<void()> before_write_hook;
            if (options.mock_wav_capture_failure) {
                before_write_hook = [] {
                    throw std::runtime_error("injected WAV capture writer failure");
                };
            }
            wav_capture = std::make_unique<WavCapture>(
                options.wav_capture_file,
                std::move(before_write_hook));
        }
        std::optional<MockPlaybackFailureStage> mock_failure_stage;
        if (options.mock_playback_fail_stage.has_value()) {
            mock_failure_stage = options.mock_playback_fail_stage.value() == "prepare"
                ? MockPlaybackFailureStage::Prepare
                : MockPlaybackFailureStage::Write;
        }
        WaveOutPlayer player(
            playback_sink_mode,
            playback_metrics.get(),
            options.playback_prebuffer_chunks,
            options.mock_playback_fail_after_submissions,
            mock_failure_stage);
        ActiveRequestState active_state;

#ifdef QWEN_TTS_BRIDGE_HAS_SPEECH_ANIMATION
        std::shared_ptr<PlaybackAnimationContext> animation_context;
        std::shared_ptr<std::mutex> animation_receipt_mutex;
        std::shared_ptr<std::ofstream> animation_receipt_output;
        std::shared_ptr<PlaybackAnimationDiagnosticQueue> animation_diagnostics;
        std::unique_ptr<qwen_tts_bridge::speech_animation::PlaybackAnimationRuntime>
            animation_runtime;
        PlaybackAnimationLoop animation_loop;
        if (!options.playback_animation_receipts_file.empty()) {
            const auto receipt_path = std::filesystem::u8path(
                options.playback_animation_receipts_file);
            if (std::filesystem::exists(receipt_path)) {
                throw std::runtime_error(
                    "refusing to overwrite existing playback animation receipts file: " +
                    options.playback_animation_receipts_file);
            }
            animation_receipt_output = std::make_shared<std::ofstream>(
                receipt_path,
                std::ios::binary | std::ios::trunc);
            if (!*animation_receipt_output) {
                throw std::runtime_error(
                    "failed to open playback animation receipts file: " +
                    options.playback_animation_receipts_file);
            }
            animation_context = std::make_shared<PlaybackAnimationContext>();
            {
                std::lock_guard<std::mutex> lock(animation_context->mutex);
                // The animation loop can tick before the first request is
                // submitted. Start it on the player's current epoch so an
                // early diagnostic/selection cannot publish epoch zero.
                animation_context->playback_epoch = player.playback_epoch();
            }
            animation_receipt_mutex = std::make_shared<std::mutex>();
            animation_diagnostics =
                std::make_shared<PlaybackAnimationDiagnosticQueue>();
            animation_runtime = std::make_unique<
                qwen_tts_bridge::speech_animation::PlaybackAnimationRuntime>(
                [&player, animation_context] {
                    std::lock_guard<std::mutex> lock(animation_context->mutex);
                    const auto snapshot = player.playback_cursor_snapshot(
                        animation_context->playback_epoch,
                        animation_context->request_id);
                    return ::speech_animation::integration::PlaybackCursorSnapshot{
                        snapshot.playback_epoch,
                        snapshot.request_id,
                        snapshot.utterance_sample,
                        snapshot.sample_rate,
                        snapshot.position_available};
                },
                [animation_receipt_output, animation_receipt_mutex](
                    const auto& selection) {
                    std::lock_guard<std::mutex> lock(*animation_receipt_mutex);
                    *animation_receipt_output << selection.to_json() << '\n';
                    animation_receipt_output->flush();
                },
                [animation_diagnostics](const auto& diagnostic) {
                    std::lock_guard<std::mutex> lock(animation_diagnostics->mutex);
                    animation_diagnostics->records.push_back(diagnostic);
                });
            animation_runtime->initialize_epoch(player.playback_epoch());
            animation_loop.start(
                [&animation_runtime,
                 animation_diagnostics,
                 animation_receipt_output,
                 animation_receipt_mutex] {
                    static_cast<void>(animation_runtime->tick());
                    std::deque<PlaybackAnimationDiagnostic> diagnostics;
                    {
                        std::lock_guard<std::mutex> lock(animation_diagnostics->mutex);
                        diagnostics.swap(animation_diagnostics->records);
                    }
                    if (!diagnostics.empty()) {
                        std::lock_guard<std::mutex> lock(*animation_receipt_mutex);
                        for (const auto& diagnostic : diagnostics) {
                            *animation_receipt_output
                                << "{\"type\":\"diagnostic\",\"request_id\":"
                                << diagnostic.request_id
                                << ",\"code\":\""
                                << json_escape(diagnostic.code)
                                << "\",\"message\":\""
                                << json_escape(diagnostic.message) << "\"}\n";
                        }
                        animation_receipt_output->flush();
                    }
                },
                options.playback_animation_fps);
        }
#endif

        if (!options.text.empty()) {
            OneShotState state;
            OneShotCompletionState completion_state;
            if (playback_metrics != nullptr) {
                playback_metrics->begin_request();
            }
            auto prepared_request = prepare_request(client, options, options.text);
            submit_request(
                client_for_text(
                    options,
                    prepared_request.text,
                    client,
                    safe_client.get()),
                player,
                active_state,
                options,
                std::move(prepared_request),
                &state,
                &completion_state,
                pcm_capture.get(),
                wav_capture.get(),
                std::nullopt
#ifdef QWEN_TTS_BRIDGE_HAS_SPEECH_ANIMATION
                , animation_runtime.get(), animation_context.get()
#endif
            );
            if (!wait_for_one_shot(state, options.request_timeout)) {
                cancel_active_request(
                    client,
                    player,
                    active_state,
                    options.terminal_fade_enabled ? options.terminal_fade.fade_ms : 0
#ifdef QWEN_TTS_BRIDGE_HAS_SPEECH_ANIMATION
                    , animation_runtime.get(), animation_context.get()
#endif
                );
                if (safe_client != nullptr) {
                    safe_client->stop();
                }
                client.stop();
                throw std::runtime_error("one-shot synthesis timed out");
            }
            if (!state.success) {
                if (safe_client != nullptr) {
                    safe_client->stop();
                }
                client.stop();
                throw std::runtime_error(state.message.empty() ? "one-shot synthesis failed" : state.message);
            }
            player.wait_until_idle(options.request_timeout);
            if (pcm_capture != nullptr) {
                pcm_capture->finalize();
            }
            if (playback_metrics != nullptr) {
                playback_metrics->mark_playback_completed();
                playback_metrics->write_json_file(options.playback_metrics_file);
            }
            if (wav_capture != nullptr) {
                wav_capture->finalize();
            }
            client.stop();
            if (safe_client != nullptr) {
                safe_client->stop();
            }
            if (!options.playback_interruption_diagnostics_file.empty()) {
                player.write_interruption_diagnostics_file(
                    options.playback_interruption_diagnostics_file);
            }
            return 0;
        }

        print_usage(std::cout, utf8_from_wide(argv[0]));
        print_interactive_status(options);
        for (std::string line; std::cout << "> " && read_interactive_line(line);) {
            if (line.empty()) {
                continue;
            }
            if (line == "/quit" || line == "/exit") {
                break;
            }
            if (line == "/help") {
                print_usage(std::cout, utf8_from_wide(argv[0]));
                continue;
            }
            if (line == "/cancel") {
                cancel_active_request(
                    client,
                    player,
                    active_state,
                    options.terminal_fade_enabled ? options.terminal_fade.fade_ms : 0
#ifdef QWEN_TTS_BRIDGE_HAS_SPEECH_ANIMATION
                    , animation_runtime.get(), animation_context.get()
#endif
                );
                std::cout << "cancelled active request\n";
                continue;
            }
            if (line.front() == '/') {
                try {
                    if (!apply_interactive_command(options, line)) {
                        std::cerr << "unknown command; use /help\n";
                    }
                }
                catch (const std::exception& exc) {
                    std::cerr << "command error: " << exc.what() << '\n';
                }
                continue;
            }
            const std::uint64_t playback_epoch = cancel_active_request(
                client,
                player,
                active_state,
                options.terminal_fade_enabled ? options.terminal_fade.fade_ms : 0
#ifdef QWEN_TTS_BRIDGE_HAS_SPEECH_ANIMATION
                , animation_runtime.get(), animation_context.get()
#endif
            );
            PreparedTtsRequest prepared_request;
            try {
                prepared_request = prepare_request(client, options, line);
            }
            catch (const std::exception& exc) {
                std::cerr << "text preparation failed: " << exc.what() << '\n';
                continue;
            }
            submit_request(
                client_for_text(
                    options,
                    prepared_request.text,
                    client,
                    safe_client.get()),
                player,
                active_state,
                options,
                std::move(prepared_request),
                nullptr,
                nullptr,
                nullptr,
                nullptr,
                playback_epoch
#ifdef QWEN_TTS_BRIDGE_HAS_SPEECH_ANIMATION
                , animation_runtime.get(), animation_context.get()
#endif
            );
        }

        cancel_active_request(
            client,
            player,
            active_state,
            options.terminal_fade_enabled ? options.terminal_fade.fade_ms : 0
#ifdef QWEN_TTS_BRIDGE_HAS_SPEECH_ANIMATION
            , animation_runtime.get(), animation_context.get()
#endif
        );
        client.stop();
        if (safe_client != nullptr) {
            safe_client->stop();
        }
        if (!options.playback_interruption_diagnostics_file.empty()) {
            player.write_interruption_diagnostics_file(
                options.playback_interruption_diagnostics_file);
        }
        return 0;
    }
    catch (const std::exception& exc) {
        std::cerr << "qwen_tts_play: " << exc.what() << '\n';
        std::cerr << "Run with --help for usage.\n";
        return 1;
    }
}
