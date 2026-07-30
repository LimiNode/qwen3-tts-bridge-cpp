"""Build a provenance-pinned deterministic corpus-v4 repair set from an audit."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

try:
    from scripts.audit_corpus_repetition import _is_sha256, _record_id_set_sha256
    from scripts.validate_corpus_v4_batches import _GLOBAL_QUOTAS
except ModuleNotFoundError:
    from audit_corpus_repetition import _is_sha256, _record_id_set_sha256
    from validate_corpus_v4_batches import _GLOBAL_QUOTAS

_AUDIT_SCHEMA_VERSION = 4
_POLICY_SCHEMA_VERSION = 1
_REPAIR_SET_SCHEMA_VERSION = 3
_MAX_LOCAL_IMPROVEMENT_TRIALS = 25_000
_MAX_FIXED_SLOT_SWAP_TRIALS = 5_000


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--repair-policy", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    audit_bytes = args.audit.read_bytes()
    records_bytes = args.records.read_bytes()
    policy_bytes = args.repair_policy.read_bytes()
    audit = _load_object_bytes(audit_bytes, "audit")
    records = _load_records_bytes(records_bytes)
    policy = _load_object_bytes(policy_bytes, "repair policy")
    repair_set = _build_repair_set(
        audit,
        records,
        source_audit_sha256=hashlib.sha256(audit_bytes).hexdigest(),
        source_records_sha256=hashlib.sha256(records_bytes).hexdigest(),
        source_record_id_set_sha256=_record_id_set_sha256(records),
        repair_policy=policy,
        repair_policy_sha256=hashlib.sha256(policy_bytes).hexdigest(),
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
    *,
    source_audit_sha256: str,
    source_records_sha256: str,
    source_record_id_set_sha256: str,
    repair_policy: dict[str, object],
    repair_policy_sha256: str,
    category_quotas: dict[str, int] | None = None,
) -> dict[str, Any]:
    records_by_id = _records_by_id(records)
    _validate_audit_provenance(
        audit,
        records,
        source_records_sha256,
        source_record_id_set_sha256,
    )
    policy = _validate_policy(
        repair_policy,
        records_by_id,
        category_quotas or _GLOBAL_QUOTAS["category"],
    )
    if audit["corpus_id"] != policy["corpus_id"]:
        raise RuntimeError("audit corpus_id does not match repair policy")
    if not _is_sha256(source_audit_sha256) or not _is_sha256(repair_policy_sha256):
        raise RuntimeError("repair inputs must use SHA-256 values")

    groups = _groups(audit, records_by_id)
    selected, reasons = _select_repetition_repairs(
        groups, records_by_id, policy["selection_priority"]
    )
    greedy_selected_count = len(selected)
    target_by_id = _add_category_rebalance(
        selected,
        reasons,
        records_by_id,
        policy["allowed_category_replacements"],
    )
    post_rebalance_selected_count = len(selected)
    selected = _reverse_prune(selected, target_by_id, groups)
    reverse_pruned_selected_count = len(selected)
    selected, target_by_id, fixed_slot_metrics = _bounded_fixed_slot_swap_improvement(
        selected,
        target_by_id,
        groups,
        records_by_id,
    )
    fixed_slot_swap_selected_count = len(selected)
    selected, local_metrics = _bounded_local_improvement(
        selected,
        target_by_id,
        groups,
    )
    selected = _reverse_prune(selected, target_by_id, groups)
    _add_missing_reasons(selected, reasons, groups)
    entries = [
        _entry(record_id, records_by_id[record_id], reasons[record_id], target_by_id)
        for record_id in sorted(selected)
    ]
    category_rebalance_record_count = len(target_by_id)
    metrics = {
        "greedy_repetition_selected_count": greedy_selected_count,
        "post_rebalance_selected_count": post_rebalance_selected_count,
        "reverse_pruned_selected_count": reverse_pruned_selected_count,
        "fixed_slot_swap_selected_count": fixed_slot_swap_selected_count,
        "local_improved_selected_count": len(selected),
        "category_rebalance_record_count": category_rebalance_record_count,
        "repetition_only_record_count": len(selected) - category_rebalance_record_count,
        **fixed_slot_metrics,
        **local_metrics,
    }
    return {
        "corpus_v4_repair_set_schema_version": _REPAIR_SET_SCHEMA_VERSION,
        "corpus_id": policy["corpus_id"],
        "source_audit_sha256": source_audit_sha256,
        "source_records_sha256": source_records_sha256,
        "source_record_id_set_sha256": source_record_id_set_sha256,
        "source_record_count": len(records),
        "repair_policy_sha256": repair_policy_sha256,
        "repair_policy_id": policy["corpus_id"],
        "implicated_record_count": len(
            {record_id for group in groups for record_id in group["occurrences"]}
        ),
        "selected_record_count": len(entries),
        "selection_policy": (
            "deterministic_greedy_multicover_fixed_slot_swap_reverse_delete_"
            "bounded_local_search"
        ),
        "selection_metrics": metrics,
        "records": entries,
    }


def _validate_audit_provenance(
    audit: dict[str, object],
    records: list[dict[str, object]],
    source_records_sha256: str,
    source_record_id_set_sha256: str,
) -> None:
    expected_fields = {
        "corpus_repetition_audit_schema_version",
        "corpus_id",
        "record_count",
        "source_records_sha256",
        "source_record_id_set_sha256",
        "limits",
        "frequencies",
        "violations",
        "violation_records",
        "passed",
    }
    if set(audit) != expected_fields:
        raise RuntimeError("audit top-level schema is invalid")
    if audit.get("corpus_repetition_audit_schema_version") != _AUDIT_SCHEMA_VERSION:
        raise RuntimeError("audit schema version is unsupported")
    if audit.get("record_count") != len(records):
        raise RuntimeError("audit record count does not match source records")
    if not isinstance(audit.get("corpus_id"), str) or not audit["corpus_id"]:
        raise RuntimeError("audit corpus_id is invalid")
    if audit.get("source_records_sha256") != source_records_sha256:
        raise RuntimeError("audit source records SHA does not match")
    if audit.get("source_record_id_set_sha256") != source_record_id_set_sha256:
        raise RuntimeError("audit source record ID set SHA does not match")


def _validate_policy(
    policy: dict[str, object],
    records_by_id: dict[str, dict[str, object]],
    targets: dict[str, int],
) -> dict[str, Any]:
    expected_fields = {
        "corpus_v4_repair_policy_schema_version",
        "corpus_id",
        "allowed_category_replacements",
        "selection_priority",
    }
    if set(policy) != expected_fields:
        raise RuntimeError("repair policy top-level schema is invalid")
    if policy.get("corpus_v4_repair_policy_schema_version") != _POLICY_SCHEMA_VERSION:
        raise RuntimeError("repair policy schema version is unsupported")
    corpus_id = policy.get("corpus_id")
    if not isinstance(corpus_id, str) or not corpus_id:
        raise RuntimeError("repair policy corpus_id is invalid")
    raw_replacements = policy.get("allowed_category_replacements")
    if not isinstance(raw_replacements, dict):
        raise RuntimeError("repair policy replacements are invalid")
    replacements: dict[str, dict[str, int]] = {}
    for source, target_counts in raw_replacements.items():
        if not isinstance(source, str) or source not in targets:
            raise RuntimeError("repair policy source category is invalid")
        if not isinstance(target_counts, dict) or not target_counts:
            raise RuntimeError("repair policy target categories are invalid")
        parsed = {}
        for target, count in target_counts.items():
            if (
                not isinstance(target, str)
                or target not in targets
                or not isinstance(count, int)
                or isinstance(count, bool)
                or count <= 0
            ):
                raise RuntimeError("repair policy target count is invalid")
            parsed[target] = count
        replacements[source] = parsed
    priority = policy.get("selection_priority")
    if (
        not isinstance(priority, list)
        or not all(isinstance(category, str) for category in priority)
        or len(priority) != len(set(priority))
        or set(priority) != set(replacements)
    ):
        raise RuntimeError("repair policy selection_priority is invalid")

    source_counts = Counter(
        str(record.get("category", "")) for record in records_by_id.values()
    )
    expected_sources = {
        category: source_counts[category] - target
        for category, target in targets.items()
        if source_counts[category] > target
    }
    expected_targets = {
        category: target - source_counts[category]
        for category, target in targets.items()
        if source_counts[category] < target
    }
    policy_sources = {
        source: sum(target_counts.values())
        for source, target_counts in replacements.items()
    }
    policy_targets = Counter()
    for target_counts in replacements.values():
        policy_targets.update(target_counts)
    if policy_sources != expected_sources or dict(policy_targets) != expected_targets:
        raise RuntimeError("repair policy does not match source category imbalance")
    return {
        "corpus_id": corpus_id,
        "allowed_category_replacements": replacements,
        "selection_priority": {
            category: len(priority) - index
            for index, category in enumerate(priority)
        },
    }


def _load_object_bytes(value: bytes, name: str) -> dict[str, object]:
    loaded = json.loads(value.decode("utf-8"))
    if not isinstance(loaded, dict):
        raise RuntimeError(f"{name} must be a JSON object")
    return loaded


def _load_records_bytes(value: bytes) -> list[dict[str, object]]:
    records = []
    for line_number, line in enumerate(value.decode("utf-8").splitlines(), 1):
        if not line.strip():
            continue
        loaded = json.loads(line)
        if not isinstance(loaded, dict):
            raise RuntimeError(f"records line {line_number} is not an object")
        records.append(loaded)
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
    limits = audit["limits"]
    violations = audit["violations"]
    violation_records = audit["violation_records"]
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
    groups: list[dict[str, Any]],
    records_by_id: dict[str, dict[str, object]],
    category_priority: dict[str, int],
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
                -category_priority.get(
                    str(records_by_id[record_id].get("category")), 0
                ),
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


def _add_category_rebalance(
    selected: set[str],
    reasons: dict[str, set[str]],
    records_by_id: dict[str, dict[str, object]],
    replacements: dict[str, dict[str, int]],
) -> dict[str, str]:
    target_by_id = {}
    for source_category, target_counts in replacements.items():
        candidates = sorted(
            record_id
            for record_id, record in records_by_id.items()
            if record.get("category") == source_category
        )
        preferred = [record_id for record_id in candidates if record_id in selected]
        ordered = preferred + [item for item in candidates if item not in selected]
        offset = 0
        for target_category, required in sorted(target_counts.items()):
            chosen = ordered[offset : offset + required]
            if len(chosen) != required:
                raise RuntimeError(
                    f"not enough {source_category} records for category rebalance"
                )
            for record_id in chosen:
                selected.add(record_id)
                reasons[record_id].add("category_quota_rebalance")
                target_by_id[record_id] = target_category
            offset += required
    return target_by_id


def _reverse_prune(
    selected: set[str], target_by_id: dict[str, str], groups: list[dict[str, Any]]
) -> set[str]:
    result = set(selected)
    fixed = set(target_by_id)
    for record_id in sorted(result.difference(fixed), reverse=True):
        candidate = result.difference({record_id})
        if _repetition_satisfied(candidate, groups):
            result = candidate
    return result


def _bounded_local_improvement(
    selected: set[str],
    target_by_id: dict[str, str],
    groups: list[dict[str, Any]],
) -> tuple[set[str], dict[str, int]]:
    result = set(selected)
    fixed = set(target_by_id)
    all_candidates = sorted(
        {record_id for group in groups for record_id in group["occurrences"]}
    )
    trials = 0
    improvements = 0
    while trials < _MAX_LOCAL_IMPROVEMENT_TRIALS:
        removable = sorted(result.difference(fixed))
        replacement_pool = [
            record_id for record_id in all_candidates if record_id not in result
        ]
        move = _find_local_move(
            result,
            removable,
            replacement_pool,
            groups,
            _MAX_LOCAL_IMPROVEMENT_TRIALS - trials,
        )
        trials += move["trials"]
        if move["selected"] is None:
            break
        result = move["selected"]
        result = _reverse_prune(result, target_by_id, groups)
        improvements += 1
    return result, {
        "bounded_local_improvement_trial_count": trials,
        "bounded_local_improvement_count": improvements,
    }


def _bounded_fixed_slot_swap_improvement(
    selected: set[str],
    target_by_id: dict[str, str],
    groups: list[dict[str, Any]],
    records_by_id: dict[str, dict[str, object]],
) -> tuple[set[str], dict[str, str], dict[str, int]]:
    """Try category-slot assignments that let reverse deletion remove repairs."""
    result = set(selected)
    targets = dict(target_by_id)
    trials = 0
    improvements = 0
    while trials < _MAX_FIXED_SLOT_SWAP_TRIALS:
        current_count = len(result)
        best: tuple[set[str], dict[str, str]] | None = None
        for fixed_id in sorted(targets):
            source_category = records_by_id[fixed_id].get("category")
            available = sorted(
                record_id
                for record_id, record in records_by_id.items()
                if record.get("category") == source_category
                and record_id != fixed_id
                and record_id not in targets
            )
            candidates = [record_id for record_id in available if record_id in result]
            candidates.extend(record_id for record_id in available if record_id not in result)
            for candidate_id in candidates:
                trials += 1
                candidate_targets = dict(targets)
                target_category = candidate_targets.pop(fixed_id)
                candidate_targets[candidate_id] = target_category
                candidate_selected = _reverse_prune(
                    result.union({candidate_id}), candidate_targets, groups
                )
                candidate_score = (
                    len(candidate_selected),
                    tuple(sorted(candidate_selected)),
                    tuple(sorted(candidate_targets.items())),
                )
                if best is None or candidate_score < (
                    len(best[0]),
                    tuple(sorted(best[0])),
                    tuple(sorted(best[1].items())),
                ):
                    best = (candidate_selected, candidate_targets)
                if trials >= _MAX_FIXED_SLOT_SWAP_TRIALS:
                    break
            if trials >= _MAX_FIXED_SLOT_SWAP_TRIALS:
                break
        if best is None or len(best[0]) >= current_count:
            break
        result, targets = best
        improvements += 1
    return result, targets, {
        "fixed_slot_swap_trial_count": trials,
        "fixed_slot_swap_count": improvements,
    }


def _find_local_move(
    selected: set[str],
    removable: list[str],
    replacement_pool: list[str],
    groups: list[dict[str, Any]],
    max_trials: int,
) -> dict[str, Any]:
    trials = 0
    for remove_count, add_count in ((2, 1), (3, 2)):
        for removed in itertools.combinations(removable, remove_count):
            for added in itertools.combinations(replacement_pool, add_count):
                trials += 1
                candidate = selected.difference(removed).union(added)
                if _repetition_satisfied(candidate, groups):
                    return {"selected": candidate, "trials": trials}
                if trials >= max_trials:
                    return {"selected": None, "trials": trials}
    return {"selected": None, "trials": trials}


def _repetition_satisfied(selected: set[str], groups: list[dict[str, Any]]) -> bool:
    return all(
        sum(
            count
            for record_id, count in group["occurrences"].items()
            if record_id not in selected
        )
        <= group["limit"]
        for group in groups
    )


def _add_missing_reasons(
    selected: set[str], reasons: dict[str, set[str]], groups: list[dict[str, Any]]
) -> None:
    for group in groups:
        for record_id in selected.intersection(group["occurrences"]):
            reasons[record_id].add(group["id"])


def _entry(
    record_id: str,
    record: dict[str, object],
    reasons: set[str],
    target_by_id: dict[str, str],
) -> dict[str, Any]:
    target_category = target_by_id.get(record_id)
    if target_category is None:
        target = {
            "category": record["category"],
            "scene_context": record["scene_context"],
            "speech_intent": record["speech_intent"],
        }
        target_metadata_policy = "preserve_exact"
    else:
        target = {"category": target_category}
        target_metadata_policy = "compatible_author_required"
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
        "target": target,
        "target_metadata_policy": target_metadata_policy,
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
        "corpus_v4_repair_report_schema_version": 2,
        "corpus_id": repair_set["corpus_id"],
        "source_audit_sha256": repair_set["source_audit_sha256"],
        "source_records_sha256": repair_set["source_records_sha256"],
        "repair_policy_sha256": repair_set["repair_policy_sha256"],
        "implicated_record_count": repair_set["implicated_record_count"],
        "selected_record_count": repair_set["selected_record_count"],
        "selection_policy": repair_set["selection_policy"],
        "selection_metrics": repair_set["selection_metrics"],
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
    }


if __name__ == "__main__":
    raise SystemExit(main())
