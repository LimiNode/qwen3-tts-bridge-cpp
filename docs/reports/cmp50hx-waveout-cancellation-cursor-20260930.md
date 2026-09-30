# CMP 50HX WaveOut cancellation cursor evidence

This report records the first hardware check of the cursor-aware interruption
path after PR #170/#171. The diagnostic option is opt-in; it is not part of the
normal playback path.

## Contract

The player must, on cancellation:

1. read the physical WaveOut cursor;
2. select the queued buffer containing that cursor (or the first buffer after a
   gap);
3. retain only the configured fade window from that position;
4. call `waveOutReset` and discard producer-ahead buffers; and
5. accept the next request without restarting the worker.

The tested fade was 15 ms at 24 kHz (`360` frames), with no cancellation
silence.

## Hardware and runtime

| Item | Value |
| --- | --- |
| GPU | NVIDIA CMP 50HX, compute capability 7.5 |
| Driver | 581.94 |
| qwentts | `40ab5eb` |
| Talker | `qwen-talker-1.7b-base-Q8_0.gguf` |
| Codec | `qwen-tokenizer-12hz-Q8_0.gguf` |
| Voice | registered `canonical_fidelity` Kraftwerk profile |
| Bridge merge | `9277b0eb` (PR #171) |

The raw diagnostic JSON and process logs are retained outside the repository
under `C:\tmp\cmp50hx-cancellation-diagnostics2` and
`C:\tmp\cmp50hx-cancellation-diagnostics3`; generated audio and logs are not
committed.

## Observed events

| Scenario | `stream-max-chunk-frames` | Cursor frame | Selected buffer | Local offset | Queued audio | Reset duration | Fade frames | Late audio | Next request |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| early | 1 | 82,645 | 82,200 + 1,920 | 445 | 160 ms | 14.8 ms | 360 | 0 | completed, natural EOS |
| middle | 1 | 165,225 | 164,760 + 1,920 | 465 | 80 ms | 1.9 ms | 360 | 0 | completed, natural EOS |
| backlog | 8 | 76,064 | 74,520 + 15,360 | 1,544 | 640 ms | 6.8 ms | 360 | 0 | completed, natural EOS |

The early row was repeated after the request-linkage fix in PR #171; its JSON
also records `old_request_id=1`, `old_terminal_state=cancelled`,
`new_request_id=2`, and `new_terminal_state=completed`. All three processes
exited with code `0`, and the native worker remained alive between requests.

These runs establish cursor availability, buffer selection, bounded fade
length, reset completion, and late-audio rejection for the tested WaveOut
scenarios. They do not by themselves establish absence of audible clicks on
all devices; a loopback capture remains a separate listening/measurement gate.
