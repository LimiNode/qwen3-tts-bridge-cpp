# Frequency Exact-Allowlist Operational Soak R10

This directory defines the post-holdout operational soak for the frozen
frequency-ranked exact allowlist `[18, 19, 20, 26, 27, 29]`.

The schedule is intentionally not a new discovery or holdout set. It covers
all six compiled shapes plus three explicitly eager unknown shapes. The cases
exercise Russian, English, mixed language detection, and the `ryan` and
`serena` CustomVoice speakers. Every row declares the expected prefill route,
backend, and chunk schedule, so an unexpected compilation is a failure rather
than a reason to expand the allowlist.

`qwen_release_soak.py` uses this schedule for the 504-request Python worker
soak. `cpp-api-soak-manifest.jsonl` expresses the same nine cases in the public
C++ benchmark schema. The seed manifest contains more than the runner's
required twenty unique seeds.

The final Python run is `python-operational-soak-final-report.json`: 396 normal
completions and 108 cancellations passed with fixed cache cardinality six and
no Dynamo growth. `cpp-api-soak-r250-validation.json` independently accepts
225 normal public-C++-API requests and 25 first-PCM cancellations from one
persistent worker. A cancellation validates the observed PCM prefix, prefill
route, backend, and `cancelled` terminal event; it does not pretend that a
cancelled request completed the rest of its chunk schedule.

Those two PASS artifacts authorize only
`config/rtx4090-faster-customvoice-frequency-exact-allowlist-r10-internal-opt-in.json`.
The startup script default remains unchanged. The opt-in profile is tied to the
recorded RTX 4090, worker and FasterQwen source bundles, and must be
revalidated before use with another GPU, Python/Torch/CUDA stack, or source
bundle.

The source records and frozen policy remain in
`../representative-v4-frequency-exact-allowlist-r9/`; this directory contains
only the operational schedule and its run outputs.

The cancellation semantic seed is deliberately separate from the normal-run
seed pool. `cancellation-sentinel-calibration.json` records the real-runtime
preflight that established that seed leaves work after the third audio chunk
for every scheduled label. This prevents `after_third_audio` from racing a
known EOS terminal event.

This RTX 4090 Windows WDDM environment returns no process rows for
`nvidia-smi --query-compute-apps`, so PID-specific GPU memory is recorded as
unsupported rather than fabricated. The operational gate still requires the
worker's per-request `torch.cuda` allocated/reserved memory metrics, plus the
process-tree RSS and private-bytes checks.
