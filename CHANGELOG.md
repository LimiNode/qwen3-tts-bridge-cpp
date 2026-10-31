# Changelog

## Unreleased — Windows beta preparation

The proposed first beta uses the persistent Python worker as its production
baseline, with the documented Qwen3-TTS Base 1.7B profile and external,
manifest-verified model artifacts. The native qwentts.cpp worker, RU-stress
profile and speech-animation paths remain opt-in or experimental until their
separate acceptance gates are closed. WinMM is an optional, already-tested
playback module with device-specific acceptance still required. This section
is scope documentation, not a release announcement or tag.

- documented the persistent Python worker release baseline and optional native
  process-worker route;
- added install/export support for `QwenTTSBridge::qwen_tts_bridge`;
- added minimal async synthesis, cancellation, and post-processing examples;
- added an optional backend-neutral request text preprocessing hook;
- validate preprocessor output as UTF-8 before submission and cover Cyrillic and
  English transformations;
- added explicit native model validation/download bootstrap tooling;
- documented explicit external model provisioning, with native atomic downloads
  and offline/no-download modes remaining opt-in;
- documented the CLI-specific terminal tail contract: `qwen_tts_play` enables
  fade/padding by default with `--no-tail` opt-out, while `qwen_tts_save_wav`
  enables it only with `--tail`;
- documented experimental direct qwen.dll usage and release limitations;
- recorded the proposed beta capability scope and deferred model/DSP/avatar
  claims in `docs/beta-release-scope.md`.
