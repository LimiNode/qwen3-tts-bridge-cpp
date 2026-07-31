"""Fail closed on a completed Qwen discovery run and its exact route contract."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--runtime-split-audit", type=Path, required=True)
    parser.add_argument("--expected-corpus-id", required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    result = validate(
        input_path=args.input,
        audit_path=args.runtime_split_audit,
        expected_corpus_id=args.expected_corpus_id,
        profile_path=args.profile,
        run_dir=args.run_dir,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0 if result["overall_acceptance_pass"] else 1


def validate(
    *,
    input_path: Path,
    audit_path: Path,
    expected_corpus_id: str,
    profile_path: Path,
    run_dir: Path,
) -> dict[str, object]:
    records = _load_jsonl(input_path, "input")
    audit = _load_object(audit_path, "runtime split audit")
    profile = _load_object(profile_path, "profile")
    manifest = _load_object(run_dir / "run-manifest.json", "run manifest")
    rows = _load_jsonl(run_dir / "records.jsonl", "records")

    input_sha256 = _sha256(input_path)
    expected_ids = {str(record.get("record_id", "")) for record in records}
    observed_ids = [str(row.get("record_id", "")) for row in rows]
    observed_id_set = set(observed_ids)
    profile_sha256 = _sha256(profile_path)

    provenance_checks = {
        "input_sha256": audit.get("discovery_sha256") == input_sha256
        and manifest.get("input_sha256") == input_sha256,
        "corpus_id": audit.get("corpus_id") == expected_corpus_id
        and manifest.get("corpus_id") == expected_corpus_id,
        "discovery_split": all(record.get("corpus_split") == "discovery" for record in records),
        "record_count": audit.get("discovery_count") == len(records),
        "profile_sha256": _nested_sha(manifest, "profile") == profile_sha256,
        "record_ids": bool(expected_ids)
        and "" not in expected_ids
        and observed_id_set == expected_ids
        and len(observed_ids) == len(observed_id_set),
    }

    execution_counts = Counter(_execution_outcome(row) for row in rows)
    generation_counts = Counter(_generation_outcome(row) for row in rows)
    route_failures = [
        {"record_id": row.get("record_id"), "failures": failures}
        for row in rows
        if (failures := _route_failures(row, profile))
    ]
    checks = {
        **provenance_checks,
        "all_rows_terminal": all(_execution_outcome(row) in {"completed", "failed", "cancelled"} for row in rows),
        "execution_completed": execution_counts == {"completed": len(rows)},
        "generation_eos": generation_counts == {"eos": len(rows)},
        "exact_route_contract": not route_failures,
    }
    failed_checks = [name for name, passed in checks.items() if not passed]
    return {
        "qwen_corpus_discovery_validation_schema_version": 1,
        "corpus_id": expected_corpus_id,
        "record_count": len(rows),
        "input_sha256": input_sha256,
        "records_sha256": _sha256(run_dir / "records.jsonl"),
        "profile_sha256": profile_sha256,
        "checks": checks,
        "failed_checks": failed_checks,
        "execution_outcomes": dict(sorted(execution_counts.items())),
        "generation_outcomes": dict(sorted(generation_counts.items())),
        "route_failure_count": len(route_failures),
        "route_failures": route_failures,
        "route_acceptance_pass": checks["exact_route_contract"],
        "generation_acceptance_pass": checks["generation_eos"],
        "overall_acceptance_pass": not failed_checks,
        "decision": "accepted_for_baseline" if not failed_checks else "not_a_valid_baseline",
    }


def _route_failures(row: Mapping[str, object], profile: Mapping[str, object]) -> list[str]:
    route = row.get("first_chunk_route")
    if not isinstance(route, Mapping):
        return ["missing_first_chunk_route"]
    length = route.get("talker_prefill_length")
    if not isinstance(length, int) or isinstance(length, bool) or length <= 0:
        return ["invalid_talker_prefill_length"]
    allowlist = _positive_int_set(profile.get("prefill_compile_lengths"))
    cache_entries = profile.get("prefill_allowlist_max_entries")
    if not isinstance(cache_entries, int) or isinstance(cache_entries, bool) or cache_entries <= 0:
        return ["invalid_profile_cache_entries"]
    if length in allowlist:
        expected = {
            "prefill_shape_policy": "compiled_allowlist",
            "prefill_backend_used": "compile_reduce_overhead",
            "selected_chunk_schedule": [8, 8, 12],
            "chunk_schedule_decision": "compiled_allowlist",
            "prefill_compile_cache_hit": True,
            "prefill_shape_allowlist_hit": True,
            "prefill_compile_attempted": False,
            "prefill_compile_fallback": False,
            "prefill_compile_cache_entries": cache_entries,
            "prefill_compile_cache_entries_delta": 0,
            "prefill_compile_cache_evictions_delta": 0,
        }
    else:
        expected = {
            "prefill_shape_policy": "eager_unknown",
            "prefill_backend_used": "eager",
            "selected_chunk_schedule": [8],
            "chunk_schedule_decision": "eager_unknown",
            "prefill_compile_cache_hit": False,
            "prefill_shape_allowlist_hit": False,
            "prefill_compile_attempted": False,
            "prefill_compile_fallback": False,
            "prefill_compile_cache_entries": cache_entries,
            "prefill_compile_cache_entries_delta": 0,
            "prefill_compile_cache_evictions_delta": 0,
        }
    return [field for field, value in expected.items() if route.get(field) != value]


def _execution_outcome(row: Mapping[str, object]) -> str:
    value = row.get("execution_outcome")
    if isinstance(value, str):
        return value
    return "completed" if row.get("request_outcome") == "completed" else "unknown"


def _generation_outcome(row: Mapping[str, object]) -> str:
    value = row.get("generation_outcome")
    if isinstance(value, str):
        return value
    trace = row.get("generation_trace")
    if not isinstance(trace, Mapping):
        return "unknown"
    if trace.get("hit_eos") is True or trace.get("termination_reason") == "eos":
        return "eos"
    if trace.get("hit_max_new_tokens") is True or trace.get("termination_reason") == "max_new_tokens":
        return "max_new_tokens"
    if trace.get("hit_max_seq_len") is True or trace.get("termination_reason") == "max_seq_len":
        return "max_seq_len"
    return "unknown"


def _positive_int_set(value: object) -> set[int]:
    if not isinstance(value, list):
        return set()
    return {
        item
        for item in value
        if isinstance(item, int) and not isinstance(item, bool) and item > 0
    }


def _load_jsonl(path: Path, name: str) -> list[dict[str, object]]:
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"{name} line {line_number} is not valid JSON") from exc
        if not isinstance(value, dict):
            raise RuntimeError(f"{name} line {line_number} must be an object")
        rows.append(value)
    if not rows:
        raise RuntimeError(f"{name} must not be empty")
    return rows


def _load_object(path: Path, name: str) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{name} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"{name} must be an object")
    return value


def _nested_sha(value: Mapping[str, object], key: str) -> str | None:
    nested = value.get(key)
    return nested.get("sha256") if isinstance(nested, Mapping) else None


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
