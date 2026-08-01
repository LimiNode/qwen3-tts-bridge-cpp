"""Summarize a completed holdout without changing the frozen allowlist policy."""

from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable, Mapping


_METRICS = ("first_audio_ms", "completed_ms", "inverse_rtf")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--candidate-profile", type=Path, required=True)
    parser.add_argument("--legacy-profile", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build_report(
        _load_jsonl(args.records),
        _load_object(args.candidate_profile),
        _load_object(args.legacy_profile),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"record_count": report["record_count"], "output": str(args.output)}))


def build_report(
    rows: list[dict[str, object]],
    candidate_profile: Mapping[str, object],
    legacy_profile: Mapping[str, object],
) -> dict[str, object]:
    candidate_lengths = _positive_int_set(candidate_profile.get("prefill_compile_lengths"))
    legacy_lengths = _positive_int_set(legacy_profile.get("prefill_compile_lengths"))
    if not rows or not candidate_lengths or not legacy_lengths:
        raise RuntimeError("records and both exact allowlists must be non-empty")
    for row in rows:
        if row.get("execution_outcome") != "completed" or row.get("generation_outcome") != "eos":
            raise RuntimeError("holdout report requires completed EOS rows")
    by_route = _group_report(rows, lambda row: _route_label(row))
    by_length = _group_report(rows, lambda row: str(_prefill_length(row)))
    by_category = _group_report(rows, lambda row: _string_value(row, "category"))
    by_language = _group_report(rows, lambda row: _string_value(row, "language_class"))
    observed_compiled = sum(_prefill_length(row) in candidate_lengths for row in rows)
    legacy_compiled = sum(_prefill_length(row) in legacy_lengths for row in rows)
    return {
        "holdout_route_report_schema_version": 1,
        "record_count": len(rows),
        "candidate_exact_lengths": sorted(candidate_lengths),
        "legacy_exact_lengths_descriptive_only": sorted(legacy_lengths),
        "coverage": {
            "candidate_compiled_count": observed_compiled,
            "candidate_compiled_percent": _percent(observed_compiled, len(rows)),
            "legacy_compiled_count_descriptive_only": legacy_compiled,
            "legacy_compiled_percent_descriptive_only": _percent(legacy_compiled, len(rows)),
        },
        "by_route": by_route,
        "by_prefill_length": by_length,
        "by_category": by_category,
        "by_language_class": by_language,
        "notes": [
            "This report is descriptive only and does not retune the frozen allowlist.",
            "The legacy coverage is counterfactual routing coverage, not a new runtime measurement.",
        ],
    }


def _group_report(
    rows: Iterable[Mapping[str, object]],
    label: object,
) -> dict[str, object]:
    groups: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for row in rows:
        groups[str(label(row))].append(row)
    return {
        name: {"count": len(group), **{metric: _distribution(group, metric) for metric in _METRICS}}
        for name, group in sorted(groups.items(), key=lambda item: _sort_key(item[0]))
    }


def _route_label(row: Mapping[str, object]) -> str:
    route = row.get("first_chunk_route")
    if not isinstance(route, Mapping):
        return "missing"
    value = route.get("prefill_shape_policy")
    return value if isinstance(value, str) else "missing"


def _prefill_length(row: Mapping[str, object]) -> int:
    route = row.get("first_chunk_route")
    if not isinstance(route, Mapping):
        raise RuntimeError("row lacks first_chunk_route")
    value = route.get("talker_prefill_length")
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise RuntimeError("row has invalid talker_prefill_length")
    return value


def _string_value(row: Mapping[str, object], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"row lacks {key}")
    return value


def _distribution(rows: Iterable[Mapping[str, object]], metric: str) -> dict[str, float]:
    values = sorted(float(row[metric]) for row in rows)
    return {
        "min": round(values[0], 3),
        "p50": round(_percentile(values, 0.50), 3),
        "p95": round(_percentile(values, 0.95), 3),
        "max": round(values[-1], 3),
        "mean": round(statistics.fmean(values), 3),
    }


def _percentile(values: list[float], fraction: float) -> float:
    index = (len(values) - 1) * fraction
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return values[lower]
    return values[lower] + (values[upper] - values[lower]) * (index - lower)


def _positive_int_set(value: object) -> set[int]:
    if not isinstance(value, list):
        return set()
    return {item for item in value if isinstance(item, int) and not isinstance(item, bool) and item > 0}


def _percent(numerator: int, denominator: int) -> float:
    return round(100.0 * numerator / denominator, 4)


def _sort_key(value: str) -> tuple[int, object]:
    return (0, int(value)) if value.isdigit() else (1, value)


def _load_jsonl(path: Path) -> list[dict[str, object]]:
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        value = json.loads(line)
        if not isinstance(value, dict):
            raise RuntimeError(f"records line {line_number} must be an object")
        rows.append(value)
    return rows


def _load_object(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"{path} must be an object")
    return value


if __name__ == "__main__":
    main()
