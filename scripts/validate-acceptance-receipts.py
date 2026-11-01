"""Validate canonical acceptance receipts without model or CUDA dependencies."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any


HEX64 = re.compile(r"^[0-9a-f]{64}$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")
ID = re.compile(r"^[a-z0-9][a-z0-9-]+$")
MODEL_FAMILIES = {"Base", "VoiceDesign", "RU-stress", "CustomVoice", "other"}
BACKENDS = {"faster", "native", "upstream", "other"}
MECHANICAL_FIELDS = {"model_load", "pcm", "natural_eos", "persistent_repeat", "restart"}
MECHANICAL_VALUES = {"pass", "fail", "not_run"}
LISTENING_FIELDS = {"intelligibility", "voice_or_instruction", "artifacts", "final_tail", "sequential_contamination"}
LISTENING_VALUES = {"pass", "partial", "not_assessed", "fail"}
ARTIFACT_KINDS = {"wav", "json", "log", "manifest", "other"}


class ValidationError(ValueError):
    """A receipt violates the repository evidence contract."""


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"cannot read JSON {path}: {exc}") from exc


def object_keys(value: dict[str, Any], required: set[str], allowed: set[str], label: str) -> None:
    missing = required - value.keys()
    extra = set(value) - allowed
    if missing:
        raise ValidationError(f"{label}: missing required fields: {sorted(missing)}")
    if extra:
        raise ValidationError(f"{label}: unknown fields: {sorted(extra)}")


def check_date(value: Any, label: str) -> None:
    if not isinstance(value, str):
        raise ValidationError(f"{label}: expected ISO date")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError(f"{label}: invalid ISO date {value!r}") from exc


def check_string(value: Any, label: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValidationError(f"{label}: expected non-empty string")


def validate_artifact_path(value: Any, receipt_root: str, root: Path, label: str) -> Path:
    if not isinstance(value, str) or "\\" in value:
        raise ValidationError(f"{label}: path must use repository POSIX separators")
    try:
        relative = PurePosixPath(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{label}: invalid path") from exc
    if str(relative) != value:
        raise ValidationError(f"{label}: non-canonical path")
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise ValidationError(f"{label}: path traversal or non-canonical path")
    prefix = PurePosixPath(receipt_root)
    if relative != prefix and prefix not in relative.parents:
        raise ValidationError(f"{label}: path is outside artifact_root")
    if not value.startswith(".tmp/base-acceptance/"):
        raise ValidationError(f"{label}: path is not repository-local")
    repository_root = root.resolve()
    payload_root = (repository_root / ".tmp/base-acceptance").resolve()
    resolved_artifact_root = (repository_root / Path(*prefix.parts)).resolve()
    resolved_path = (repository_root / Path(*relative.parts)).resolve()
    for candidate, candidate_label in ((resolved_artifact_root, "artifact_root"), (resolved_path, "artifact")):
        try:
            candidate.relative_to(payload_root)
        except ValueError as exc:
            raise ValidationError(f"{label}: resolved {candidate_label} escapes .tmp/base-acceptance") from exc
    try:
        resolved_path.relative_to(resolved_artifact_root)
    except ValueError as exc:
        raise ValidationError(f"{label}: resolved path escapes artifact_root") from exc
    return resolved_path


def validate_receipt(path: Path, root: Path, check_artifacts: bool) -> dict[str, Any]:
    receipt = load_json(path)
    if not isinstance(receipt, dict):
        raise ValidationError(f"{path}: top-level value must be an object")
    required = {
        "schema_version", "acceptance_id", "recorded_at", "model_family", "backend",
        "bridge_commit", "model_revision", "runtime_revision", "hardware", "artifact_root",
        "artifacts", "mechanical", "human_listening", "release_status", "input_identity",
    }
    allowed = required | {"supersedes", "related_reports", "notes"}
    object_keys(receipt, required, allowed, str(path))
    if receipt["schema_version"] != 1:
        raise ValidationError(f"{path}: unsupported schema_version")
    if not isinstance(receipt["acceptance_id"], str) or not ID.fullmatch(receipt["acceptance_id"]):
        raise ValidationError(f"{path}: invalid acceptance_id")
    check_date(receipt["recorded_at"], f"{path}: recorded_at")
    if receipt["model_family"] not in MODEL_FAMILIES:
        raise ValidationError(f"{path}: invalid model_family")
    if receipt["backend"] not in BACKENDS:
        raise ValidationError(f"{path}: invalid backend")
    if not isinstance(receipt["bridge_commit"], str) or not COMMIT.fullmatch(receipt["bridge_commit"]):
        raise ValidationError(f"{path}: bridge_commit must be a full 40-character SHA-1")
    check_string(receipt["model_revision"], f"{path}: model_revision")
    runtime = receipt["runtime_revision"]
    if not isinstance(runtime, dict) or not runtime or any(not isinstance(k, str) or not isinstance(v, str) or not v for k, v in runtime.items()):
        raise ValidationError(f"{path}: runtime_revision must be a non-empty string map")

    hardware = receipt["hardware"]
    if not isinstance(hardware, dict):
        raise ValidationError(f"{path}: hardware must be an object")
    hardware_fields = {"gpu", "compute_capability", "driver", "cuda"}
    object_keys(hardware, hardware_fields, hardware_fields, f"{path}: hardware")
    for key in hardware_fields:
        check_string(hardware[key], f"{path}: hardware.{key}")

    artifact_root = receipt["artifact_root"]
    if not isinstance(artifact_root, str) or not re.fullmatch(r"\.tmp/base-acceptance/[a-z0-9][a-z0-9-]+", artifact_root):
        raise ValidationError(f"{path}: artifact_root must use .tmp/base-acceptance/<run-id>")

    identity = receipt["input_identity"]
    if not isinstance(identity, dict):
        raise ValidationError(f"{path}: input_identity must be an object")
    identity_required = {"status", "source"}
    identity_allowed = identity_required | {"text_utf8_sha256", "instruction_utf8_sha256", "corpus_sha256"}
    object_keys(identity, identity_required, identity_allowed, f"{path}: input_identity")
    if identity["status"] not in {"recorded", "not_recorded"}:
        raise ValidationError(f"{path}: invalid input_identity.status")
    check_string(identity["source"], f"{path}: input_identity.source")
    for key in identity_allowed - identity_required:
        if key in identity and (not isinstance(identity[key], str) or not HEX64.fullmatch(identity[key])):
            raise ValidationError(f"{path}: invalid input_identity.{key}")
    if identity["status"] == "recorded" and not any(key in identity for key in identity_allowed - identity_required):
        raise ValidationError(f"{path}: recorded input_identity must contain a hash")

    mechanical = receipt["mechanical"]
    if not isinstance(mechanical, dict):
        raise ValidationError(f"{path}: mechanical must be an object")
    object_keys(mechanical, MECHANICAL_FIELDS, MECHANICAL_FIELDS, f"{path}: mechanical")
    if any(value not in MECHANICAL_VALUES for value in mechanical.values()):
        raise ValidationError(f"{path}: invalid mechanical status")

    listening = receipt["human_listening"]
    if not isinstance(listening, dict):
        raise ValidationError(f"{path}: human_listening must be an object")
    listening_required = {"status", "observer", "recorded_at", "scope", "criteria", "notes"}
    object_keys(listening, listening_required, listening_required, f"{path}: human_listening")
    status = listening["status"]
    if status not in {"pass", "partial_pass", "not_run", "fail"}:
        raise ValidationError(f"{path}: invalid human_listening.status")
    check_string(listening["observer"], f"{path}: human_listening.observer")
    check_date(listening["recorded_at"], f"{path}: human_listening.recorded_at")
    check_string(listening["scope"], f"{path}: human_listening.scope")
    check_string(listening["notes"], f"{path}: human_listening.notes")
    criteria = listening["criteria"]
    if not isinstance(criteria, dict):
        raise ValidationError(f"{path}: human_listening.criteria must be an object")
    object_keys(criteria, LISTENING_FIELDS, LISTENING_FIELDS, f"{path}: human_listening.criteria")
    if any(value not in LISTENING_VALUES for value in criteria.values()):
        raise ValidationError(f"{path}: invalid human listening criterion")
    values = set(criteria.values())
    if status == "pass" and values != {"pass"}:
        raise ValidationError(f"{path}: pass requires every listening criterion to pass")
    if status == "partial_pass" and ("fail" in values or values == {"pass"} or not (values - {"pass"})):
        raise ValidationError(f"{path}: partial_pass must contain positive, non-failing evidence")
    if status == "not_run" and values != {"not_assessed"}:
        raise ValidationError(f"{path}: not_run cannot contain positive criteria")
    if status == "fail" and "fail" not in values:
        raise ValidationError(f"{path}: fail requires a failed criterion")

    artifacts = receipt["artifacts"]
    if not isinstance(artifacts, list) or not artifacts:
        raise ValidationError(f"{path}: artifacts must be a non-empty array")
    for index, artifact in enumerate(artifacts):
        label = f"{path}: artifacts[{index}]"
        if not isinstance(artifact, dict):
            raise ValidationError(f"{label}: must be an object")
        fields = {"path", "kind", "bytes", "sha256"}
        object_keys(artifact, fields, fields, label)
        local_path = validate_artifact_path(artifact["path"], artifact_root, root, f"{label}.path")
        if artifact["kind"] not in ARTIFACT_KINDS:
            raise ValidationError(f"{label}: invalid kind")
        if isinstance(artifact["bytes"], bool) or not isinstance(artifact["bytes"], int) or artifact["bytes"] < 0:
            raise ValidationError(f"{label}: invalid byte count")
        if not isinstance(artifact["sha256"], str) or not HEX64.fullmatch(artifact["sha256"]):
            raise ValidationError(f"{label}: invalid sha256")
        if check_artifacts:
            if not local_path.is_file():
                raise ValidationError(f"{label}: artifact is missing: {local_path}")
            if local_path.stat().st_size != artifact["bytes"]:
                raise ValidationError(f"{label}: artifact size mismatch: {local_path}")
            if hashlib.sha256(local_path.read_bytes()).hexdigest() != artifact["sha256"]:
                raise ValidationError(f"{label}: artifact SHA-256 mismatch: {local_path}")

    release = receipt["release_status"]
    if release not in {"accepted", "conditional", "blocked"}:
        raise ValidationError(f"{path}: invalid release_status")
    core_gates = {"model_load", "pcm", "natural_eos"}
    if release == "accepted" and (
        any(mechanical[key] != "pass" for key in core_gates) or status != "pass"
    ):
        raise ValidationError(f"{path}: accepted release cannot hide failed or incomplete gates")
    if "supersedes" in receipt and receipt["supersedes"] is not None:
        if not isinstance(receipt["supersedes"], list) or any(not isinstance(item, str) or not item for item in receipt["supersedes"]):
            raise ValidationError(f"{path}: supersedes must be null or a string array")
    if "related_reports" in receipt:
        if not isinstance(receipt["related_reports"], list) or any(not isinstance(item, str) or not item for item in receipt["related_reports"]):
            raise ValidationError(f"{path}: related_reports must be a string array")
    if "notes" in receipt and not isinstance(receipt["notes"], str):
        raise ValidationError(f"{path}: notes must be a string")
    return receipt


def validate_index(
    root: Path, check_artifacts: bool = False, index_path: Path | None = None
) -> int:
    index_path = index_path or (root / "docs/reports/acceptance-index.json")
    index = load_json(index_path)
    if not isinstance(index, dict):
        raise ValidationError(f"{index_path}: top-level value must be an object")
    object_keys(index, {"schema_version", "generated_at", "canonical_receipts", "legacy_reference_reports"}, {"schema_version", "generated_at", "canonical_receipts", "legacy_reference_reports"}, str(index_path))
    if index["schema_version"] != 1:
        raise ValidationError(f"{index_path}: unsupported schema_version")
    check_date(index["generated_at"], f"{index_path}: generated_at")
    entries = index["canonical_receipts"]
    if not isinstance(entries, list) or not entries:
        raise ValidationError(f"{index_path}: canonical_receipts must be non-empty")
    reports_root = (root / "docs/reports").resolve()
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValidationError(f"{index_path}: malformed canonical receipt entry")
        entry_fields = {"acceptance_id", "receipt", "model_family", "backend", "human_listening", "release_status"}
        object_keys(entry, entry_fields, entry_fields, f"{index_path}: entry")
        acceptance_id = entry["acceptance_id"]
        if not isinstance(acceptance_id, str) or not ID.fullmatch(acceptance_id):
            raise ValidationError(f"{index_path}: invalid entry acceptance_id")
        if acceptance_id in seen_ids:
            raise ValidationError(f"{index_path}: duplicate acceptance_id: {acceptance_id}")
        seen_ids.add(acceptance_id)
        receipt_name = entry["receipt"]
        expected_receipt = f"docs/reports/{acceptance_id}.json"
        if receipt_name != expected_receipt or not isinstance(receipt_name, str):
            raise ValidationError(f"{index_path}: receipt must be canonical: {expected_receipt}")
        try:
            receipt_relative = PurePosixPath(receipt_name)
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"{index_path}: invalid receipt path") from exc
        if str(receipt_relative) != receipt_name or receipt_relative.is_absolute() or ".." in receipt_relative.parts:
            raise ValidationError(f"{index_path}: non-canonical receipt path")
        if receipt_name in seen_paths:
            raise ValidationError(f"{index_path}: duplicate receipt path: {receipt_name}")
        seen_paths.add(receipt_name)
        receipt_path = (root / Path(*receipt_relative.parts)).resolve()
        try:
            receipt_path.relative_to(reports_root)
        except ValueError as exc:
            raise ValidationError(f"{index_path}: receipt escapes docs/reports") from exc
        receipt = validate_receipt(receipt_path, root, check_artifacts)
        for key in ("acceptance_id", "model_family", "backend"):
            if receipt[key] != entry[key]:
                raise ValidationError(f"{index_path}: {key} does not match {receipt_path}")
        if receipt["human_listening"]["status"] != entry["human_listening"] or receipt["release_status"] != entry["release_status"]:
            raise ValidationError(f"{index_path}: status does not match {receipt_path}")
    for legacy in index["legacy_reference_reports"]:
        legacy_path = legacy.get("path") if isinstance(legacy, dict) else None
        if (
            not isinstance(legacy, dict)
            or set(legacy) - {"path", "model_family", "status", "note"}
            or not isinstance(legacy_path, str)
        ):
            raise ValidationError(f"{index_path}: missing legacy reference report")
        try:
            legacy_relative = PurePosixPath(legacy_path)
            legacy_resolved = (root / Path(*legacy_relative.parts)).resolve()
            legacy_resolved.relative_to(reports_root)
        except (TypeError, ValueError):
            raise ValidationError(f"{index_path}: legacy report escapes docs/reports")
        if str(legacy_relative) != legacy_path or legacy_relative.is_absolute() or ".." in legacy_relative.parts or not legacy_resolved.is_file():
            raise ValidationError(f"{index_path}: missing legacy reference report: {legacy_path!r}")
    print(f"validated {len(entries)} canonical acceptance receipts")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-artifacts", action="store_true", help="verify local .tmp payloads")
    args = parser.parse_args()
    return validate_index(Path(__file__).resolve().parents[1], args.check_artifacts)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValidationError as exc:
        print(f"acceptance receipt validation failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
