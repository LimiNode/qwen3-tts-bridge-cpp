#include <qwen_tts_bridge/playback.hpp>

#include <cmath>
#include <iomanip>
#include <limits>
#include <locale>
#include <sstream>
#include <stdexcept>

namespace qwen_tts_bridge::playback {

namespace {

const char* selection_status_name(PlaybackCueSelection::Status status) noexcept {
    switch (status) {
    case PlaybackCueSelection::Status::Selected:
        return "selected";
    case PlaybackCueSelection::Status::CursorUnavailable:
        return "cursor_unavailable";
    case PlaybackCueSelection::Status::StaleEpoch:
        return "stale_epoch";
    case PlaybackCueSelection::Status::StaleRequest:
        return "stale_request";
    case PlaybackCueSelection::Status::SampleRateMismatch:
        return "sample_rate_mismatch";
    case PlaybackCueSelection::Status::OutsideCueTimeline:
        return "outside_cue_timeline";
    }
    return "unknown";
}

} // namespace

const char* playback_receipt_status_name(PlaybackReceiptStatus status) noexcept {
    switch (status) {
    case PlaybackReceiptStatus::Accepted:
        return "accepted";
    case PlaybackReceiptStatus::StaleEpoch:
        return "stale_epoch";
    case PlaybackReceiptStatus::StaleRequest:
        return "stale_request";
    case PlaybackReceiptStatus::InvalidRange:
        return "invalid_range";
    case PlaybackReceiptStatus::InvalidSampleRate:
        return "invalid_sample_rate";
    case PlaybackReceiptStatus::SampleRateMismatch:
        return "sample_rate_mismatch";
    case PlaybackReceiptStatus::DiscontinuousPcm:
        return "discontinuous_pcm";
    case PlaybackReceiptStatus::DiscontinuousCue:
        return "discontinuous_cue";
    case PlaybackReceiptStatus::CueHistoryFull:
        return "cue_history_full";
    case PlaybackReceiptStatus::AlreadyTerminal:
        return "already_terminal";
    }
    return "unknown";
}

std::string PlaybackCueSelection::to_json() const {
    std::ostringstream output;
    output.imbue(std::locale::classic());
    output << std::setprecision(std::numeric_limits<float>::max_digits10);
    output << "{\"status\":\"" << selection_status_name(status)
           << "\",\"playback_epoch\":" << playback_epoch
           << ",\"request_id\":" << request_id
           << ",\"cursor_sample\":" << cursor_sample;
    if (status == Status::Selected) {
        output << ",\"cue_first_sample\":" << cue.first_sample
               << ",\"cue_sample_count\":" << cue.sample_count
               << ",\"mouth_open\":" << cue.mouth_open
               << ",\"activity\":" << cue.activity;
    }
    output << "}";
    return output.str();
}

std::string PlaybackReceipt::to_json() const {
    std::ostringstream output;
    output.imbue(std::locale::classic());
    output << "{\"playback_epoch\":" << playback_epoch
           << ",\"request_id\":" << request_id
           << ",\"pcm_chunk_count\":" << pcm_chunk_count
           << ",\"pcm_sample_count\":" << pcm_sample_count
           << ",\"cue_count\":" << cue_count
           << ",\"cue_sample_count\":" << cue_sample_count
           << ",\"sample_rate\":" << sample_rate
           << ",\"pcm_contiguous\":" << (pcm_contiguous ? "true" : "false")
           << ",\"cue_contiguous\":" << (cue_contiguous ? "true" : "false")
           << ",\"cue_history_overflow\":"
           << (cue_history_overflow ? "true" : "false")
           << ",\"terminal\":" << (terminal ? "true" : "false")
           << "}";
    return output.str();
}

PlaybackReceiptProbe::PlaybackReceiptProbe(std::size_t max_cues)
    : max_cues_(max_cues) {
    if (max_cues_ == 0) {
        throw std::invalid_argument("playback receipt cue history must be bounded");
    }
}

void PlaybackReceiptProbe::begin(
    std::uint64_t playback_epoch,
    RequestId request_id) {
    if (playback_epoch == 0 || request_id == 0) {
        throw std::invalid_argument("playback receipt requires non-zero epoch and request id");
    }
    const bool replacement_epoch_claim =
        lifecycle_state_ == LifecycleState::Invalidated &&
        playback_epoch == playback_epoch_;
    if (!replacement_epoch_claim && playback_epoch <= playback_epoch_) {
        throw std::invalid_argument("playback receipt epoch must increase monotonically");
    }
    if (replacement_epoch_claim || playback_epoch > playback_epoch_) {
        lifecycle_state_ = LifecycleState::Active;
    }
    playback_epoch_ = playback_epoch;
    request_id_ = request_id;
    next_pcm_sample_ = 0;
    next_cue_sample_ = 0;
    pcm_started_ = false;
    cue_started_ = false;
    cues_.clear();
    receipt_ = PlaybackReceipt{};
    receipt_.playback_epoch = playback_epoch;
    receipt_.request_id = request_id;
}

void PlaybackReceiptProbe::invalidate(std::uint64_t playback_epoch) {
    if (playback_epoch == 0) {
        throw std::invalid_argument("playback receipt epoch must be non-zero");
    }
    if (playback_epoch <= playback_epoch_) {
        throw std::invalid_argument("playback receipt epoch must increase monotonically");
    }
    playback_epoch_ = playback_epoch;
    lifecycle_state_ = LifecycleState::Invalidated;
    request_id_ = 0;
    next_pcm_sample_ = 0;
    next_cue_sample_ = 0;
    pcm_started_ = false;
    cue_started_ = false;
    cues_.clear();
    receipt_ = PlaybackReceipt{};
    receipt_.playback_epoch = playback_epoch;
}

PlaybackReceiptStatus PlaybackReceiptProbe::observe_pcm(
    std::uint64_t playback_epoch,
    const PcmChunk& chunk) {
    if (playback_epoch != playback_epoch_) {
        return PlaybackReceiptStatus::StaleEpoch;
    }
    if (request_id_ == 0 || chunk.request_id != request_id_) {
        return PlaybackReceiptStatus::StaleRequest;
    }
    if (receipt_.terminal) {
        return PlaybackReceiptStatus::AlreadyTerminal;
    }
    if (chunk.sample_count == 0) {
        return PlaybackReceiptStatus::InvalidRange;
    }
    if (chunk.format.sample_rate == 0) {
        return PlaybackReceiptStatus::InvalidSampleRate;
    }
    if (receipt_.sample_rate != 0 &&
        receipt_.sample_rate != chunk.format.sample_rate) {
        return PlaybackReceiptStatus::SampleRateMismatch;
    }
    std::uint64_t end_sample = 0;
    if (!range_end(chunk.first_sample, chunk.sample_count, end_sample)) {
        return PlaybackReceiptStatus::InvalidRange;
    }
    if (receipt_.sample_rate == 0) {
        receipt_.sample_rate = chunk.format.sample_rate;
    }
    if (pcm_started_ && chunk.first_sample != next_pcm_sample_) {
        receipt_.pcm_contiguous = false;
        return PlaybackReceiptStatus::DiscontinuousPcm;
    }
    if (!pcm_started_ && chunk.first_sample != 0) {
        receipt_.pcm_contiguous = false;
        return PlaybackReceiptStatus::DiscontinuousPcm;
    }
    pcm_started_ = true;
    next_pcm_sample_ = end_sample;
    ++receipt_.pcm_chunk_count;
    receipt_.pcm_sample_count = next_pcm_sample_;
    return PlaybackReceiptStatus::Accepted;
}

PlaybackReceiptStatus PlaybackReceiptProbe::append_cue(const PlaybackCue& cue) {
    if (cue.playback_epoch != playback_epoch_) {
        return PlaybackReceiptStatus::StaleEpoch;
    }
    if (request_id_ == 0 || cue.request_id != request_id_) {
        return PlaybackReceiptStatus::StaleRequest;
    }
    if (receipt_.terminal) {
        return PlaybackReceiptStatus::AlreadyTerminal;
    }
    if (cue.sample_count == 0) {
        return PlaybackReceiptStatus::InvalidRange;
    }
    if (!std::isfinite(cue.mouth_open) || !std::isfinite(cue.activity)) {
        return PlaybackReceiptStatus::InvalidRange;
    }
    std::uint64_t end_sample = 0;
    if (!range_end(cue.first_sample, cue.sample_count, end_sample)) {
        return PlaybackReceiptStatus::InvalidRange;
    }
    if (cue_started_ && cue.first_sample != next_cue_sample_) {
        receipt_.cue_contiguous = false;
        return PlaybackReceiptStatus::DiscontinuousCue;
    }
    if (cues_.size() >= max_cues_) {
        receipt_.cue_history_overflow = true;
        return PlaybackReceiptStatus::CueHistoryFull;
    }
    if (receipt_.cue_sample_count >
        std::numeric_limits<std::uint64_t>::max() - cue.sample_count) {
        return PlaybackReceiptStatus::InvalidRange;
    }
    cue_started_ = true;
    next_cue_sample_ = end_sample;
    cues_.push_back(cue);
    ++receipt_.cue_count;
    receipt_.cue_sample_count += cue.sample_count;
    return PlaybackReceiptStatus::Accepted;
}

PlaybackCueSelection PlaybackReceiptProbe::select(
    const PlaybackCursorSnapshot& snapshot) const {
    PlaybackCueSelection selection;
    selection.playback_epoch = snapshot.playback_epoch;
    selection.request_id = snapshot.request_id;
    selection.cursor_sample = snapshot.utterance_sample;
    if (snapshot.playback_epoch != playback_epoch_) {
        selection.status = PlaybackCueSelection::Status::StaleEpoch;
        return selection;
    }
    if (request_id_ == 0 || snapshot.request_id != request_id_) {
        selection.status = PlaybackCueSelection::Status::StaleRequest;
        return selection;
    }
    if (!snapshot.position_available) {
        selection.status = PlaybackCueSelection::Status::CursorUnavailable;
        return selection;
    }
    if (receipt_.sample_rate == 0 ||
        snapshot.sample_rate != receipt_.sample_rate) {
        selection.status = PlaybackCueSelection::Status::SampleRateMismatch;
        return selection;
    }
    for (const auto& cue : cues_) {
        std::uint64_t end_sample = 0;
        if (!range_end(cue.first_sample, cue.sample_count, end_sample)) {
            continue;
        }
        if (snapshot.utterance_sample >= cue.first_sample &&
            snapshot.utterance_sample < end_sample) {
            selection.status = PlaybackCueSelection::Status::Selected;
            selection.cue = cue;
            return selection;
        }
    }
    selection.status = PlaybackCueSelection::Status::OutsideCueTimeline;
    return selection;
}

bool PlaybackReceiptProbe::mark_terminal(
    std::uint64_t playback_epoch,
    RequestId request_id) noexcept {
    if (playback_epoch != playback_epoch_ ||
        request_id_ == 0 ||
        request_id != request_id_ ||
        receipt_.terminal) {
        return false;
    }
    receipt_.terminal = true;
    return true;
}

PlaybackReceipt PlaybackReceiptProbe::receipt() const noexcept {
    return receipt_;
}

bool PlaybackReceiptProbe::range_end(
    std::uint64_t first_sample,
    std::uint32_t sample_count,
    std::uint64_t& end_sample) noexcept {
    if (sample_count == 0 ||
        first_sample > std::numeric_limits<std::uint64_t>::max() - sample_count) {
        return false;
    }
    end_sample = first_sample + sample_count;
    return true;
}

} // namespace qwen_tts_bridge::playback
