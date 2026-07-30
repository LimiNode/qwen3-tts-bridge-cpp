"""Select the smallest deterministic corpus-v4 replacement set from an audit."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

try:
    from scripts.validate_corpus_v4_batches import _GLOBAL_QUOTAS
except ModuleNotFoundError:
    from validate_corpus_v4_batches import _GLOBAL_QUOTAS


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    audit_bytes = args.audit.read_bytes()
    audit = _load_object_bytes(audit_bytes, "audit")
    records = _load_records(args.records)
    repair_set = _build_repair_set(
        audit, records, hashlib.sha256(audit_bytes).hexdigest()
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(repair_set, ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    report = _report(repair_set)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


def _build_repair_set(
    audit: dict[str, object],
    records: list[dict[str, object]],
    audit_sha256: str,
    *,
    category_quotas: dict[str, int] | None = None,
) -> dict[str, Any]:
    records_by_id = _records_by_id(records)
    groups = _groups(audit, records_by_id)
    selected, reasons = _select_repetition_repairs(groups, records_by_id)
    rebalanced = _add_category_rebalance(
        selected,
        reasons,
        records_by_id,
        category_quotas or _GLOBAL_QUOTAS["category"],
    )
    entries = [
        _entry(record_id, records_by_id[record_id], reasons[record_id], rebalanced)
        for record_id in sorted(selected)
    ]
    return {
        "corpus_v4_repair_set_schema_version": 1,
        "source_audit_sha256": audit_sha256,
        "source_record_count": len(records),
        "implicated_record_count": len(
            {record_id for group in groups for record_id in group["occurrences"]}
        ),
        "selected_record_count": len(entries),
        "selection_policy": "greedy_overflow_then_category_quota",
        "records": entries,
    }


def _load_object_bytes(value: bytes, name: str) -> dict[str, object]:
    loaded = json.loads(value.decode("utf-8"))
    if not isinstance(loaded, dict):
        raise RuntimeError(f"{name} must be a JSON object")
    return loaded


def _load_records(path: Path) -> list[dict[str, object]]:
    records = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), 1
    ):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise RuntimeError(f"records line {line_number} is not an object")
        records.append(value)
    return records


def _records_by_id(records: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    result = {}
    for record in records:
        record_id = record.get("record_id")
        if not isinstance(record_id, str) or not record_id:
            raise RuntimeError("records must contain non-empty record_id values")
        if record_id in result:
            raise RuntimeError(f"duplicate record_id in records: {record_id}")
        result[record_id] = record
    return result


def _groups(
    audit: dict[str, object], records_by_id: dict[str, dict[str, object]]
) -> list[dict[str, Any]]:
    limits = audit.get("limits")
    violations = audit.get("violations")
    violation_records = audit.get("violation_records")
    if not isinstance(limits, dict):
        raise RuntimeError("audit has no limits object")
    if not isinstance(violations, dict) or not isinstance(violation_records, dict):
        raise RuntimeError("audit has no violation diagnostics")
    groups = []
    for kind in ("exact_text", "sentence", "closing_block"):
        groups.extend(
            _groups_for_kind(
                kind,
                violations.get(kind),
                violation_records.get(kind),
                limits.get(kind),
                records_by_id,
            )
        )
    ngram_violations = violations.get("ngrams")
    ngram_records = violation_records.get("ngrams")
    if not isinstance(ngram_violations, dict) or not isinstance(ngram_records, dict):
        raise RuntimeError("audit has no ngram diagnostics")
    for size in sorted(ngram_violations):
        groups.extend(
            _groups_for_kind(
                f"ngram_{size}",
                ngram_violations.get(size),
                ngram_records.get(size),
                limits.get(size),
                records_by_id,
            )
        )
    return groups


def _groups_for_kind(
    kind: str,
    violations: object,
    occurrence_map: object,
    limit: object,
    records_by_id: dict[str, dict[str, object]],
) -> list[dict[str, Any]]:
    if not isinstance(violations, dict) or not isinstance(occurrence_map, dict):
        raise RuntimeError(f"audit {kind} diagnostics are invalid")
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
        raise RuntimeError(f"audit {kind} limit is invalid")
    groups = []
    for value, reported_count in sorted(violations.items()):
        occurrences = occurrence_map.get(value)
        if not isinstance(value, str) or not isinstance(reported_count, int):
            raise RuntimeError(f"audit {kind} violation is invalid")
        if not isinstance(occurrences, list) or not all(
            isinstance(record_id, str) for record_id in occurrences
        ):
            raise RuntimeError(f"audit {kind} occurrence list is invalid")
        if len(occurrences) != reported_count:
            raise RuntimeError(f"audit {kind} occurrence count does not match")
        missing = sorted(set(occurrences).difference(records_by_id))
        if missing:
            raise RuntimeError(f"audit {kind} references unknown record IDs: {missing}")
        groups.append(
            {
                "id": _group_id(kind, value),
                "limit": limit,
                "occurrences": Counter(occurrences),
            }
        )
    return groups


def _group_id(kind: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    return f"{kind}:{digest}"


def _select_repetition_repairs(
    groups: list[dict[str, Any]], records_by_id: dict[str, dict[str, object]]
) -> tuple[set[str], dict[str, set[str]]]:
    selected: set[str] = set()
    reasons: dict[str, set[str]] = defaultdict(set)
    remaining = [Counter(group["occurrences"]) for group in groups]
    while True:
        overflow = [
            max(0, sum(counts.values()) - int(group["limit"]))
            for group, counts in zip(groups, remaining, strict=True)
        ]
        if not any(overflow):
            return selected, reasons
        candidates = {
            record_id
            for counts, excess in zip(remaining, overflow, strict=True)
            if excess
            for record_id in counts
            if record_id not in selected
        }
        if not candidates:
            raise RuntimeError("repair selection cannot reduce all audit overflows")
        chosen = min(
            candidates,
            key=lambda record_id: (
                -_coverage(record_id, remaining, overflow),
                -_category_priority(records_by_id[record_id]),
                record_id,
            ),
        )
        selected.add(chosen)
        for group, counts, excess in zip(groups, remaining, overflow, strict=True):
            if chosen in counts:
                if excess:
                    reasons[chosen].add(group["id"])
                del counts[chosen]


def _coverage(
    record_id: str, remaining: list[Counter[str]], overflow: list[int]
) -> int:
    return sum(
        min(counts.get(record_id, 0), excess)
        for counts, excess in zip(remaining, overflow, strict=True)
    )


def _category_priority(record: dict[str, object]) -> int:
    category = record.get("category")
    if not isinstance(category, str):
        return 0
    return {"game_commentary": 3, "conversation": 2, "stream_event": 1}.get(
        category, 0
    )


def _add_category_rebalance(
    selected: set[str],
    reasons: dict[str, set[str]],
    records_by_id: dict[str, dict[str, object]],
    targets: dict[str, int],
) -> dict[str, str]:
    source_counts = Counter(
        str(record.get("category", "")) for record in records_by_id.values()
    )
    replacements = {
        "game_commentary": (
            "game_review",
            source_counts["game_commentary"] - targets["game_commentary"],
        ),
        "conversation": (
            "transition",
            source_counts["conversation"] - targets["conversation"],
        ),
        "stream_event": (
            "transition",
            source_counts["stream_event"] - targets["stream_event"],
        ),
    }
    target_by_id = {}
    for source_category, (target_category, required) in replacements.items():
        if required < 0:
            raise RuntimeError(f"category {source_category} is below its quota")
        candidates = sorted(
            record_id
            for record_id, record in records_by_id.items()
            if record.get("category") == source_category
        )
        preferred = [record_id for record_id in candidates if record_id in selected]
        ordered = preferred + [item for item in candidates if item not in selected]
        chosen = ordered[:required]
        if len(chosen) != required:
            raise RuntimeError(
                f"not enough {source_category} records for category rebalance"
            )
        for record_id in chosen:
            selected.add(record_id)
            reasons[record_id].add("category_quota_rebalance")
            target_by_id[record_id] = target_category
    expected_counts = source_counts.copy()
    for record_id, target_category in target_by_id.items():
        expected_counts[str(records_by_id[record_id]["category"])] -= 1
        expected_counts[target_category] += 1
    if any(expected_counts[category] != target for category, target in targets.items()):
        raise RuntimeError("category rebalance does not reach the frozen quotas")
    return target_by_id


def _entry(
    record_id: str,
    record: dict[str, object],
    reasons: set[str],
    target_by_id: dict[str, str],
) -> dict[str, Any]:
    target_category = target_by_id.get(record_id, record["category"])
    return {
        "record_id": record_id,
        "original_record_sha256": _record_sha256(record),
        "original_category": record["category"],
        "repair_reasons": sorted(reasons),
        "preserve": {
            "batch_id": record["batch_id"],
            "record_id": record_id,
            "language_class": record["language_class"],
            "intended_length_class": record["intended_length_class"],
        },
        "target": {"category": target_category},
    }


def _record_sha256(record: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            record, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


def _report(repair_set: dict[str, Any]) -> dict[str, Any]:
    records = repair_set["records"]
    return {
        "corpus_v4_repair_report_schema_version": 1,
        "source_audit_sha256": repair_set["source_audit_sha256"],
        "implicated_record_count": repair_set["implicated_record_count"],
        "selected_record_count": repair_set["selected_record_count"],
        "selected_by_batch": dict(
            sorted(Counter(entry["preserve"]["batch_id"] for entry in records).items())
        ),
        "selected_by_category": dict(
            sorted(Counter(entry["original_category"] for entry in records).items())
        ),
        "selected_by_target_category": dict(
            sorted(Counter(entry["target"]["category"] for entry in records).items())
        ),
        "selected_by_language": dict(
            sorted(
                Counter(
                    entry["preserve"]["language_class"] for entry in records
                ).items()
            )
        ),
        "selected_by_length": dict(
            sorted(
                Counter(
                    entry["preserve"]["intended_length_class"] for entry in records
                ).items()
            )
        ),
        "quota_rebalance_record_count": sum(
            "category_quota_rebalance" in entry["repair_reasons"] for entry in records
        ),
    }


if __name__ == "__main__":
    raise SystemExit(main())
