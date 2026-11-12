# Real-model CLI acceptance plan

Status: planning only. No real-model inference or listening result is claimed
by this document.

This plan is the acceptance gate for the Python `qwen-tts` CLI after the
contract and integration wave. It does not authorize implementing the future
C++ CLI and does not promote a model family or native backend.

## Scope

Run the matrix on a clean Windows machine with an idle GPU, a sealed worker
runtime, external model directories, and the exact bridge commit under test.
Use the existing `run-real-model-release-acceptance.ps1` runner where its
contract applies. Keep payloads under
`.tmp/base-acceptance/<run-id>/`; commit only a small receipt under
`docs/reports/` after the run.

Every case records:

- bridge commit, worker/runtime revisions, model path and revision or an
  explicit `not_pinned` state;
- model family, backend, device, dtype, generation options and request corpus
  hash;
- startup, first-audio, completion, PCM byte/frame and natural-EOS metadata;
- WAV path, byte count and SHA-256, plus playback receipt when `play --out` or
  physical playback is exercised;
- mechanical status, listening status, and release status separately.

## Required matrix

| Case | CLI route | Required checks |
| --- | --- | --- |
| Base 0.6B | `synth` and `play --voice-id` with an approved registry row | managed reference compatibility, non-empty PCM, natural EOS, valid PCM16 mono 24 kHz WAV, sequential second request |
| Base 1.7B | `synth` and `play --voice-id` | same checks, plus worker restart and registry persistence |
| CustomVoice 0.6B | `synth`/`play --model-family custom-0.6b --speaker ryan` and `serena` | preset speaker routing, English/Russian corpus, instruction forwarding, no Base fallback |
| CustomVoice 1.7B | `synth`/`play --model-family custom-1.7b --speaker ...` | explicit supported-speaker result, instruction behavior, no silent family substitution |
| VoiceDesign 1.7B | `synth`/`play --model-family voice-design --instruction ...` | style instruction, natural EOS, WAV publication and repeat request |
| Managed VoiceDesign | `voices create` → `voices verify` → `synth --voice-id` | registry durability, managed WAV SHA, provenance, receipt summary, duplicate rejection, strict natural EOS |

For every family, run both `--out` and no-`--out` playback where the selected
runtime supports playback. Include output/log aliases, existing-target backup,
rollback failure, malformed/truncated WAV, and timeout cleanup checks using
small fault-injection fixtures before the real-model run.

## Backend comparison

Python/Faster is the production baseline. Upstream is a separately identified
diagnostic comparison and must not inherit a Faster acceptance verdict. Native
profiles are opt-in: run them only when the exact DLL, model hashes, profile,
and native acceptance prerequisites are available. A missing or unsupported
combination is an explicit `not_run`/`unsupported` result, never a fallback.

The same text corpus and seed/options should be used for comparable backends,
but receipts remain separate because listening and timing results do not
transfer across backend, model revision, or bridge commit.

## Human listening gate

After mechanical checks, listen to exact WAV artifacts and record observer,
date, device and scope. Assess at least intelligibility, voice identity,
instruction/style adherence, clicks/stutter, complete final word and natural
tail, and isolation between sequential requests. Leave unassessed criteria as
`not_assessed`; “sounds good” is not a universal release verdict.

## Evidence and promotion

The tracked receipt must reference every retained payload by repository-relative
path, byte count and SHA-256, and must update
`docs/reports/acceptance-index.json`. Do not commit model weights, runtime
bundles, WAV payloads or raw logs. A successful mock/CI run is not real-model
acceptance. A passing run supports only the declared machine, runtime, model
revision and listening scope.

Promotion remains blocked until the required rows, clean-environment package
check, and declared listening scope are complete. Partial results stay
`conditional` or `not_run` and must not be described as production support.

## Execution order

1. Validate the sealed runtime and model manifests without inference.
2. Run CustomVoice 0.6B smoke and sequential requests.
3. Run Base 1.7B with the managed voice registry.
4. Run CustomVoice 1.7B and VoiceDesign 1.7B.
5. Run `voices create` end to end.
6. Repeat the declared subset with upstream/native backends.
7. Collect listening observations and write the canonical receipt.

Any failure is preserved as evidence with its exact environment and does not
justify changing model or backend selection during the same acceptance run.
