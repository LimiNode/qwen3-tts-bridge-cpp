# Real Qwen speech-animation E2E receipt (CMP 50HX)

Date: 2026-10-09

This report records the first real native-Qwen `PCM -> speech-animation`
acceptance pass. It compares the same deterministic request with the optional
adapter disabled and enabled for short, medium, and long Russian utterances.
The runs used the registered `kraftwerk_robot_ru_warm` voice and did not use a
mock engine or physical playback.

## Result

| Case | OFF first PCM | ON first PCM | ON - OFF | First animation span | Adapter mean / max | PCM end |
|---|---:|---:|---:|---:|---:|---:|
| short | 189.340 ms | 188.224 ms | -1.115 ms | 195.304 ms | 0.0195 / 0.0336 ms | 59,520 |
| medium | 188.954 ms | 187.999 ms | -0.955 ms | 198.116 ms | 0.0179 / 0.0312 ms | 119,040 |
| long | 189.782 ms | 189.313 ms | -0.469 ms | 195.612 ms | 0.0169 / 0.0327 ms | 259,200 |

All three pairs satisfied the mechanical acceptance contract:

- native completion was `natural_eos`;
- PCM sample ranges were contiguous;
- animation sample ranges were contiguous;
- the final audio span ended exactly at the real PCM end;
- terminal fade began exactly at that PCM end and reported 3,840 fade samples;
- queue high-water was one and `queue_full_count` was zero;
- the analyzer emitted both speech activity and silence spans;
- `mouth_open` varied from `0.0` to `0.999994`;
- OFF and ON produced the same PCM end for every paired request.

The ON first-PCM values were 0.47-1.12 ms earlier, not later. This difference
is normal fresh-worker/GPU timing variation and cannot be adapter work: the
adapter is invoked only after the downstream PCM callback. The measured
conversion/copy occupancy was 0.017-0.020 ms on average and at most 0.034 ms.

`first_downstream_pcm_ms` is the timestamp at the application callback boundary
where playback could be enqueued. It is not a WaveOut cursor or physical audio
latency measurement. Likewise, the receipt establishes real sample-addressed
mouth activity but does not claim a Unity/Godot visual-presentation acceptance.

## Evidence layout

Each case directory contains:

- `adapter-off.json`: complete PCM callback receipt without the adapter;
- `adapter-on.json`: complete PCM and animation-span receipt;
- `ab-summary.json`: paired timing and invariant summary.

The exact runtime, model, source, and artifact hashes are in
`provenance.json`. Input text is embedded in every receipt and is marked
`text_source=utf8_file`; no console-transcoded Russian text was used.

