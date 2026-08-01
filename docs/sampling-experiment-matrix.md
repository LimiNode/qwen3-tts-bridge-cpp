# Sampling Experiment Matrix

`scripts/qwen_sampling_matrix.py` verifies request-level sampling behavior on
one already loaded FasterQwen CustomVoice engine. It is intentionally an eager
`StyleExperiment` tool: it must not be used to alter or benchmark the sealed
R10 exact-allowlist profile.

Before measuring it performs the same unbounded synthesis warmup as the style
experiment worker. The report keeps the returned warmup metadata so a cold
model-load result cannot be mistaken for normal interactive behavior.

The report records only hashes and effective settings. It does not establish
that any individual rendering sounds natural; that remains a listening review.

Run it with the same Python environment and FasterQwen source selected for the
style experiment:

```powershell
$Repo = 'C:\_repoz\qwen3-tts-bridge-cpp-frequency-r10-integration'
$Python = 'C:\_repoz\qwen3-tts-bridge-cpp\.venv-faster-qwen\Scripts\python.exe'
$Faster = 'C:\_repoz\faster-qwen3-tts-v032-stack112-clean'
$Model = 'C:\_repoz\qwen3-tts-bridge-cpp\models\Qwen3-TTS-12Hz-0.6B-CustomVoice'
$env:PYTHONPATH = "$Faster;$Repo\worker\src"

& $Python "$Repo\scripts\qwen_sampling_matrix.py" `
  --model $Model `
  --output "$Repo\docs\benchmark-artifacts\rtx4090-2026-07-30\sampling-matrix.json" `
  --speaker serena `
  --alternate-speaker ryan
```

The acceptance checks require exact PCM, codec trace, and terminal-state
matches for repeated same-seed sampled and greedy requests. They also check
that a changed seed and changed temperature alter at least one sampled output,
that greedy -> sampled -> greedy and speaker A -> B -> A do not leak state,
and that a request cancelled after its first PCM chunk does not contaminate the
next seeded control request.
