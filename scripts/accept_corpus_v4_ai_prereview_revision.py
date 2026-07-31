"""Build, verify, and atomically publish a corpus-v4 adjudication revision."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any

try:
    from scripts.audit_corpus_repetition import _audit, _record_id_set_sha256
    from scripts.validate_corpus_v4_batches import _validate
except ModuleNotFoundError:
    from audit_corpus_repetition import _audit, _record_id_set_sha256
    from validate_corpus_v4_batches import _validate

_BATCH_IDS = tuple(f"v4-b{index:02d}" for index in range(1, 11))
_MATERIALIZATION_SCHEMA_VERSION = 1
_ACCEPTANCE_SCHEMA_VERSION = 2
_REJECTION_SCHEMA_VERSION = 1
_MATERIALIZATION_FIELDS = {
    "corpus_v4_human_adjudication_revision_schema_version",
    "base_candidate_sha256",
    "base_candidate_record_id_set_sha256",
    "triage_manifest_sha256",
    "targeted_review_form_sha256",
    "targeted_ai_prereview_sha256",
    "general_review_form_sha256",
    "general_ai_prereview_sha256",
    "ai_review_provenance_sha256",
    "targeted_adjudication_sha256",
    "general_adjudication_sha256",
    "ai_review_provenance",
    "targeted_flagged",
    "targeted_replaced",
    "targeted_kept",
    "general_flagged",
    "general_replaced",
    "general_kept",
    "overlap_count",
    "unique_candidate_count",
    "unique_revised_count",
    "record_count",
    "output_sha256",
    "output_record_id_set_sha256",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    _add_builder_arguments(parser)
    parser.add_argument("--corpus-id", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error("--output-dir must not already exist")
    pending_dir = _create_pending_dir(args.output_dir)
    try:
        acceptance = _build_acceptance(args, pending_dir)
    except Exception as error:
        rejected_dir = _reject_exception(pending_dir, args.output_dir, error)
        print(
            json.dumps(
                {
                    "accepted": False,
                    "rejected_output_dir": str(rejected_dir),
                    "error": str(error),
                },
                sort_keys=True,
            )
        )
        return 1
    _write_object(pending_dir / "acceptance-report.json", acceptance)
    if acceptance["acceptance_pass"]:
        _promote_directory(pending_dir, args.output_dir)
        print(json.dumps(acceptance, sort_keys=True))
        return 0
    rejected_dir = _reject_directory(pending_dir, args.output_dir)
    print(json.dumps(acceptance, sort_keys=True))
    print(json.dumps({"rejected_output_dir": str(rejected_dir)}, sort_keys=True))
    return 1


def _add_builder_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--base-candidate", type=Path, required=True)
    parser.add_argument("--triage-manifest", type=Path, required=True)
    parser.add_argument("--targeted-review-form", type=Path, required=True)
    parser.add_argument("--targeted-ai-prereview", type=Path, required=True)
    parser.add_argument("--general-review-form", type=Path, required=True)
    parser.add_argument("--general-ai-prereview", type=Path, required=True)
    parser.add_argument("--ai-review-provenance", type=Path, required=True)
    parser.add_argument("--targeted-adjudication", type=Path, required=True)
    parser.add_argument("--general-adjudication", type=Path, required=True)


def _build_acceptance(args: argparse.Namespace, directory: Path) -> dict[str, object]:
    candidate_path = directory / "candidate.jsonl"
    materialization_report_path = directory / "materialization-report.json"
    _run_builder(args, candidate_path, materialization_report_path)
    candidate_bytes = candidate_path.read_bytes()
    records = _load_records(candidate_path)
    materialization = _load_object(materialization_report_path)
    provenance = _verify_materialization_report(
        materialization,
        args,
        candidate_bytes,
        records,
    )
    batch_paths = _write_batches(directory / "candidate-batches", records)
    validation = _validate(batch_paths, len(_BATCH_IDS))
    repetition = _audit(
        records,
        source_records_sha256=provenance["candidate_sha256"],
        source_record_id_set_sha256=provenance["candidate_record_id_set_sha256"],
        corpus_id=args.corpus_id,
    )
    validation_path = directory / "full-batch-validation.json"
    repetition_path = directory / "repetition-audit.json"
    _write_object(validation_path, validation)
    _write_object(repetition_path, repetition)
    acceptance = _acceptance_report(materialization, validation, repetition, provenance)
    acceptance["materialization_report_sha256"] = _sha256(
        materialization_report_path.read_bytes()
    )
    acceptance["full_batch_validation_sha256"] = _sha256(validation_path.read_bytes())
    acceptance["repetition_audit_sha256"] = _sha256(repetition_path.read_bytes())
    return acceptance


def _run_builder(
    args: argparse.Namespace, candidate_path: Path, report_path: Path
) -> None:
    builder = Path(__file__).with_name("build_corpus_v4_ai_prereview_revision.py")
    command = [sys.executable, str(builder)]
    for name in (
        "base_candidate",
        "triage_manifest",
        "targeted_review_form",
        "targeted_ai_prereview",
        "general_review_form",
        "general_ai_prereview",
        "ai_review_provenance",
        "targeted_adjudication",
        "general_adjudication",
    ):
        command.extend((f"--{name.replace('_', '-')}", str(getattr(args, name))))
    command.extend(("--output", str(candidate_path), "--report", str(report_path)))
    subprocess.run(command, check=True, stdout=subprocess.DEVNULL)


def _verify_materialization_report(
    materialization: dict[str, Any],
    args: argparse.Namespace,
    candidate_bytes: bytes,
    records: list[dict[str, Any]],
) -> dict[str, str]:
    if set(materialization) != _MATERIALIZATION_FIELDS:
        raise RuntimeError("materialization report schema is invalid")
    if (
        materialization.get("corpus_v4_human_adjudication_revision_schema_version")
        != _MATERIALIZATION_SCHEMA_VERSION
    ):
        raise RuntimeError("materialization report schema is unsupported")
    provenance = _input_provenance(args, candidate_bytes, records)
    expected = {
        "base_candidate_sha256": provenance["base_candidate_sha256"],
        "base_candidate_record_id_set_sha256": provenance[
            "base_candidate_record_id_set_sha256"
        ],
        "triage_manifest_sha256": provenance["triage_manifest_sha256"],
        "targeted_review_form_sha256": provenance["targeted_review_form_sha256"],
        "targeted_ai_prereview_sha256": provenance["targeted_ai_prereview_sha256"],
        "general_review_form_sha256": provenance["general_review_form_sha256"],
        "general_ai_prereview_sha256": provenance["general_ai_prereview_sha256"],
        "ai_review_provenance_sha256": provenance["ai_review_provenance_sha256"],
        "targeted_adjudication_sha256": provenance["targeted_adjudication_sha256"],
        "general_adjudication_sha256": provenance["general_adjudication_sha256"],
        "output_sha256": provenance["candidate_sha256"],
        "output_record_id_set_sha256": provenance["candidate_record_id_set_sha256"],
        "record_count": len(records),
    }
    for field, value in expected.items():
        if materialization.get(field) != value:
            raise RuntimeError(f"materialization report {field} does not match")
    expected_ai_review_provenance = {
        "status": "supplied",
        "details": _load_object(args.ai_review_provenance),
    }
    if materialization.get("ai_review_provenance") != expected_ai_review_provenance:
        raise RuntimeError("materialization report AI review provenance does not match")
    _validate_materialization_counts(materialization, args.triage_manifest)
    return provenance


def _input_provenance(
    args: argparse.Namespace,
    candidate_bytes: bytes,
    records: list[dict[str, Any]],
) -> dict[str, str]:
    base_bytes = args.base_candidate.read_bytes()
    base_records = _load_records(args.base_candidate)
    return {
        "corpus_id": args.corpus_id,
        "candidate_sha256": _sha256(candidate_bytes),
        "candidate_record_id_set_sha256": _record_id_set_sha256(records),
        "base_candidate_sha256": _sha256(base_bytes),
        "base_candidate_record_id_set_sha256": _record_id_set_sha256(base_records),
        "triage_manifest_sha256": _sha256(args.triage_manifest.read_bytes()),
        "targeted_review_form_sha256": _sha256(args.targeted_review_form.read_bytes()),
        "targeted_ai_prereview_sha256": _sha256(
            args.targeted_ai_prereview.read_bytes()
        ),
        "general_review_form_sha256": _sha256(args.general_review_form.read_bytes()),
        "general_ai_prereview_sha256": _sha256(args.general_ai_prereview.read_bytes()),
        "ai_review_provenance_sha256": _sha256(args.ai_review_provenance.read_bytes()),
        "targeted_adjudication_sha256": _sha256(
            args.targeted_adjudication.read_bytes()
        ),
        "general_adjudication_sha256": _sha256(args.general_adjudication.read_bytes()),
    }


def _validate_materialization_counts(
    materialization: dict[str, Any], triage_manifest_path: Path
) -> None:
    triage_manifest = _load_object(triage_manifest_path)
    targeted_ids = _triage_candidate_ids(
        triage_manifest.get("targeted_repair_candidates"), "record_id", "targeted"
    )
    general_ids = _triage_candidate_ids(
        triage_manifest.get("general_repair_candidates"), "label", "general"
    )
    expected_counts = {
        "targeted_flagged": len(targeted_ids),
        "general_flagged": len(general_ids),
        "overlap_count": len(targeted_ids.intersection(general_ids)),
        "unique_candidate_count": len(targeted_ids.union(general_ids)),
        "record_count": 2000,
    }
    for field, value in expected_counts.items():
        if materialization.get(field) != value:
            raise RuntimeError(f"materialization report {field} is invalid")
    for scope in ("targeted", "general"):
        flagged = materialization[f"{scope}_flagged"]
        replaced = materialization[f"{scope}_replaced"]
        kept = materialization[f"{scope}_kept"]
        if not all(isinstance(value, int) and value >= 0 for value in (replaced, kept)):
            raise RuntimeError(
                f"materialization report {scope} decision counts are invalid"
            )
        if replaced + kept != flagged:
            raise RuntimeError(
                f"materialization report {scope} decision counts mismatch"
            )
    unique_revised = materialization.get("unique_revised_count")
    total_replaced = (
        materialization["targeted_replaced"] + materialization["general_replaced"]
    )
    if (
        not isinstance(unique_revised, int)
        or unique_revised != total_replaced
        or unique_revised > len(targeted_ids.union(general_ids))
    ):
        raise RuntimeError("materialization report unique revised count is invalid")


def _triage_candidate_ids(rows: object, id_field: str, scope: str) -> set[str]:
    if not isinstance(rows, list):
        raise RuntimeError(f"triage manifest {scope} candidates are invalid")
    result: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise RuntimeError(f"triage manifest {scope} candidate is invalid")
        record_id = row.get(id_field)
        if not isinstance(record_id, str) or not record_id or record_id in result:
            raise RuntimeError(f"triage manifest {scope} candidate ID is invalid")
        result.add(record_id)
    return result


def _write_batches(directory: Path, records: list[dict[str, Any]]) -> list[Path]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        batch_id = record.get("batch_id")
        if not isinstance(batch_id, str):
            raise RuntimeError("materialized record has an invalid batch_id")
        grouped[batch_id].append(record)
    if set(grouped) != set(_BATCH_IDS):
        raise RuntimeError("materialized corpus does not contain the expected batches")
    paths = []
    for batch_id in _BATCH_IDS:
        path = directory / f"{batch_id}.jsonl"
        _write_jsonl(path, grouped[batch_id])
        paths.append(path)
    return paths


def _acceptance_report(
    materialization: dict[str, Any],
    validation: dict[str, Any],
    repetition: dict[str, Any],
    provenance: dict[str, str],
) -> dict[str, object]:
    materialization_pass = True
    corpus_validation_pass = validation.get("passed") is True
    repetition_pass = repetition.get("passed") is True
    return {
        "corpus_v4_human_adjudication_acceptance_schema_version": (
            _ACCEPTANCE_SCHEMA_VERSION
        ),
        "corpus_id": provenance["corpus_id"],
        "candidate_sha256": provenance["candidate_sha256"],
        "candidate_record_id_set_sha256": provenance["candidate_record_id_set_sha256"],
        "base_candidate_sha256": provenance["base_candidate_sha256"],
        "base_candidate_record_id_set_sha256": provenance[
            "base_candidate_record_id_set_sha256"
        ],
        "triage_manifest_sha256": provenance["triage_manifest_sha256"],
        "targeted_review_form_sha256": provenance["targeted_review_form_sha256"],
        "targeted_ai_prereview_sha256": provenance["targeted_ai_prereview_sha256"],
        "general_review_form_sha256": provenance["general_review_form_sha256"],
        "general_ai_prereview_sha256": provenance["general_ai_prereview_sha256"],
        "ai_review_provenance_sha256": provenance["ai_review_provenance_sha256"],
        "targeted_adjudication_sha256": provenance["targeted_adjudication_sha256"],
        "general_adjudication_sha256": provenance["general_adjudication_sha256"],
        "builder_schema_version": materialization[
            "corpus_v4_human_adjudication_revision_schema_version"
        ],
        "validator_schema_version": validation.get(
            "corpus_v4_batch_validation_schema_version"
        ),
        "repetition_audit_schema_version": repetition.get(
            "corpus_repetition_audit_schema_version"
        ),
        "materialization_pass": materialization_pass,
        "corpus_validation_pass": corpus_validation_pass,
        "repetition_pass": repetition_pass,
        "acceptance_pass": (
            materialization_pass and corpus_validation_pass and repetition_pass
        ),
    }


def _create_pending_dir(output_dir: Path) -> Path:
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    return Path(
        tempfile.mkdtemp(
            prefix=f".{output_dir.name}.pending-",
            dir=output_dir.parent,
        )
    )


def _reject_exception(pending_dir: Path, output_dir: Path, error: Exception) -> Path:
    _write_object(
        pending_dir / "rejection-report.json",
        {
            "corpus_v4_human_adjudication_rejection_schema_version": (
                _REJECTION_SCHEMA_VERSION
            ),
            "accepted": False,
            "error_type": type(error).__name__,
            "message": str(error),
        },
    )
    return _reject_directory(pending_dir, output_dir)


def _reject_directory(pending_dir: Path, output_dir: Path) -> Path:
    rejected_dir = output_dir.with_name(
        f"{output_dir.name}.rejected-{uuid.uuid4().hex}"
    )
    _promote_directory(pending_dir, rejected_dir)
    return rejected_dir


def _promote_directory(source: Path, destination: Path) -> None:
    if destination.exists():
        raise RuntimeError(f"output directory already exists: {destination}")
    os.replace(source, destination)


def _load_records(path: Path) -> list[dict[str, Any]]:
    return _load_jsonl(path.read_bytes(), "materialized candidate")


def _load_jsonl(value: bytes, name: str) -> list[dict[str, Any]]:
    rows = []
    for line_number, line in enumerate(value.decode("utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise RuntimeError(f"{name} line {line_number} is not an object")
        rows.append(row)
    if not rows:
        raise RuntimeError(f"{name} contains no records")
    return rows


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"{path} is not an object")
    return value


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    _write_bytes(
        path,
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows
        ).encode("utf-8"),
    )


def _write_object(path: Path, value: dict[str, object]) -> None:
    _write_bytes(
        path,
        (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        ),
    )


def _write_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(value)
        os.replace(temporary_name, path)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
