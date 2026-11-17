# R1 corrective closeout — local candidate

Status: **conditional / NO-GO for release promotion**. This receipt records a
reviewable local candidate; it is not a tag, GitHub release, or support claim.

## Exact source and automated verification

- Integration branch: `integration/r1-corrective`
- Current integration HEAD (documentation and packaging-script follow-up):
  `ec2b1d2a`
- Implementation HEAD used for the corrective binaries and package:
  `faf546017ff05101788457ae6fd79fc10ba9a67c`
- The package was regenerated after the A1–A3 corrective commit.  The receipt
  follows that exact implementation commit and records the resulting hashes.
- Corrective commits include native admission/shutdown/package fixes,
  frontend-aware native defaults, and idempotent recovery of incomplete native
  voice publications.
- MSVC Release CTest: **46/46 PASS** on the preceding native candidate; the
  corrective native targets additionally passed the focused subprocess suites
  (`qwen_tts_native_worker_test`, `stdio_transport_test`).
  The previous failure was the forced-termination recovery path; the new
  bounded recovery handles transient Windows path/handle races and disposable
  incomplete artifacts fail closed without touching a committed manifest.
- Python corrective lifecycle and packaging/receipt suites: **67 tests, 1
  skipped**, plus `validate-acceptance-receipts.py` validating 2 canonical
  receipts.  The historical full Python result remains `492 passed, 7
  skipped` and is retained as earlier evidence.
- Native packaging contract tests: **12/12 PASS**, including a real PE32+
  fixture with normal imports, delay imports, recursive dynamic-module
  traversal, and a missing transitive dependency.  The test exercises the
  production PE parser without replacing `_imports()`.
- Native publication/recovery qualification: `qwen_tts_native_worker_test`
  passed in **3 consecutive Release runs** after the corrective changes.
- The production Release worker was built with `BUILD_TESTS=OFF` and
  `QWEN_TTS_BRIDGE_ENABLE_TEST_HOOKS=OFF`; binary-string inspection found no
  `QTB_TEST_PUBLICATION`, `QTB_TEST_RECOVERY`, or `QTB_TEST_PERSISTENCE` seams.
  The separate instrumented worker intentionally contains those hooks for
  deterministic recovery tests.

## Native package measurement

The package was assembled from the committed Release binaries at the
implementation HEAD above and the pinned qwentts runtime (`130cb99`, ABI 6).
The generated manifest records that exact implementation revision; no manual
provenance edit was made.

| Artifact | Result |
| --- | --- |
| ZIP | 435,248,520 bytes |
| Unpacked tree | 573,042,652 bytes, 21 files |
| ZIP SHA-256 | `1D3FBEDEE250F2D5B46B091583105BED01E80814CBF5BE1BA15F340059C489A7` |
| Python/PyTorch bundled | no |
| GGUF weights or user recordings bundled | no |
| PE dependency closure and extraction verification | PASS |

The review-only package is in the ignored local path
`.tmp/r1-native-package-faf54601.zip`; the previous package remains historical
evidence.  No release tag or GitHub release was created.
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
