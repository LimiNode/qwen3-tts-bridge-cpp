# Model Runtime Provenance

Qwen model weights remain external to the portable package. A pinned Hugging
Face revision identifies the intended upstream snapshot, while a model runtime
manifest identifies the exact local file set used for one acceptance run. Both
are necessary: a matching revision alone is not a byte-level identity claim.

Build the manifest beside the external model directory:

```powershell
python scripts\model_runtime_manifest.py build `
  --model-path C:\models\Qwen3-TTS-12Hz-1.7B-Base `
  --repository Qwen/Qwen3-TTS-12Hz-1.7B-Base `
  --revision <pinned-revision> `
  --output C:\models\Qwen3-TTS-12Hz-1.7B-Base.manifest.json
```

Keep that manifest with the acceptance report. New technical-beta acceptance
reports embed the manifest, its document SHA-256, and its file count, so a
later machine can explain a content-digest mismatch without rereading model
weights from the original host.

To compare two manifests without accessing the models themselves:

```powershell
python scripts\model_runtime_manifest.py compare `
  --left-manifest C:\evidence\base-r3.manifest.json `
  --right-manifest C:\models\Qwen3-TTS-12Hz-1.7B-Base.manifest.json `
  --output C:\evidence\base-manifest-diff.json
```

The result records repository/revision equality plus deterministic added,
removed, and content-changed file paths. A digest mismatch is not silently
accepted: it must either be explained by this comparison or be treated as a
different external model snapshot.

`compare` is diagnostic and returns zero even when the manifests differ, so an
operator can always collect its report. Add `--require-match` when a script
must fail closed after writing the same comparison report:

```powershell
python scripts\model_runtime_manifest.py compare `
  --left-manifest C:\evidence\base-r3.manifest.json `
  --right-manifest C:\models\Qwen3-TTS-12Hz-1.7B-Base.manifest.json `
  --require-match
```

Historical R3 evidence records only the Base directory digest, not the full
historical file list. The CMP 50HX report therefore correctly records a
different Base digest at the same pinned revision but cannot prove the cause.
It does not claim byte-identical Base model content across the two machines.
