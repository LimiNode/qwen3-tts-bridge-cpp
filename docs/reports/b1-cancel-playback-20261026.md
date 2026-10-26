# B1 continuation — active cancellation and physical playback

Status: **active-GPU cancellation PASS within bounded evidence; playback PARTIAL and not accepted; human listening NOT RUN**.

This report uses the frozen Base 1.7B model, registered voice, sealed portable
worker, and CMP 50HX inputs from merged B2-4/B1 receipts. Raw model logs, PCM,
and WAV/listening assets remain outside Git.

## Active-GPU cancellation

The worker was started with the same `faster/CUDA/bfloat16/SDPA` configuration,
`max_seq_len=768`, `emit_every_frames=8`, eager prefill, compile and CUDA
graphs disabled, and a 900-second request timeout. Request 1 was a long Russian
utterance. The harness waited for both `started` and the first real PCM frame
before sending `cancel`.

Observed evidence:

```text
request_engine_started: present (qtb engine thread, CUDA device 0)
PCM before cancel: 30,684 bytes (one chunk)
PCM after cancel: 0 bytes
terminal messages for request 1: [cancelled]
logical cancel acknowledgement: 1.420 ms
request_finished: terminal_state=cancelled, synthesis_ms=14,109.101,
  audio_bytes=30,684, audio_chunks=1
request_admission_released: present, admission_limit=16,
  admitted_requests=1
recovery request start after cancel: 3,129.278 ms
recovery request: completed, natural EOS, 170,656 PCM bytes
worker exit code: 0
```

This is stronger than the earlier protocol-only result: actual engine
execution is evidenced by `request_engine_started` and PCM before cancellation.
The `logical_cancel_ack_ms` value measures acknowledgement at the worker
protocol boundary; it is not CUDA/device unwind latency. The receipt captures
terminalization, engine-side cleanup ordering, and admission-release events
before the recovery request starts, but the worker does not expose a separate
device-stop timestamp. `request_admission_released` proves that this request
left the admission accounting; it does **not** prove that the configured
capacity was saturated or that a request was rejected for lack of capacity.

Raw receipt SHA-256:

```text
E:\stage-a-base-evidence\b1-active-cancel.json
5C27D7D455D329D3323676F0F14731ECF89A231CB9F7D266850AF21EA3CC2F1F
```

## B1-C physical playback probe

The existing C++ `qwen_tts_play` Release binary was run with the registered
voice and the same relocated worker/model. Player SHA-256:

```text
7DED14EB53015936F564F089748B03C14916301B49EFB7CF71218F2701FD18B1
```

The one-shot request produced a valid raw `s16le` capture: 5 chunks, 152,460
bytes, 24 kHz mono, and `playback_completed=true`. WaveOut metrics also report
the first submission and terminal completion. However, the queue-starvation
proxy recorded `queue_empty_before_later_chunk_count=4`; later PCM arrivals
were separated by roughly 4 seconds while each chunk represented about 639 ms
of audio. This is evidence of producer starvation in this slow-generation run,
not by itself a WinMM defect or a clean real-time playback acceptance. The
worker also warned that SoX was not installed, although the requested PCM
capture completed.

Therefore B1-C is **PARTIAL / NOT ACCEPTED**: the physical path ran and its
format/terminal receipts are valid, but this run is not clean playback evidence
and does not provide the required playback epoch receipt for the animation
oracle. Issue #235 remains open; no epoch assertion was weakened.

External playback artifacts:

```text
b1-playback-capture                  SHA-256 4E30A2690EB81F9B751997F0DFAB424BBB434C96338694DB6A0D7C7A44363712
b1-playback-capture.json             SHA-256 142BFC61E0549F2CBB4350E77A2E11C3B7C700BE5D3668A0D6649D85DF410078
b1-playback-metrics.json             SHA-256 82180AADBDB4CA71D19CED3C19A34AE318C26A4AADF47B8FF7A99BC644B0F852
```

Human listening was not performed, so intelligibility, pronunciation,
character-voice consistency, clicks/stutters, and phrase-tail quality remain
**NOT RUN**.

## Acceptance matrix

| Gate | Result | Boundary |
| --- | --- | --- |
| Active GPU cancellation after first PCM | **PASS** | one `cancelled`, no post-cancel PCM, engine/admission metrics present |
| Physical unwind/admission release | **PASS (bounded evidence)** | event ordering and 3,129 ms recovery admission delay; logical acknowledgement and admission release are not device-stop or capacity-rejection measurements |
| Recovery natural EOS | **PASS** | subsequent request completed with natural EOS |
| C++ physical playback (audio-only path) | **PARTIAL / NOT ACCEPTED** | valid capture, but four queue-empty starvation-proxy events |
| Playback epoch animation receipt | **NOT RUN** | current player binary does not emit the required epoch receipt |
| Human listening | **NOT RUN** | explicit listening decision still required |
| B2 clean-portable matrix | **NOT RUN** | separate stage |
| RTX 4090 validation | **NOT RUN** | independent post-freeze gate |
