#pragma once

/// \file playback_receipt.hpp
/// \brief Bounded, sample-addressed playback timeline probe.

#include "playback_cursor.hpp"

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

#include "../client/client_types.hpp"

namespace qwen_tts_bridge::playback {

using qwen_tts_bridge::PcmChunk;
using qwen_tts_bridge::RequestId;

/// \enum PlaybackReceiptStatus
/// \brief Result of publishing one timeline item to a receipt probe.
enum class PlaybackReceiptStatus {
    Accepted,
    StaleEpoch,
    StaleRequest,
    InvalidRange,
    InvalidSampleRate,
    SampleRateMismatch,
    DiscontinuousPcm,
    DiscontinuousCue,
    CueHistoryFull,
    AlreadyTerminal,
};

/// \brief Returns a stable machine-readable name for a probe status.
const char* playback_receipt_status_name(PlaybackReceiptStatus status) noexcept;

/// \struct PlaybackCue
/// \brief Sample-addressed synthetic or downstream-produced animation cue.
///
/// The bridge deliberately does not assign a viseme or phoneme meaning to the
/// cue. `mouth_open` and `activity` are opaque scalar evidence useful for a
/// receipt or a test consumer until speech-animation supplies its own cue
/// type.
struct PlaybackCue {
    std::uint64_t playback_epoch = 0;
    RequestId request_id = 0;
    std::uint64_t first_sample = 0;
    std::uint32_t sample_count = 0;
    float mouth_open = 0.0F;
    float activity = 0.0F;
};

/// \struct PlaybackCueSelection
/// \brief Result of selecting the cue at a measured playback cursor.
struct PlaybackCueSelection {
    enum class Status {
        Selected,
        CursorUnavailable,
        StaleEpoch,
        StaleRequest,
        SampleRateMismatch,
        OutsideCueTimeline,
    };

    Status status = Status::OutsideCueTimeline;
    std::uint64_t playback_epoch = 0;
    RequestId request_id = 0;
    std::uint64_t cursor_sample = 0;
    PlaybackCue cue;

    /// \brief Serializes the selection without requiring a JSON dependency.
    std::string to_json() const;
};

/// \struct PlaybackReceipt
/// \brief Machine-readable summary of one bounded playback timeline.
struct PlaybackReceipt {
    std::uint64_t playback_epoch = 0;
    RequestId request_id = 0;
    std::size_t pcm_chunk_count = 0;
    std::uint64_t pcm_sample_count = 0;
    std::size_t cue_count = 0;
    std::uint64_t cue_sample_count = 0;
    std::uint32_t sample_rate = 0;
    bool pcm_contiguous = true;
    bool cue_contiguous = true;
    bool cue_history_overflow = false;
    bool terminal = false;

    /// \brief Serializes the summary without requiring a JSON dependency.
    std::string to_json() const;
};

/// \brief Records and consumes sample-addressed playback evidence.
///
/// This class is intentionally neutral: it does not analyze PCM, infer
/// phonemes, or depend on speech-animation. It is suitable for a downstream
/// probe or application-owned consumer. Publishing and selection are local
/// operations; no callback is invoked by the probe.
/// The probe is intended for one owning consumer thread and is not internally
/// synchronized.
class PlaybackReceiptProbe final {
public:
    explicit PlaybackReceiptProbe(std::size_t max_cues = 4096);

    /// Starts a new request timeline and discards all prior ranges.
    void begin(std::uint64_t playback_epoch, RequestId request_id);

    /// Invalidates the current request while retaining the replacement epoch.
    void invalidate(std::uint64_t playback_epoch);

    /// Publishes one PCM callback range. The callback's request id must match
    /// the active request and its first sample must continue the PCM timeline.
    PlaybackReceiptStatus observe_pcm(
        std::uint64_t playback_epoch,
        const PcmChunk& chunk);

    /// Publishes one bounded synthetic/downstream cue range.
    ///
    /// Once `max_cues` is reached the probe fails closed and rejects all later
    /// cues for this timeline; it does not silently turn into a rolling buffer.
    PlaybackReceiptStatus append_cue(const PlaybackCue& cue);

    /// Selects the cue containing the measured cursor position.
    PlaybackCueSelection select(const PlaybackCursorSnapshot& snapshot) const;

    /// Marks the matching active request terminal without changing its sample clock.
    /// Returns false for a stale identity or an already terminal request.
    bool mark_terminal(
        std::uint64_t playback_epoch,
        RequestId request_id) noexcept;

    [[nodiscard]] PlaybackReceipt receipt() const noexcept;

private:
    static bool range_end(
        std::uint64_t first_sample,
        std::uint32_t sample_count,
        std::uint64_t& end_sample) noexcept;

    std::size_t max_cues_;
    std::uint64_t playback_epoch_ = 0;
    RequestId request_id_ = 0;
    std::uint64_t next_pcm_sample_ = 0;
    std::uint64_t next_cue_sample_ = 0;
    bool pcm_started_ = false;
    bool cue_started_ = false;
    PlaybackReceipt receipt_;
    std::vector<PlaybackCue> cues_;
};

} // namespace qwen_tts_bridge::playback
