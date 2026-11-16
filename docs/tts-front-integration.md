# tts-front-cpp integration

The bridge uses the released `tts-front-cpp` v0.2.5 component, pinned as the
`external/cpp/tts-front-cpp` submodule at commit
`d1b6a6e18e7f51f8c51fff548bb84f10e749004a` (tag `v0.2.5`). The fixed
v0.2.2-to-v0.2.5 effective-text comparison is recorded in
`docs/reports/tts-front-v022-v025-effective-text.md`.

The preparation boundary is intentionally one-way:

```text
raw TtsRequest.text
    -> tts-front-cpp TextFrontend
    -> PreparedText (frontend stages + diagnostics)
    -> QwenTtsClient prepared synthesis
```

`QwenTtsClientOptions::text_preparer` takes precedence over the legacy string
`text_preprocessor`. A prepared request never runs either callback again. The
adapter copies `normalized_text`, `pronunciation_text`, warnings, and semantic
stress decisions into `PreparedText` so callers can record uncertainty instead
of silently guessing.

The frontend remains model-agnostic. `TextRenderCapability::Base` sends the
frontend pronunciation text without model-specific stress markers. The
`TextRenderCapability::ExplicitCombiningStress` capability is an opt-in Qwen
adapter contract: it renders a semantic `stressed_vowel` decision as combining
U+0301. Applications must select it only for a model that explicitly documents
that representation; the bridge does not infer this from a profile name.

Example composition:

```cpp
qwen_tts_bridge::TtsFrontTextPreparer preparer(preparer_options);
qwen_tts_bridge::QwenTtsClientOptions options;
options.text_preparer = [&preparer](const auto& request, auto& prepared, auto& error) {
    return preparer.prepare(request, prepared, error);
};
```

The adapter is built by default with
`QWEN_TTS_BRIDGE_BUILD_TTS_FRONT=ON`. Set it to `OFF` when only the core bridge
is required. The adapter target is `QwenTTSBridge::qwen_tts_bridge_tts_front`;
the core target remains independent from the frontend implementation.

The experimental native `ru-stress` model profile is now load-compatible with
the split GGUF runtime and advertises
`text_render_capability: "explicit_combining_stress"`. The R1 native example
configuration selects this profile by default and the native launcher derives
the explicit-stress renderer from that profile metadata. `--no-tts-front`
remains an explicit raw-text opt-out. Selecting the Base profile keeps the
renderer model-neutral and never adds combining marks.

This is a target R1 product default, not a completed release claim. Keep
listening, long-horizon, dual-GPU, and cancellation acceptance evidence
alongside the model provenance in
`docs/russian-stress-model-compatibility.md` before publishing R1.
