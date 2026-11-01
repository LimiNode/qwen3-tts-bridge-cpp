"""Validate the tracked canonical acceptance receipts and their index."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any


HEX64 = re.compile(r"^[0-9a-f]{64}$")
COMMIT = re.compile(r"^[0-9a-f]{7,40}$")
RECEIPT_REQUIRED = {
    "schema_version",
    "acceptance_id",
    "recorded_at",
    "model_family",
    "backend",
    "bridge_commit",
    "model_revision",
    "runtime_revision",
    "hardware",
    "artifact_root",
    "artifacts",
    "mechanical",
    "human_listening",
    "release_status",
}
MECHANICAL_FIELDS = {"model_load", "pcm", "natural_eos", "persistent_repeat", "restart"}
LISTENING_FIELDS = {
    "intelligibility",
    "voice_or_instruction",
    "artifacts",
    "final_tail",
    "sequential_contamination",
}
MECHANICAL_VALUES = {"pass", "fail", "not_run"}
LISTENING_VALUES = {"pass", "partial", "not_assessed", "fail"}


class ValidationError(ValueError):
    """A receipt violates the repository evidence contract."""


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"cannot read JSON {path}: {exc}") from exc


def require_keys(value: dict[str, Any], required: set[str], label: str) -> None:
    missing = required - value.keys()
    if missing:
        raise ValidationError(f"{label}: missing required fields: {sorted(missing)}")


def check_date(value: Any, label: str) -> None:
    if not isinstance(value, str):
        raise ValidationError(f"{label}: expected ISO date")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError(f"{label}: invalid ISO date {value!r}") from exc


def validate_receipt(path: Path, root: Path, check_artifacts: bool) -> dict[str, Any]:
    receipt = load_json(path)
    if not isinstance(receipt, dict):
        raise ValidationError(f"{path}: top-level value must be an object")
    require_keys(receipt, RECEIPT_REQUIRED, str(path))
    if receipt["schema_version"] != 1:
        raise ValidationError(f"{path}: unsupported schema_version")
    if not isinstance(receipt["acceptance_id"], str) or not re.fullmatch(
        r"[a-z0-9][a-z0-9-]+", receipt["acceptance_id"]
    ):
        raise ValidationError(f"{path}: invalid acceptance_id")
    check_date(receipt["recorded_at"], f"{path}: recorded_at")
    if not isinstance(receipt["bridge_commit"], str) or not COMMIT.fullmatch(
        receipt["bridge_commit"]
    ):
        raise ValidationError(f"{path}: invalid bridge_commit")
    if not isinstance(receipt["runtime_revision"], dict) or not receipt["runtime_revision"]:
        raise ValidationError(f"{path}: runtime_revision must be a non-empty object")
    if not isinstance(receipt["artifact_root"], str) or not re.fullmatch(
        r"\.tmp/base-acceptance/[a-z0-9][a-z0-9-]+", receipt["artifact_root"]
    ):
        raise ValidationError(f"{path}: artifact_root must use .tmp/base-acceptance/<run-id>")

    mechanical = receipt["mechanical"]
    if not isinstance(mechanical, dict):
        raise ValidationError(f"{path}: mechanical must be an object")
    require_keys(mechanical, MECHANICAL_FIELDS, f"{path}: mechanical")
    if any(value not in MECHANICAL_VALUES for value in mechanical.values()):
        raise ValidationError(f"{path}: invalid mechanical status")

    listening = receipt["human_listening"]
    if not isinstance(listening, dict):
        raise ValidationError(f"{path}: human_listening must be an object")
    require_keys(
        listening,
        {"status", "observer", "recorded_at", "scope", "criteria", "notes"},
        f"{path}: human_listening",
    )
    if listening["status"] not in {"pass", "partial_pass", "not_run", "fail"}:
        raise ValidationError(f"{path}: invalid human_listening.status")
    check_date(listening["recorded_at"], f"{path}: human_listening.recorded_at")
    criteria = listening["criteria"]
    if not isinstance(criteria, dict):
        raise ValidationError(f"{path}: human_listening.criteria must be an object")
    require_keys(criteria, LISTENING_FIELDS, f"{path}: human_listening.criteria")
    if any(value not in LISTENING_VALUES for value in criteria.values()):
        raise ValidationError(f"{path}: invalid human listening criterion")

    artifacts = receipt["artifacts"]
    if not isinstance(artifacts, list) or not artifacts:
        raise ValidationError(f"{path}: artifacts must be a non-empty array")
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            raise ValidationError(f"{path}: artifact must be an object")
        require_keys(artifact, {"path", "kind", "bytes", "sha256"}, f"{path}: artifact")
        artifact_path = artifact["path"]
        if not isinstance(artifact_path, str) or not artifact_path.startswith(
            ".tmp/base-acceptance/"
        ):
            raise ValidationError(f"{path}: artifact path is not repository-local: {artifact_path!r}")
        if not isinstance(artifact["bytes"], int) or artifact["bytes"] < 0:
            raise ValidationError(f"{path}: invalid artifact byte count")
        if not isinstance(artifact["sha256"], str) or not HEX64.fullmatch(artifact["sha256"]):
            raise ValidationError(f"{path}: invalid artifact sha256")
        if check_artifacts:
            local_path = root / Path(artifact_path)
            if not local_path.is_file():
                raise ValidationError(f"{path}: artifact is missing: {local_path}")
            if local_path.stat().st_size != artifact["bytes"]:
                raise ValidationError(f"{path}: artifact size mismatch: {local_path}")
            digest = hashlib.sha256(local_path.read_bytes()).hexdigest()
            if digest != artifact["sha256"]:
                raise ValidationError(f"{path}: artifact SHA-256 mismatch: {local_path}")

    if receipt["release_status"] not in {"accepted", "conditional", "blocked"}:
        raise ValidationError(f"{path}: invalid release_status")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check-artifacts",
        action="store_true",
        help="also verify local .tmp payload files, sizes, and SHA-256 values",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    index_path = root / "docs/reports/acceptance-index.json"
    index = load_json(index_path)
    if index.get("schema_version") != 1:
        raise ValidationError(f"{index_path}: unsupported schema_version")
    entries = index.get("canonical_receipts")
    if not isinstance(entries, list) or not entries:
        raise ValidationError(f"{index_path}: canonical_receipts must be non-empty")

    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("receipt"), str):
            raise ValidationError(f"{index_path}: malformed canonical receipt entry")
        receipt_path = root / entry["receipt"]
        receipt = validate_receipt(receipt_path, root, args.check_artifacts)
        if receipt["acceptance_id"] != entry.get("acceptance_id"):
            raise ValidationError(f"{index_path}: acceptance_id does not match {receipt_path}")
        if receipt["human_listening"]["status"] != entry.get("human_listening"):
            raise ValidationError(f"{index_path}: listening status does not match {receipt_path}")
        if receipt["release_status"] != entry.get("release_status"):
            raise ValidationError(f"{index_path}: release status does not match {receipt_path}")

    for legacy in index.get("legacy_reference_reports", []):
        path = legacy.get("path") if isinstance(legacy, dict) else None
        if not isinstance(path, str) or not (root / path).is_file():
            raise ValidationError(f"{index_path}: missing legacy reference report: {path!r}")

    print(f"validated {len(entries)} canonical acceptance receipts")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValidationError as exc:
        print(f"acceptance receipt validation failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
