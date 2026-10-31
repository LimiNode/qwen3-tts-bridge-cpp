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
`.tmp/base-acceptance/<run-id>/` directory for manifests, receipts, logs, and
listening outputs. Preserve migrated historical evidence under
`.tmp/historical/<name>/`; treat that directory as a protected local archive,
excluded from routine cleanup. Ignored directories are not versioned,
transferred, or backed up by Git, so historical evidence requires an
independent backup before any rollback copy is deleted. Do not create new
evidence in sibling temporary directories or outside the repository.
