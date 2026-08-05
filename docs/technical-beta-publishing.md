# Technical-Beta Publishing

`scripts/publish-technical-beta.ps1` is the only script that may replace the
technical-beta package directory. It refuses a dirty source worktree, stages a
candidate beside the final destination on the same volume, validates a
relocated copy with its private Python runtime, and publishes only after every
gate succeeds.

The required gates are:

1. exact package-tree and staged voice-asset manifests;
2. MinGW native DLL closure;
3. `qwen_tts_doctor.cmd` before and after the smoke requests for both the
   CustomVoice and Base model manifests;
4. a CustomVoice natural-EOS request; and
5. a Base natural-EOS request using the registered bootstrap voice profile.
6. a second, in-place validation after publication at the final destination.

The package-tree manifest seals every file and directory. Empty
`__pycache__` directories are the only explicitly permitted transient
directories; Python bytecode files are always rejected. The relocated and
published-destination reports record pre/post manifest verification.

The script writes generated acceptance JSON supplied through
`-AcceptanceOutput`. It records clean source provenance, the exact source and
test commit, an empty-diff SHA-256, sealed package hashes, model identities,
every gate command and exit code, and machine-readable natural-EOS results for
both model families. The acceptance report deliberately contains no local
absolute paths and does not replace a clean-machine test on a second host.

During validation the worker starts from its package directory with private
`PYTHONHOME` and `PYTHONPATH`, disabled user-site and bytecode writes, package
voice registry, and offline Hugging Face/Transformers variables. This detects
accidental development-checkout and cache dependencies before the independent
CMP gate.

Replacement keeps the old marked package as a sibling backup until the
published destination has passed its validation. The lightweight
`scripts/test-technical-beta-publication.ps1` injects failures before and
after the swap and verifies rollback without requiring CUDA.

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
  -AcceptanceOutput docs\reports\technical-beta-r3-acceptance.json
```

The C++ examples are built with the configured MinGW Makefiles tree. Do not
substitute Ninja on the Windows validation machines.
