# Changelog

## Unreleased — v0.2.0 release candidate

- documented the persistent native process-worker release route;
- added install/export support for `QwenTTSBridge::qwen_tts_bridge`;
- added minimal async synthesis, cancellation, and post-processing examples;
- added an optional backend-neutral request text preprocessing hook;
- validate preprocessor output as UTF-8 before submission and cover Cyrillic and
  English transformations;
- added explicit native model validation/download bootstrap tooling;
- made the native release launcher the documented quick-start path, with
  atomic model downloads and explicit offline/no-download modes;
- enabled the terminal audio fade/padding default with an explicit `--no-tail`
  opt-out;
- documented experimental direct qwen.dll usage and release limitations.
