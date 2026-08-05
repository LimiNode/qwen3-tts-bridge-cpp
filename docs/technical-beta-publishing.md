# Technical-Beta Publishing

`scripts/publish-technical-beta.ps1` is the only script that may replace the
technical-beta package directory. It stages a candidate package, validates a
relocated copy with its private Python runtime, and publishes only after every
gate succeeds.

The required gates are:

1. exact package-tree and staged voice-asset manifests;
2. MinGW native DLL closure;
3. `qwen_tts_doctor.cmd` before and after the smoke requests for both the
   CustomVoice and Base model manifests;
4. a CustomVoice natural-EOS request; and
5. a Base natural-EOS request using the registered bootstrap voice profile.

The script writes a compact acceptance JSON supplied through
`-AcceptanceOutput`. It records the source commit, sealed package hashes,
external model-manifest identities, both generated WAV hashes, and the scope
of the same-host relocated validation. It deliberately contains no local
absolute paths and does not replace a clean-machine test on a second host.

For example, on the pinned validation host:

```powershell
.\scripts\publish-technical-beta.ps1 `
  -OutputRoot dist\QwenTTSBridge-technical-beta `
  -ReplaceExisting `
  -CustomVoiceModelPath C:\models\Qwen3-TTS-12Hz-0.6B-CustomVoice `
  -CustomVoiceModelManifest tmp\customvoice-model-manifest.json `
  -BaseModelPath C:\models\Qwen3-TTS-12Hz-1.7B-Base `
  -BaseModelManifest tmp\base-model-manifest.json `
  -VerifierPython .\.venv-packaging\Scripts\python.exe `
  -AcceptanceOutput docs\reports\technical-beta-r2-acceptance.json
```

The C++ examples are built with the configured MinGW Makefiles tree. Do not
substitute Ninja on the Windows validation machines.
