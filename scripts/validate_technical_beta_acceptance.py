"""Fail-closed schema validation for technical-beta acceptance evidence."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


RELOCATION_GATE_NAMES = (
    "package_tree_pre_smoke",
    "voice_assets_pre_smoke",
    "native_closure",
    "custom_voice_doctor_pre_smoke",
    "base_doctor_pre_smoke",
    "custom_voice_natural_eos",
    "base_natural_eos",
    "custom_voice_doctor_post_smoke",
    "base_doctor_post_smoke",
    "no_bytecode",
    "package_tree_post_smoke",
    "voice_assets_post_smoke",
)

FAULT_CASE_NAMES = (
    "replace_success",
    "replace_before_backup",
    "replace_after_backup",
    "replace_after_swap",
    "replace_published_validation_failure",
    "replace_before_backup_cleanup",
    "first_publish_after_swap",
    "first_publish_validation_failure",
)


def _reject_duplicate_keys(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON object key: {key}")
        value[key] = item
    return value


def _read_report(path: Path) -> Mapping[str, Any]:
    with path.open(encoding="utf-8") as stream:
        value = json.load(stream, object_pairs_hook=_reject_duplicate_keys)
    if not isinstance(value, Mapping):
        raise ValueError("report root must be a JSON object")
    return value


def _require_exact_true_gates(
    report: Mapping[str, Any],
    expected_names: Sequence[str],
) -> None:
    gates = report.get("required_gates")
    if not isinstance(gates, Mapping):
        raise ValueError("required_gates must be a JSON object")
    if tuple(gates) != tuple(expected_names):
        missing = sorted(set(expected_names) - set(gates))
        unknown = sorted(set(gates) - set(expected_names))
        raise ValueError(
            f"required_gates must contain the expected ordered keys; "
            f"missing={missing}, unknown={unknown}"
        )
    failed = [name for name in expected_names if gates[name] is not True]
    if failed:
        raise ValueError(f"required_gates contains non-passing gates: {failed}")


def _require_digest(value: Any, name: str) -> None:
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError(f"{name} must be a SHA-256 hex string")
    try:
        int(value, 16)
    except ValueError as error:
        raise ValueError(f"{name} must be a SHA-256 hex string") from error


def validate_relocation(report: Mapping[str, Any]) -> None:
    if report.get("schema_version") != 4:
        raise ValueError("relocation report schema_version must be 4")
    if report.get("acceptance_pass") is not True:
        raise ValueError("relocation report acceptance_pass must be true")
    _require_exact_true_gates(report, RELOCATION_GATE_NAMES)
    package = report.get("package")
    if not isinstance(package, Mapping):
        raise ValueError("relocation report package must be a JSON object")
    _require_digest(package.get("verified_manifest_digest"), "verified_manifest_digest")
    if package.get("verified_manifest_digest_algorithm") != "sha256(package-tree-manifest)":
        raise ValueError("unexpected verified_manifest_digest_algorithm")


def validate_fault_matrix(report: Mapping[str, Any]) -> None:
    if report.get("schema_version") != 2:
        raise ValueError("fault matrix schema_version must be 2")
    if report.get("acceptance_pass") is not True:
        raise ValueError("fault matrix acceptance_pass must be true")
    cases = report.get("cases")
    if not isinstance(cases, list):
        raise ValueError("fault matrix cases must be an array")
    names = [case.get("name") for case in cases if isinstance(case, Mapping)]
    if len(names) != len(cases) or tuple(names) != FAULT_CASE_NAMES:
        raise ValueError("fault matrix must contain the expected ordered case names")
    failed = [case["name"] for case in cases if case.get("pass") is not True]
    if failed:
        raise ValueError(f"fault matrix contains failed cases: {failed}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", choices=("relocation", "fault"), required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    try:
        report = _read_report(args.report)
        if args.kind == "relocation":
            validate_relocation(report)
        else:
            validate_fault_matrix(report)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"technical-beta acceptance validation failed: {error}", file=sys.stderr)
        return 1

    print(f"technical-beta {args.kind} evidence schema passed: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
