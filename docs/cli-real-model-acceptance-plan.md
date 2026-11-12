# Real-model CLI acceptance plan

Status: planning only. No real-model inference or listening result is claimed
by this document.

This plan is the acceptance gate for the installed Python `qwen-tts` CLI after
the contract and integration wave. It does not authorize implementing the
future C++ CLI and does not promote a model family or native backend.

## CLI surface and runner boundary

The required end-to-end surface is exercised through the installed command,
not by calling implementation modules directly. At minimum, the runbook must
invoke the real commands `qwen-tts synth`, `qwen-tts play`, `qwen-tts voices
create`, `qwen-tts voices verify`, and the legacy `qwen-tts design` route.
`scripts/run-real-model-release-acceptance.ps1` is auxiliary telemetry,
fixture, and playback infrastructure; it is not a substitute for the full CLI
matrix. The runner uses the checkout worker sources through `PYTHONPATH`, so
its results are not portable-package acceptance unless a separately assembled
package is explicitly tested.

The existing `scripts/test-portable-user-cli.ps1` provides installed,
relocated **mock-only** coverage for all explicit family routes, `play --out`,
legacy `design`, and `voices create` → `verify` → Base synthesis. It also
checks WAV/completion receipts, fail-closed voice selection and a hanging-child
watchdog. Its `cli-acceptance-summary.json` retains command logs, artifact
hashes, timestamps and independent result layers. This is a run summary, not
a canonical model receipt. Its release disposition is always `blocked`, even
when mechanical checks pass. It never performs model acceptance or listening.

Real installed-command automation remains a separate prerequisite: the
checkout auxiliary runner does not cover it, and the mock package runner must
not be pointed at real models in an attempt to promote its verdict. The
remaining hardware matrix below must run the sealed installed CLI without
mock switches and retain exact model/runtime/corpus manifests.

## Scope and evidence storage

Run the matrix on a clean Windows machine with an idle GPU, a sealed worker
runtime, external model directories, and the exact bridge commit under test.
Use the existing runner only where its contract applies, and invoke the
installed CLI commands listed above directly.

Keep payloads under `.tmp/base-acceptance/<run-id>/`. This directory is local,
ignored storage: it is neither durable evidence nor universally available to
another checkout or machine. Commit only a small tracked receipt under
`docs/reports/` after the run. Each tracked receipt must record the local or
repository-relative payload path, byte count, SHA-256, and whether the payload
is still available locally or must be restored from an identified archive
before the result can be reused. Never commit WAV, model, runtime, or raw-log
payloads.

Every case records:

- bridge commit, worker/runtime revisions, model path and revision or an
  explicit `not_pinned` state;
- hardware identity (GPU model and UUID, driver, CUDA), Python/Torch/runtime
  revisions, and the model revision or `not_pinned` state;
- model family, backend, device, dtype, generation options, exact corpus/seed
  and request-options hash;
- startup, first-audio, completion, PCM byte/frame and natural-EOS metadata;
- WAV path, byte count and SHA-256, plus playback receipt when `play --out` or
  physical playback is exercised;
- mechanical status, listening status, and release status separately.

Use only these result values: `pass`, `fail`, `not_run`, `unsupported`, and
`not_assessed`. Every `not_run`, `unsupported`, or `not_assessed` result must
include a concise reason and identify any missing prerequisite. A `fail` must
retain the failing receipt and environment; it is not silently converted to
`not_run`.

## Required matrix

| Case | CLI route | Required checks |
| --- | --- | --- |
| Base 0.6B | `synth` and `play --voice-id` with an approved registry row | managed reference compatibility, non-empty PCM, natural EOS, valid PCM16 mono 24 kHz WAV, sequential second request |
| Base 1.7B | `synth` and `play --voice-id` | same checks, plus worker restart and registry persistence |
| CustomVoice 0.6B | `synth`/`play --model-family custom-0.6b --speaker ryan` and `serena` | preset speaker routing, English/Russian corpus, instruction forwarding, no Base fallback |
| CustomVoice 1.7B | `synth`/`play --model-family custom-1.7b --speaker ...` | explicit supported-speaker result, instruction behavior, no silent family substitution |
| VoiceDesign 1.7B | `synth`/`play --model-family voice-design --instruction ...` plus legacy `design` | style instruction, natural EOS, WAV publication and repeat request |
| Managed VoiceDesign | `voices create` → `voices verify` → `synth --voice-id` | registry durability, managed WAV SHA, provenance, receipt summary, duplicate rejection, strict natural EOS |

Rows are required only for model families and backends included in the
advertised release scope. Optional families or backends may be recorded as
`unsupported` or `not_run` with a reason and must not block an unrelated
release claim. A row is not a claim that every model revision or hardware
combination is supported.

For every required family, run both `--out` and no-`--out` playback where the
selected runtime supports playback. Use actual runtime speaker contracts in
examples and fixtures (for CustomVoice, for example, `ryan` and `serena`),
not placeholder speaker names. Include output/log aliases, existing-target
backup, rollback failure, malformed/truncated WAV, and timeout cleanup checks
using small fault-injection fixtures before the real-model run. Fixture checks
are mechanical safeguards and do not replace listening to the real artifacts.

## Backend comparison

Python/Faster is the production baseline. Upstream is a separately identified
diagnostic comparison and must not inherit a Faster acceptance verdict. Native
profiles are opt-in: run them only when the exact DLL, model hashes, profile,
and native acceptance prerequisites are available. A missing or unsupported
combination is an explicit `not_run` or `unsupported` result, never a fallback.

The same text corpus and seed/options should be used for comparable backends,
but receipts remain separate because listening and timing results do not
transfer across backend, model revision, or bridge commit.

An earlier receipt may be reused only when model identity and revision,
backend, bridge commit, runtime, hardware identity, and acceptance scope all
match. Historical receipts remain valid historical evidence, but they do not
automatically validate a newly added or changed CLI route. Fresh runs are
required for `voices create`, `play --out`, and any changed command path.

## Human listening gate

After mechanical checks, listen to exact WAV artifacts and record observer,
date, device and scope. Assess at least intelligibility, voice identity,
instruction/style adherence, clicks/stutter, complete final word and natural
tail, and isolation between sequential requests. Leave unassessed criteria as
`not_assessed` with a reason; “sounds good” is not a universal release verdict.

## Evidence and promotion

The tracked receipt must reference every retained payload by local or
repository-relative path, byte count and SHA-256, record availability or
restoration expectations, and update `docs/reports/acceptance-index.json` when
it is the current receipt. Do not commit model weights, runtime bundles, WAV
payloads or raw logs. A successful mock/CI run is not real-model acceptance. A
passing run supports only the declared machine, runtime, model revision and
listening scope.

Promotion remains blocked until the required rows, clean-environment package
check, and declared listening scope are complete. Partial results stay
`conditional` or `not_run` and must not be described as production support.

## Execution order

1. Validate the sealed runtime and model manifests without inference.
2. Run Base 0.6B with an approved managed/reference voice and sequential
   requests.
3. Run CustomVoice 0.6B smoke and sequential requests with `ryan` and
   `serena` where the model advertises them.
4. Run Base 1.7B with the managed voice registry, including restart and
   persistence checks.
5. Run CustomVoice 1.7B and VoiceDesign 1.7B.
6. Run `voices create` → `voices verify` → `synth --voice-id` end to end.
7. Repeat the declared subset with upstream/native backends.
8. Collect listening observations and write the canonical receipt.

Any failure is preserved as evidence with its exact environment and does not
justify changing model or backend selection during the same acceptance run.
