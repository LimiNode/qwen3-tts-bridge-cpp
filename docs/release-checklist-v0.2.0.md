# v0.2.0 release-readiness checklist

## Supported release route

- [ ] Build `qwen_tts_bridge` and the persistent process worker with the pinned
  qwentts runtime for the target Windows GPU.
- [ ] Package `qwen_tts_play.exe`, `qwen_tts_native_worker.exe`, the CUDA DLL
  runtime, and a separately provisioned `models/` directory.
- [ ] Validate model files with `scripts/ensure-native-models.ps1`; do not put
  weights or local voice recordings in Git.
- [ ] Keep the qwen.dll in-process adapter disabled unless its ABI and target
  hardware evidence are explicitly accepted.

## Verification

- [ ] Run all CTest protocol, session, post-processing, and mock-worker tests.
- [ ] Run the installed-package consumer smoke using
  `find_package(QwenTTSBridge CONFIG REQUIRED)`.
- [ ] Run the native worker ABI/contract tests when the qwentts submodule is
  available.
- [ ] Confirm UTF-8 Russian and English text, registered voice provenance,
  cancellation followed by a second request, and natural/assisted/forced EOS
  metrics on the target hardware.
- [ ] Record exact bridge, qwentts, ggml, model, registry, and runtime hashes in
  the release evidence before tagging.

## Known limitations

The release bundle is not a single-file installer. Model downloads are explicit
and cacheable, and the current text preprocessing hook is intentionally an
identity default with no bundled NLP dependency. WebSocket, Unity-specific
integration, and direct DLL execution remain future/experimental work.
