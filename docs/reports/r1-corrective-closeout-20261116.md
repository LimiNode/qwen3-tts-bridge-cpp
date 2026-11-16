# R1 corrective closeout — local candidate

Status: **conditional / NO-GO for release promotion**. This receipt records a
reviewable local candidate; it is not a tag, GitHub release, or support claim.

## Exact source and automated verification

- Integration branch: `integration/r1-corrective`
- Combined HEAD: `fd940f912176315b8ec7c03dcfade011cc29a6af`
- Corrective commits include native admission/shutdown/package fixes,
  frontend-aware native defaults, and idempotent recovery of incomplete native
  voice publications.
- MSVC Release CTest: **46/46 PASS** after two focused recovery repetitions.
  The previous failure was the forced-termination recovery path; the new
  bounded recovery handles transient Windows path/handle races and disposable
  incomplete artifacts fail closed without touching a committed manifest.
- Python/package results from the preceding committed candidate remain
  historical evidence (`492 passed, 7 skipped`); they were not rerun by this
  closeout.

## Native package measurement

The package was assembled from the committed Release binaries and the pinned
qwentts runtime (`130cb99`, ABI 6). The generated manifest records the exact
source HEAD above; no manual provenance edit was made.

| Artifact | Result |
| --- | --- |
| ZIP | 435,249,134 bytes |
| Unpacked tree | 573,044,435 bytes, 21 files |
| ZIP SHA-256 | `5C4E879A59143D92F41855F01C7A95C465FB47BDEB61409A4689311E7926D18F` |
| Python/PyTorch bundled | no |
| GGUF weights or user recordings bundled | no |
| PE dependency closure and extraction verification | PASS |

The review-only package is in the ignored local paths
`.tmp/r1-native-package-final.zip` and `.tmp/r1-native-package-relocated/`.
They are evidence, not release assets.

## Remaining gates

R1 remains NO-GO until all of the following are independently recorded for the
same frozen package/source/runtime/model identities:

- clean relocation real-model synthesis outside the checkout;
- CMP 50HX and RTX 4090 native qualification, including repeat/cancel/restart,
  physical playback and peak-memory measurements;
- matched RU/EN A/B WAV corpus and human listening;
- correction or fail-closed contract for the upstream `tts-front-cpp` defect
  where `2 книги` currently becomes `два книги` (the bridge does not apply a
  string substitution); and
- publication of the review branch for independent inspection.

CustomVoice Python/BF16 observations remain a separate optional capability gate
and do not promote native Base/RU-stress support.
