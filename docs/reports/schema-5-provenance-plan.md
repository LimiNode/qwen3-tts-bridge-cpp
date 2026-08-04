# Schema 5 Provenance Plan

Schema 5 supersedes the historical schema-4 recorded-hash bootstrap evidence.
It exists to bind a selected synthetic reference candidate to the actual bytes
of the runtime that generated it.

## Required Evidence

- The pinned model directory passes its complete content manifest.
- The active Python interpreter, standard library, and active site-packages
  pass an actual-byte runtime manifest.
- Each recorded distribution file stores its wheel `RECORD` hash for diagnostic
  comparison and its independently calculated actual SHA-256 for verification.
- The runtime tree is enumerated, so a new importable file outside `RECORD`
  changes the manifest.
- FasterQwen and bridge source trees are clean, including no untracked files.
- The terminal trace includes EOS termination, terminal index, generated and
  emitted steps, max-limit flags, codec frame count, and codec SHA.

## Migration

Existing schema-4 sidecars remain historical experiment records. They are not
eligible for `--resume` under schema 5. Do not repeat a broad candidate search
solely to migrate metadata: rerun only a deliberately selected reference if a
new authoritative candidate is required.

## Runtime Cost

Actual-byte verification intentionally reads large Torch, CUDA, and Triton
files. On the local FasterQwen environment, manifest creation took about
190 seconds and a full verify took about 90 seconds. This cost is acceptable
for an authoritative bootstrap run and must not be hidden by substituting
`RECORD` values for file-content hashes.
