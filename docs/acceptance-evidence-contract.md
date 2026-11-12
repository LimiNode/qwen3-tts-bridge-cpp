# Acceptance evidence contract

This document is the normative contract for model, runtime, hardware, and
human-listening evidence. It keeps a local experiment reproducible without
making the experiment itself the only record of its result.

## Sources of truth

The evidence chain has three distinct layers:

1. `docs/reports/<acceptance-id>.json` is the tracked canonical receipt. It is
   the source of the current acceptance status and the exact identity of the
   candidate, model, runtime, hardware, and artifacts.
2. `.tmp/base-acceptance/<run-id>/` is ignored payload storage. It may contain
   WAV files, raw logs, manifests, and machine-generated receipts. It is not a
   durable status record and is not visible to a reviewer through GitHub.
3. Conversation, CI output, and local observations are inputs to a receipt.
   They are not a substitute for updating the tracked receipt.

Large payloads must not be committed. The canonical receipt must still record
each referenced payload by repository-relative path, byte count, and SHA-256.
If a payload is outside `.tmp/base-acceptance/`, it is historical evidence and
must be explicitly marked as such; new runs must use the standard directory.

`input_identity` is part of the canonical receipt. When exact UTF-8 request or
instruction bytes (or a corpus manifest) were preserved, record their SHA-256
under the corresponding field and identify the source. For historical runs
where those bytes were not retained, use `status: not_recorded` with an honest
source note; never reconstruct or invent a hash.

## Receipt lifecycle

For every significant acceptance run:

1. Create a unique `.tmp/base-acceptance/<run-id>/` directory.
2. Record the model family, backend, bridge commit, model revision, runtime
   revisions, hardware, request corpus, and exact output artifacts.
3. Record mechanical observations separately from human listening.
4. After a user or named observer listens to an artifact, update the tracked
   receipt in the same change. Include the observer, date, scope, criteria,
   notes, and artifact SHA-256.
5. Update `docs/reports/acceptance-index.json` when the receipt is current or
   supersedes an older receipt.
6. Preserve older receipts. Use `supersedes` rather than silently rewriting a
   historical run.

An agent must not say that a verdict was “recorded”, “fixed”, or “accepted” if
only an ignored file changed. The durable change is the tracked receipt.

## Status vocabulary

Mechanical checks use `pass`, `fail`, or `not_run`. Human listening uses:

- `pass`: all criteria in the declared listening scope were assessed and passed;
- `partial_pass`: the observer confirmed only a declared subset of criteria;
- `not_run`: no listening observation exists for the exact artifacts;
- `fail`: a declared criterion failed.

`release_status` is independent: `accepted` means the declared release scope
is complete, `conditional` means a limitation or gate remains, and `blocked`
means the scope cannot be promoted. Never use one undifferentiated `PASS` to
mean “PCM worked”, “the user listened”, and “the release is accepted”.

Listening verdicts do not transfer between model families, backends, model
revisions, bridge commits, or output candidates. Base, VoiceDesign, RU-stress,
Python/Faster, native, and upstream runs require separate receipts even when
they use the same text or voice name.

The observer's wording determines the scope. For example, “sounds good” may
support a scoped subjective smoke verdict, but it does not by itself prove
instruction adherence, absence of every artifact, sequential isolation, or
hardware portability. Leave unassessed criteria as `not_assessed`.

## Required handoff

New R1 canonical receipts use `schema_version: 2`. Version 1 remains readable;
do not rewrite historical receipts or listening verdicts to migrate them.
Version 2 adds three independent `{ "status": "...", "reason": "..." }`
objects: `case_result`, `listening_result`, and `release_disposition`.
Case/listening values are `pass`, `fail`, `not_run`, `unsupported`, or
`not_assessed`; disposition values are `accepted`, `conditional`, or `blocked`.
Every result requires a nonblank reason. The legacy `release_status` remains
for index compatibility and must agree with `release_disposition.status`.
Each version-2 artifact also has `availability: {status, reason}` with status
`local`, `archive`, `unavailable`, or `not_checked`. Name the restoration source
in the reason for an archived artifact (machine-local locations stay in local
data); never infer deletion from an absent worktree copy. Accepted receipts
require available evidence, not an assumed or unchecked location.

An aggregate case pass requires all declared mechanical checks, including
persistent repeat and restart, to pass. A legacy scoped `partial_pass`
listening observation maps to aggregate `not_assessed`, not `pass`; its
positive criteria and observer statement remain in `human_listening`.
An accepted version-2 receipt also requires recorded input hashes. Schema
validation checks structure; the Python validator additionally rejects
contradictory result layers. Neither validation substitutes for testing the
declared release matrix or listening to the exact artifacts.

Before handing work to a reviewer, an agent checks:

- the canonical receipt is tracked and included in the diff;
- the artifact paths and hashes identify the exact files that were inspected;
- model family, backend, bridge commit, model revision, runtime revision, and
  hardware are explicit;
- mechanical, human-listening, and release statuses are separate;
- unresolved gates are written as `not_run` or `not_assessed`, not inferred;
- old reports are preserved and linked through `supersedes` when applicable;
- the index points to the current receipt.

The canonical schema is [`acceptance-receipt.schema.json`](acceptance-receipt.schema.json).
Validate receipts locally with:

```powershell
python scripts/validate-acceptance-receipts.py
```

The same model-free validator and its positive/negative regression tests run
in the required `Acceptance evidence contract` CI job. `--check-artifacts` is
for a local machine that has the ignored payload directory; CI validates the
tracked contract without requiring model weights or WAV files.
