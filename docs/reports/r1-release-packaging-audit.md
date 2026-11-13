# R1 release packaging audit

Status: decision preparation only. No release artifact is published and no
backend is promoted by this report.

Baseline: `73fcdd4d37d9b2115579a3b868b7f2de838cc6ef`.

## Why this is a separate gate

The Python portable runtime is not comparable to a C++ launcher executable.
The portable package contains a private Python 3.11 tree, PyTorch with CUDA
libraries, site-packages, the worker and packaging metadata. Conversely, a
native package is not just `qwen.dll`: it must include the native process
worker, the qwentts/GGML backend DLL closure, manifests, launch/configuration
files and any required VC++ or CUDA runtime components. Models and reference
audio remain separate external artifacts.

The native-first R1 direction therefore changes evaluation priority, but does
not permit a size claim before the complete functioning dependency closure is
measured in a clean Windows relocation test.

## Measurements currently available

| Candidate | Result | Evidence and interpretation |
| --- | --- | --- |
| Full Python portable runtime | **Measured: 5,347,491,489 bytes; 35,919 files** | Local historical inventory `.tmp/base-acceptance/beta-rc-closeout-20261103/package-inventory-final.json`, manifest SHA-256 `bcf76c4243682fff7301d067fd92f86b886ca2fb2f15cc633e49cb28227afef8`. Site-packages account for 5,192,690,402 bytes; Torch libraries account for 4,435,159,806 bytes. Models were not included in the measurement. |
| Native SDK-only package | **Not measured** | Requires a reproducible Release install tree containing headers, libraries, CMake package files and an SDK consumer receipt. |
| Native process-worker package | **Not measured** | Requires the real `qwen.dll`, all GGML/CUDA/VC++ dependencies, worker, manifest and a relocated offline smoke test. Fake CI runtimes and standalone qwentts build outputs are not valid package measurements. |
| Minimal Python/Faster installation | **Not measured** | Must be assembled from pinned requirements into an isolated environment and tested for the same model/runtime routes. |
| Nuitka worker distribution | **Not measured for a release candidate** | Existing packaging scripts are build machinery; a valid reproducible archive and clean relocation receipt are still required. |

The Python result is a real measured footprint, not a promise that every
future package has the same contents. The native result is deliberately
`not_measured`; a small DLL or executable alone is not evidence of a usable
native distribution.

The focused native packaging work now provides
`scripts/assemble-native-portable-release.ps1` and the standard-library PE
dependency auditor in `scripts/audit-native-dependencies.py`. These tools
assemble and audit a real runtime supplied outside the repository; they do not
turn a build-tree or fake runtime into release evidence. Until the resulting
ZIP is relocated and accepted on both target GPUs, the native row remains
`not_measured` and the freeze decision remains NO-GO.

## Measurement procedure

Use `scripts/measure-release-footprint.py` on each candidate directory and ZIP
archive. It records unpacked bytes, archive bytes, file count, top-level and
extension breakdowns, largest files and the archive SHA-256 without modifying
the input. Keep the JSON under `.tmp/base-acceptance/<run-id>/` and publish only
a small validated receipt with the exact source/runtime/model manifests.

Required native closure inventory:

* `qwen_tts_native_worker.exe` and the C++ SDK/client tools;
* `qwen.dll`, `ggml.dll`, backend DLLs and their transitive runtime files;
* VC++/CUDA runtime dependencies that are not guaranteed by the clean target;
* runtime manifest, ABI/export checks, configuration and launcher scripts;
* licenses and SHA-256 manifest.

Measure both unpacked and compressed sizes, and count files. Report model
weights separately. A combined package is acceptable only when the same
dependency closure passes on CMP 50HX and RTX 4090; otherwise publish
hardware-specific packages or state the compatibility boundary.

## Proposed R1 artifact layout

The following are candidate artifact classes, not existing release assets:

1. Native Windows CUDA runtime package: worker, runtime DLL closure, manifests,
   configuration and a documented existing native entry point.
2. C++17 SDK package: headers, libraries, CMake package, minimal consumer and
   documentation, without inference runtime or models.
3. Optional Python/Faster package or bootstrap installer, distributed
   independently from native.
4. SHA-256 manifest, licenses and usage documentation.

R1 does not implement the future C++17 user CLI. Native acceptance must use the
existing worker/launcher/SDK surfaces; the full user-facing C++ CLI remains R2.
The Python backend remains installable separately and must not be silently
loaded as a fallback for a native request.

## Freeze impact and decision

The current decision is **NO-GO for packaging promotion** until the native
closure is measured and relocated on clean Windows, and until native Base
acceptance passes on CMP 50HX and RTX 4090. The known 5.35 GB Python footprint
is strong evidence for keeping Python optional, but it is not by itself a
reason to publish an unmeasured native package.

Do not publish a GitHub Release, commit models, or begin R2 CLI work from this
audit. After the native package and minimal Python measurements exist, compare
size, install complexity, offline behavior, model-family coverage, reliability,
quality and maintenance cost in the backend-selection decision record.
