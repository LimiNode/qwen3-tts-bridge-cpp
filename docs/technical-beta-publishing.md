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
`-AcceptanceOutput`. Schema 3 computes `acceptance_pass` from named
`required_gates`; it is never a hard-coded success marker. It records the
`artifact_source_commit` for the packaged source and the
`acceptance_tooling_commit` / `report_generation_commit` for the clean source
tree that produced the evidence. It also records candidate and published root
digests and requires them to match. The report deliberately contains no local
absolute paths and does not replace a clean-machine test on a second host.

During validation the worker starts from its package directory with private
`PYTHONHOME` and `PYTHONPATH`, disabled user-site and bytecode writes, package
voice registry, and offline Hugging Face/Transformers variables. This detects
accidental development-checkout and cache dependencies before the independent
CMP gate.

Replacement keeps the old marked package as a sibling backup until the
published destination has passed its validation. The lightweight
`scripts/test-technical-beta-publication.ps1` injects failures before the
backup rename, after the backup rename, after the swap, during published
validation, and before backup cleanup. It writes an optional machine-readable
case matrix and verifies rollback without requiring CUDA. The publisher runs
that matrix before packaging and embeds the passing result in the acceptance
report.

For a legacy acceptance report that predates schema 3, use
`scripts/verify-technical-beta-acceptance-evidence.ps1` from a clean worktree.
It produces a separate augmentation report: it derives gates from the immutable
historical smoke evidence and combines them with the current fault matrix. It
does not overwrite or relabel the original package report.

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
