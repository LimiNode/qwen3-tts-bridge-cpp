# Speech-animation integration boundary

`qwen3-tts-bridge-cpp` is the speech backend. It owns text preparation,
Qwen inference, streaming PCM, and the canonical sample timeline. A future
`speech-animation` component consumes that output; it is not implemented in
this repository.

```text
tts-front-cpp
    -> PreparedText / pronunciation context
    -> qwen3-tts-bridge-cpp
       -> PCM + sample-addressed timing
       -> optional Qwen terminal diagnostics
    -> speech-animation
       -> audio analysis / visemes / avatar policy
```

## Downstream inputs

For prepared requests, `TtsCallbacks::on_text_prepared` receives the exact
frontend context once before audio when the worker starts the request:

* original source text;
* normalized frontend text;
* pronunciation text;
* semantic stress decisions;
* warnings and uncertainty.

`TtsCallbacks::on_timing` receives a lightweight sideband event for each PCM
chunk. It is addressed by sample position, not callback arrival time. The
callback carries no viseme decision and no phoneme ground truth.

## Realtime rules

The timing sideband is informational and must remain cheap and non-blocking.
Audio delivery does not wait for animation analysis. Applications that need
heavier DSP should publish the bounded `PcmChunk`/`SpeechTimingChunk` pair to
an owned downstream queue with an explicit overflow policy. Analyzer failure
must not stop PCM delivery unless the application explicitly chooses a
fail-closed policy.

The bridge does not add an intentional playback delay for animation. Physical
playback and avatar scheduling remain outside the core client.

## Dependency direction

The bridge may expose a future optional adapter target, but the core build must
not depend on a generic lipsync, Unity, Godot, VRM, SALSA, or viseme library.
The generic speech-animation core must not import Qwen bridge headers. Mapping
from `PcmChunk`/`SpeechTimingChunk` into animation-neutral DTOs belongs in an
optional bridge adapter or in the application integration layer:

```text
application / optional adapter
    ├── qwen3-tts-bridge-cpp
    └── speech-animation core
```

The bridge must not know the animation package's policy or model, and the
animation core must remain usable with other TTS backends.

## Qwen-side optional adapter

When `QWEN_TTS_BRIDGE_BUILD_SPEECH_ANIMATION=ON`, the bridge builds the
`QwenTTSBridge::qwen_tts_bridge_speech_animation` adapter against the pinned
`external/cpp/speech-animation` submodule. The adapter:

1. preserves the original bridge `on_audio`/playback callback;
2. converts mono `s16le` chunks into the neutral float `SpeechTimingChunk`;
3. maps lifecycle to `begin()`, `push()`, `complete()`, and `cancel()`;
4. exposes `process_available()` for the consumer thread.

Analyzer work is never performed in the bridge audio callback. The optional
adapter is intentionally build-tree-only, even when
`QWEN_TTS_BRIDGE_BUILD_SPEECH_ANIMATION=ON`; it is not part of the default core
install. Applications that enable it must provide the speech-animation
dependency and target.

Animation integration failures are isolated from synthesis. Unsupported PCM or
queue backpressure cancels/deactivates only the animation pipeline and is
reported through the adapter diagnostic handler; the original bridge
`on_audio`, `on_completed`, `on_cancelled`, and `on_error` callbacks continue to
be forwarded unchanged.

## Real Qwen acceptance probe

The build-tree-only `qwen_tts_speech_animation_probe` is the first runtime
receipt harness. It launches the worker supplied with `--worker`, submits one
real request, and records PCM ranges, animation receipts, terminal fade,
first-PCM/first-span latency, callback occupancy, queue high-water, and adapter
diagnostics. It does not play audio and does not change the production client.

Build it with `QWEN_TTS_BRIDGE_BUILD_EXAMPLES=ON` and
`QWEN_TTS_BRIDGE_BUILD_SPEECH_ANIMATION=ON`, then run paired requests with the
same worker/model/profile and text:

```powershell
qwen_tts_speech_animation_probe.exe --adapter off `
  --worker C:\path\to\qwen-worker.exe `
  --worker-arg ... --text-file C:\path\to\russian-utterance.txt `
  --output-json C:\tmp\speech-animation-off.json

qwen_tts_speech_animation_probe.exe --adapter on `
  --worker C:\path\to\qwen-worker.exe `
  --worker-arg ... --text-file C:\path\to\russian-utterance.txt `
  --output-json C:\tmp\speech-animation-on.json
```

For a repeatable paired run, `scripts/run-speech-animation-qwen-e2e.ps1`
launches the same worker configuration once with the adapter OFF and once with
it ON, then writes `ab-summary.json` plus both full receipts. Pass the worker
arguments as one PowerShell array, for example
`-WorkerArgument @('--runtime-dir', 'C:\runtime', ...)`. For Russian acceptance,
prefer a known UTF-8 file via `-TextFile`; the probe reads its bytes directly
and records `text_source=utf8_file`, avoiding PowerShell/console transcoding
ambiguity.

The ON receipt is accepted only when PCM and animation sample ranges are
contiguous, the last audio span ends at the real PCM end, terminal fade is
anchored there, and `queue_full_count` is zero. Compare
`first_pcm_ms`/`first_downstream_pcm_ms` between OFF and ON; the downstream
timestamp is the delivery point where an application playback callback would
run, not a physical WaveOut measurement. `adapter_mean_ms` and `adapter_max_ms`
report the callback-side conversion/copy cost. Human listening of the same
captured request remains a separate quality gate.

The first three-utterance native-Qwen CMP 50HX receipt is archived in
[`reports/speech-animation-qwen-e2e-cmp50hx-20261009/`](reports/speech-animation-qwen-e2e-cmp50hx-20261009/README.md).
