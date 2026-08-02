# Sampling Experiment Matrix

`scripts/qwen_sampling_matrix.py` verifies request-level sampling behavior on
one already loaded FasterQwen CustomVoice engine. It is intentionally an eager
StyleExperiment tool: it must not be used to alter or benchmark the sealed R10
exact-allowlist profile.

Before measuring it performs one bounded, seeded synthesis warmup. The report
keeps the returned warmup metadata so a cold model-load result cannot be
mistaken for normal interactive behavior.

Schema v2 records the bridge commit/tree/dirty state, worker-source bundle
hash, script and profile hashes, whole-model tree hash, FasterQwen source
state, Python/Torch/CUDA/Triton versions, GPU facts, and NVIDIA driver. A
report with a dirty bridge or FasterQwen tree is valid diagnostic evidence, but
is not a sealed release comparison.

The matrix uses five Russian and English text classes. Besides exact repeated
sampled and greedy controls, it sweeps these values one parameter at a time:

| Control | Values | Fixed controls |
| --- | --- | --- |
| `top_k` | `1, 10, 50` | temperature 0.4, top-p 1.0, repetition penalty 1.05 |
| `top_p` | `0.7, 0.9, 1.0` | temperature 0.4, top-k 50, repetition penalty 1.05 |
| repetition penalty | `1.0, 1.05, 1.2` | temperature 0.4, top-k 50, top-p 1.0 |

The checks establish that an override reached the engine and changed at least
one rendered output. They do **not** establish that the result sounds better.
Perceptual claims require the separate blinded listening package below.

Run the matrix with the same Python environment and FasterQwen source selected
for the style experiment:

```powershell
$Repo = 'C:\_repoz\qwen3-tts-bridge-cpp-frequency-r10-integration'
$Python = 'C:\_repoz\qwen3-tts-bridge-cpp\.venv-faster-qwen\Scripts\python.exe'
$Faster = 'C:\_repoz\faster-qwen3-tts-v032-stack112-clean'
$Model = 'C:\_repoz\qwen3-tts-bridge-cpp\models\Qwen3-TTS-12Hz-0.6B-CustomVoice'
$env:PYTHONPATH = "$Faster;$Repo\worker\src"

& $Python "$Repo\scripts\qwen_sampling_matrix.py" `
  --model $Model `
  --profile "$Repo\config\rtx4090-faster-customvoice-style-eager-experiment.json" `
  --output "$Repo\docs\benchmark-artifacts\rtx4090-2026-07-30\sampling-matrix-v2.json" `
  --speaker serena `
  --alternate-speaker ryan
```

The acceptance checks require exact PCM, codec trace, and terminal-state
matches for repeated same-seed sampled and greedy requests. They also verify
seed and temperature variation, the three one-variable sampling sweeps,
greedy -> sampled -> greedy and speaker A -> B -> A state isolation, and a
post-cancellation seeded control.

## Blinded Listening Review

Generate a local WAV package after the matrix passes. It writes to `dist/`, so
the rendered audio, hidden key, and personal listening notes are not committed.

```powershell
& $Python "$Repo\scripts\qwen_sampling_blind_review.py" `
  --model $Model `
  --profile "$Repo\config\rtx4090-faster-customvoice-style-eager-experiment.json" `
  --output-dir "$Repo\dist\sampling-blind-review-2026-08-02" `
  --speaker serena
```

Listen to every `item-*.wav` in random order and fill
`blind-review-form.jsonl`. Rate naturalness, clarity, stress and pronunciation,
emotion/style, and pace from 1 to 5; record repetitions or artifacts and short
notes. Do not open `blind-review-key.json` until the form is complete: it maps
the anonymous item IDs to `stable_sampled`, `expressive_sampled`, and
`greedy_control`. `blind-review-manifest.json` contains reproducibility facts
but deliberately does not reveal that mapping.
