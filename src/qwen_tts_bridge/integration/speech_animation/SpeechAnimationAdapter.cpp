#include "SpeechAnimationAdapter.hpp"

#include <algorithm>
#include <atomic>
#include <limits>
#include <stdexcept>
#include <string>
#include <utility>

namespace qwen_tts_bridge::speech_animation {
namespace {

using IntegrationChunk = ::speech_animation::integration::SpeechTimingChunk;

bool convert_pcm(
    const PcmChunk& source,
    IntegrationChunk& target,
    std::string& diagnostic) {
    if (source.format.sample_format != "s16le" ||
        source.format.channels != 1) {
        diagnostic =
            "speech-animation adapter accepts mono s16le PCM only";
        return false;
    }
    if (source.format.sample_rate == 0 || source.sample_count == 0 ||
        source.sample_count > std::numeric_limits<std::size_t>::max() / 2u ||
        source.bytes.size() != static_cast<std::size_t>(source.sample_count) * 2u) {
        diagnostic = "bridge PCM metadata does not match its s16le payload";
        return false;
    }

    target.request_id = source.request_id;
    target.first_sample = source.first_sample;
    target.sample_rate = source.format.sample_rate;
    target.sample_count = source.sample_count;
    target.pcm.resize(source.sample_count);
    for (std::size_t index = 0; index < target.pcm.size(); ++index) {
        const auto offset = index * sizeof(std::int16_t);
        const auto bits = static_cast<std::uint16_t>(source.bytes[offset]) |
            (static_cast<std::uint16_t>(source.bytes[offset + 1]) << 8u);
        const auto sample = static_cast<std::int16_t>(bits);
        target.pcm[index] = std::max(
            -1.0F,
            std::min(1.0F, static_cast<float>(sample) / 32768.0F));
    }
    return true;
}

} // namespace

struct SpeechAnimationAdapter::State {
    std::shared_ptr<Pipeline> pipeline;
    ReceiptHandler on_receipt;
    AdapterDiagnosticHandler on_diagnostic;
    std::atomic<bool> animation_degraded{false};
};

SpeechAnimationAdapter::SpeechAnimationAdapter(
    std::shared_ptr<Pipeline> pipeline,
    ReceiptHandler on_receipt,
    AdapterDiagnosticHandler on_diagnostic)
    : state_(std::make_shared<State>()) {
    if (!pipeline) {
        throw std::invalid_argument("speech-animation pipeline is null");
    }
    state_->pipeline = std::move(pipeline);
    state_->on_receipt = std::move(on_receipt);
    state_->on_diagnostic = std::move(on_diagnostic);
}

SpeechAnimationAdapter::QueuePushResult SpeechAnimationAdapter::begin(
    RequestId request_id,
    std::uint64_t first_sample,
    std::uint32_t sample_rate) {
    return state_->pipeline->begin(request_id, first_sample, sample_rate);
}

TtsCallbacks SpeechAnimationAdapter::make_callbacks(
    TtsCallbacks downstream) const {
    auto state = state_;
    auto callbacks = std::make_shared<TtsCallbacks>(std::move(downstream));
    TtsCallbacks wrapped;
    wrapped.on_text_prepared = callbacks->on_text_prepared;
    wrapped.on_timing = callbacks->on_timing;
    wrapped.on_completion_metadata = callbacks->on_completion_metadata;
    wrapped.on_audio = [state, callbacks](const PcmChunk& chunk) {
        if (callbacks->on_audio) {
            callbacks->on_audio(chunk);
        }
        if (state->animation_degraded.load(std::memory_order_acquire)) {
            return;
        }

        IntegrationChunk input;
        std::string diagnostic;
        if (!convert_pcm(chunk, input, diagnostic)) {
            if (!state->animation_degraded.exchange(
                    true,
                    std::memory_order_acq_rel)) {
                state->pipeline->cancel();
                if (state->on_diagnostic) {
                    state->on_diagnostic(AdapterDiagnostic{
                        chunk.request_id,
                        "unsupported_pcm",
                        std::move(diagnostic)});
                }
            }
            return;
        }

        const auto result = state->pipeline->push(std::move(input));
        if (result == QueuePushResult::Accepted) {
            return;
        }

        if (!state->animation_degraded.exchange(
                true,
                std::memory_order_acq_rel)) {
            state->pipeline->cancel();
            const char* code = result == QueuePushResult::Full
                ? "speech_animation_queue_full"
                : "speech_animation_input_rejected";
            if (state->on_diagnostic) {
                state->on_diagnostic(AdapterDiagnostic{
                    chunk.request_id,
                    code,
                    "speech-animation rejected a bridge PCM chunk"});
            }
        }
    };
    wrapped.on_completed = [state, callbacks]() {
        if (!state->animation_degraded.load(std::memory_order_acquire)) {
            state->pipeline->complete();
        }
        if (callbacks->on_completed) {
            callbacks->on_completed();
        }
    };
    wrapped.on_cancelled = [state, callbacks]() {
        if (!state->animation_degraded.load(std::memory_order_acquire)) {
            state->pipeline->cancel();
        }
        if (callbacks->on_cancelled) {
            callbacks->on_cancelled();
        }
    };
    wrapped.on_error = [state, callbacks](const TtsError& error) {
        if (!state->animation_degraded.load(std::memory_order_acquire)) {
            state->pipeline->cancel();
        }
        if (callbacks->on_error) {
            callbacks->on_error(error);
        }
    };
    return wrapped;
}

std::vector<SpeechAnimationAdapter::Receipt>
SpeechAnimationAdapter::process_available() const {
    auto receipts = state_->pipeline->process_available();
    if (state_->on_receipt) {
        for (const Receipt& receipt : receipts) {
            state_->on_receipt(receipt);
        }
    }
    return receipts;
}

bool SpeechAnimationAdapter::terminal() const noexcept {
    return state_->pipeline->terminal();
}

} // namespace qwen_tts_bridge::speech_animation
