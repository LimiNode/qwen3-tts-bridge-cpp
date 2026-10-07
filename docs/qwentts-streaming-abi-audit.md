# qwentts streaming ABI audit

This note records the streaming contract of the pinned native engine used by
the bridge. It is an implementation audit, not a promise that codec frames
are independently decodable audio rectangles.

## Source pin

* qwentts.cpp: `130cb99af9ae12d554962fd0920e08fb4268af01`
* ABI: 6
* sample rate: 24,000 Hz
* tokenizer hop: 1,920 mono samples (12.5 Hz codec frame rate)

## What the callback receives

`qt_audio_chunk_cb` receives a pointer to mono float PCM and `n_samples`.
The callback is invoked from the engine compute worker and the pointer is only
valid for the duration of the callback. The bridge converts this payload to
the protocol's PCM format before exposing it to `PcmChunk` callbacks.

The streaming pipeline chooses a flush width of `T` codec frames. The first
flush is one frame, the width ramps up, and the final flush emits the pending
tail. The callback receives exactly `T * 1,920` samples for each lane. The
engine's persistent codec state carries causal convolution, transformer KV,
upsample, and DAC receptive-field state between flushes; the callback is not a
sequence of independently decoded windows.

The stream position for each lane advances by `T` after a successful decode.
The implementation therefore provides a deterministic contiguous sample
timeline, even though callback wall-clock arrival is affected by scheduling,
GPU work, batching, and transport backpressure.

## Bridge contract

The bridge exposes the sample timeline on every `PcmChunk`:

* `first_sample` is the zero-based sample-frame position within the request;
* `sample_count` is the number of interleaved sample frames in `bytes`;
* `format.sample_rate` identifies the clock rate.

The client derives these values from PCM byte accounting. They do not depend
on callback arrival timestamps. Post-processors must preserve or deliberately
transform these positions; the built-in terminal fade processor preserves
continuity while appending its configured tail.

The current qwentts ABI does **not** expose a text-conditioning position or a
stable generated-frame identifier in `qt_audio_chunk_cb`. Consequently the
bridge does not manufacture a `QwenGenerationMarker`, and codec-frame count is
kept as terminal diagnostic metadata only. A codec frame is not a phoneme,
word, or viseme boundary.

## Public guarantees and limits

Guaranteed by the bridge:

* sample positions are monotonic for one request;
* emitted ranges are contiguous for valid PCM chunks;
* timing is independent of callback wall-clock jitter;
* cancellation and terminal cleanup do not emit timing events after the
  request leaves the active registry.

Not guaranteed:

* phoneme or word alignment;
* viseme selection or mouth-motion policy;
* a one-to-one semantic mapping between codec frames and text;
* exact wall-clock playback time from callback timestamps.

Any future Qwen-specific progress signal must first prove its deterministic
relationship to the decoder state and text-conditioning sequence. Until then,
downstream animation should use the sample timeline and its own bounded audio
analysis.
