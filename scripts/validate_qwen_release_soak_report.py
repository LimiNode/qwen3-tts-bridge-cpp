"""Revalidate a completed Qwen release-soak artifact with the current gate."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess

try:
    from qwen_release_soak import _shapes_by_label, _validate_release_soak
except ModuleNotFoundError:
    from scripts.qwen_release_soak import _shapes_by_label, _validate_release_soak


_VALIDATOR_SCHEMA_VERSION = 2
_REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--schedule", type=Path, required=True)
    parser.add_argument("--seed-manifest", type=Path, required=True)
    parser.add_argument("--max-private-growth-mb", type=float, default=512.0)
    parser.add_argument("--max-cuda-allocated-growth-mb", type=float, default=128.0)
    parser.add_argument("--max-cuda-reserved-growth-mb", type=float, default=128.0)
    parser.add_argument(
        "--max-cuda-reserved-tail-slope-bytes-per-request",
        type=float,
        default=1048576.0,
    )
    parser.add_argument(
        "--gpu-pid-telemetry-policy",
        choices=("required", "allow_unsupported"),
        default="required",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for value in (
        args.max_private_growth_mb,
        args.max_cuda_allocated_growth_mb,
        args.max_cuda_reserved_growth_mb,
        args.max_cuda_reserved_tail_slope_bytes_per_request,
    ):
        if value <= 0:
            parser.error("memory limits must be positive")

    raw = args.input.read_bytes()
    report = json.loads(raw)
    if not isinstance(report, dict):
        raise RuntimeError("release-soak report must be a JSON object")
    results = _list_field(report, "requests")
    snapshots = _list_field(report, "memory_snapshots")
    worker_metrics = _list_field(report, "worker_metrics")
    config = report.get("config")
    if not isinstance(config, dict):
        raise RuntimeError("release-soak report is missing config")
    expected = _expected_context(
        config,
        schedule=args.schedule,
        seed_manifest=args.seed_manifest,
    )
    expected_requests = _positive_int(config, "requests")
    expected_cache_entries = _positive_int(config, "expected_prefill_cache_entries")
    cancellations_per_category = _positive_int(config, "cancellations_per_category")
    max_rss_growth_mb = _positive_number(config, "max_rss_growth_mb")
    expected_cancellations = cancellations_per_category * len(expected["labels"])
    validation = _validate_release_soak(
        results,
        snapshots,
        worker_metrics,
        expected_cache_entries=expected_cache_entries,
        expected_requests=expected_requests,
        expected_cancellations=expected_cancellations,
        expected_labels=set(expected["labels"]),
        cancellations_per_stage=cancellations_per_category // 3,
        max_rss_growth_mb=max_rss_growth_mb,
        max_private_growth_mb=args.max_private_growth_mb,
        max_cuda_allocated_growth_mb=args.max_cuda_allocated_growth_mb,
        max_cuda_reserved_growth_mb=args.max_cuda_reserved_growth_mb,
        max_cuda_reserved_tail_slope_bytes_per_request=(
            args.max_cuda_reserved_tail_slope_bytes_per_request
        ),
        gpu_pid_telemetry_policy=args.gpu_pid_telemetry_policy,
    )
    output = {
        "artifact_schema_version": 2,
        "input_path": str(args.input),
        "input_sha256": sha256(raw).hexdigest(),
        "validator_schema_version": _VALIDATOR_SCHEMA_VERSION,
        "validator_commit": _validator_commit(),
        "schedule": expected["schedule"],
        "seed_manifest": expected["seed_manifest"],
        "expected_labels": expected["labels"],
        "memory_limits": {
            "max_private_growth_mb": args.max_private_growth_mb,
            "max_cuda_allocated_growth_mb": args.max_cuda_allocated_growth_mb,
            "max_cuda_reserved_growth_mb": args.max_cuda_reserved_growth_mb,
            "max_cuda_reserved_tail_slope_bytes_per_request": (
                args.max_cuda_reserved_tail_slope_bytes_per_request
            ),
            "gpu_pid_telemetry_policy": args.gpu_pid_telemetry_policy,
        },
        "acceptance_pass": not validation["failures"],
        "validation": validation,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, sort_keys=True), encoding="utf-8")
    print(json.dumps(output, sort_keys=True))
    return 0 if output["acceptance_pass"] else 1


def _expected_context(
    config: dict[str, object],
    *,
    schedule: Path,
    seed_manifest: Path,
) -> dict[str, object]:
    """Load immutable expected coverage from the declared input manifests."""

    schedule = schedule.resolve()
    seed_manifest = seed_manifest.resolve()
    if not schedule.is_file() or not seed_manifest.is_file():
        raise RuntimeError("schedule and seed manifest must both be files")
    _require_config_path(config, "schedule", schedule)
    _require_config_path(config, "seed_manifest", seed_manifest)
    labels = sorted(_shapes_by_label(schedule))
    if not labels:
        raise RuntimeError("schedule manifest contains no labels")
    required_labels = config.get("required_label", [])
    if not isinstance(required_labels, list) or not all(
        isinstance(label, str) for label in required_labels
    ):
        raise RuntimeError("release-soak config has invalid required_label")
    missing_required = sorted(set(required_labels).difference(labels))
    if missing_required:
        raise RuntimeError(
            "schedule manifest is missing configured labels: "
            + ", ".join(missing_required)
        )
    return {
        "labels": labels,
        "schedule": _manifest_provenance(schedule),
        "seed_manifest": _manifest_provenance(seed_manifest),
    }


def _require_config_path(
    config: dict[str, object],
    key: str,
    expected: Path,
) -> None:
    value = config.get(key)
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"release-soak config has invalid {key}")
    configured = Path(value)
    if not configured.is_absolute():
        configured = _REPO_ROOT / configured
    if configured.resolve() != expected:
        raise RuntimeError(f"{key} does not match the raw release-soak config")


def _manifest_provenance(path: Path) -> dict[str, str]:
    try:
        display_path = str(path.relative_to(_REPO_ROOT))
    except ValueError:
        display_path = str(path)
    return {
        "path": display_path,
        "sha256": sha256(path.read_bytes()).hexdigest(),
    }


def _validator_commit() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=_REPO_ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return None


def _list_field(report: dict[str, object], key: str) -> list[dict[str, object]]:
    value = report.get(key)
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise RuntimeError(f"release-soak report has invalid {key}")
    return value


def _positive_int(config: dict[str, object], key: str) -> int:
    value = config.get(key)
    if not isinstance(value, int) or value <= 0:
        raise RuntimeError(f"release-soak config has invalid {key}")
    return value


def _positive_number(config: dict[str, object], key: str) -> float:
    value = config.get(key)
    if not isinstance(value, (int, float)) or value <= 0:
        raise RuntimeError(f"release-soak config has invalid {key}")
    return float(value)


if __name__ == "__main__":
    raise SystemExit(main())
