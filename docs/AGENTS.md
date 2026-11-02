# `docs/` — durable project knowledge

Keep reproducible methods, benchmark evidence, profile trade-offs, and
architecture decisions here. Research reports must distinguish measured facts,
interpretation, and unresolved gates; never turn an unverified experiment into
a production claim.

Use [`ai-code-quality.md`](ai-code-quality.md) for the anti-generated-code
policy. Keep README changes short; detailed experimental history belongs in
reports under `docs/`. Do not introduce a translated README without an
explicit decision on its ownership and synchronization policy.

For new model and hardware acceptance runs, use the ignored repository-local
`.tmp/base-acceptance/<run-id>/` directory for payloads: manifests, raw
receipts, logs, WAV files, and listening outputs. The final acceptance status
must be a small tracked receipt under `docs/reports/`, listed in
`docs/reports/acceptance-index.json`; an ignored receipt is not durable and is
not reviewable through GitHub. Follow
[`acceptance-evidence-contract.md`](acceptance-evidence-contract.md)
and run `python scripts/validate-acceptance-receipts.py` before handoff.

After a user or named observer listens to an exact artifact, update the tracked
receipt in the same change. Keep mechanical status, human-listening status,
and release status separate. Do not copy a verdict between model families,
backends, revisions, or candidates. Preserve migrated historical evidence
under `.tmp/historical/<name>/`; treat that directory as a protected local
archive, excluded from routine cleanup. Ignored directories are not versioned,
transferred, or backed up by Git, so historical evidence requires an
independent backup before any rollback copy is deleted.
