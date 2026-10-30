# Example PCM Capture Refactor

`PcmCapture` is an example-only diagnostic helper. It now lives in
`examples/common/pcm_capture.hpp` and `examples/common/pcm_capture.cpp` rather
than inside `qwen_tts_play.cpp`.

The extraction is behavior-preserving. Capture still receives the bridge PCM
chunks before playback post-processing, writes raw `s16le` bytes to a
process-scoped temporary path, publishes the PCM and JSON metadata only after
successful completion, and removes incomplete temporary files on destruction.
Existing output and temporary-path refusal, format validation, idempotent
`finalize()`, and rollback when metadata publication fails are unchanged.

`pcm_capture_test` covers exact multi-chunk bytes and metadata, format
mismatch, empty capture, repeated finalization, append-after-finalize,
destination and temporary-path conflicts, Unicode paths, incomplete-capture
cleanup, and metadata-publication rollback. The existing
`tests/python/verify_pcm_capture.py` remains the example-level smoke test.
