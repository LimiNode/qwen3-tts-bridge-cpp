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

The source records and frozen policy remain in
`../representative-v4-frequency-exact-allowlist-r9/`; this directory contains
only the operational schedule and its run outputs.

The cancellation semantic seed is deliberately separate from the normal-run
seed pool. `cancellation-sentinel-calibration.json` records the real-runtime
preflight that established that seed leaves work after the third audio chunk
for every scheduled label. This prevents `after_third_audio` from racing a
known EOS terminal event.
