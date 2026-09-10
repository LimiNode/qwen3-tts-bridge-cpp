# `scripts/` — setup, benchmark, and packaging scripts

Scripts are part of the product contract. Validate paths before use, avoid
machine-specific defaults, preserve caller environment variables, and return a
meaningful non-zero exit code on failure. PowerShell scripts must be parseable
by the supported Windows PowerShell version.

Benchmark scripts must save provenance and raw results, distinguish diagnostics
from acceptance gates, and never treat a partial/failed run as a pass. Keep
profile values in one owner or a documented shared contract; do not copy a
second profile matrix into another script.
