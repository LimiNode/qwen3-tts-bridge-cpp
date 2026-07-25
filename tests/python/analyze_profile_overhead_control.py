"""Analyze randomized faster telemetry overhead control artifacts."""

# pyright: reportArgumentType=false, reportCallIssue=false

from __future__ import annotations

import argparse
import json
import random
import statistics
from pathlib import Path

CONDITIONS = (
    "A_pristine",
    "B_telemetry_profile_off",
    "C_telemetry_profile_on",
)
METRICS = (
    "first_audio_ms",
    "steady_first_audio_ms",
    "paired_delta_first_audio_ms",
)
COMPARISONS = (
    ("B_minus_A", "B_telemetry_profile_off", "A_pristine"),
    ("C_minus_B", "C_telemetry_profile_on", "B_telemetry_profile_off"),
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--schedule", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bootstrap-resamples", type=int, default=20_000)
    parser.add_argument("--bootstrap-seed", type=int, default=20260725)
    args = parser.parse_args()

    summary = json.loads(args.summary.read_text(encoding="utf-8"))
    schedule = _load_jsonl(args.schedule)
    records = _records_with_schedule(summary, schedule)
    report = _build_report(
        records,
        bootstrap_resamples=args.bootstrap_resamples,
        bootstrap_seed=args.bootstrap_seed,
    )
    report["source_summary"] = str(args.summary)
    report["source_schedule"] = str(args.schedule)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(report["headline"], sort_keys=True))
    return 0


def _load_jsonl(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    ]


def _records_with_schedule(
    summary: dict[str, object],
    schedule: list[dict[str, object]],
) -> list[dict[str, object]]:
    records = summary.get("records")
    if not isinstance(records, list):
        raise ValueError("summary must contain records")
    if len(records) != len(schedule):
        raise ValueError("summary records and schedule lengths differ")

    enriched: list[dict[str, object]] = []
    for record, item in zip(records, schedule, strict=True):
        if not isinstance(record, dict) or not isinstance(item, dict):
            raise ValueError("records and schedule entries must be objects")
        if record.get("condition") != item.get("condition"):
            raise ValueError("record condition does not match schedule condition")
        merged = dict(record)
        merged["schedule_index"] = item.get("index")
        merged["replicate"] = item.get("replicate")
        enriched.append(merged)
    return enriched


def _build_report(
    records: list[dict[str, object]],
    *,
    bootstrap_resamples: int,
    bootstrap_seed: int,
) -> dict[str, object]:
    groups = {
        "all_r50": records,
        "initial_r30": [
            record
            for record in records
            if isinstance(record.get("replicate"), int)
            and int(record["replicate"]) <= 30
        ],
        "extension_r20": [
            record
            for record in records
            if isinstance(record.get("replicate"), int)
            and int(record["replicate"]) > 30
        ],
    }
    split_summaries = {
        name: _condition_summaries(group)
        for name, group in groups.items()
    }
    comparisons = {
        name: _comparison_summaries(group)
        for name, group in groups.items()
    }
    bootstrap = _bootstrap_comparisons(
        groups["all_r50"],
        resamples=bootstrap_resamples,
        seed=bootstrap_seed,
    )
    return {
        "artifact_schema_version": 1,
        "headline": {
            "note": (
                "condition p95 differences are differences of independent "
                "condition quantiles, not p95 of per-run overhead"
            ),
            "bootstrap_resamples": bootstrap_resamples,
            "bootstrap_seed": bootstrap_seed,
        },
        "split_summaries": split_summaries,
        "comparison_summaries": comparisons,
        "bootstrap_95ci": bootstrap,
    }


def _condition_summaries(
    records: list[dict[str, object]],
) -> dict[str, dict[str, object]]:
    return {
        condition: {
            "count": len(_by_condition(records, condition)),
            **{
                metric: _summary(_values(_by_condition(records, condition), metric))
                for metric in METRICS
            },
        }
        for condition in CONDITIONS
    }


def _comparison_summaries(
    records: list[dict[str, object]],
) -> dict[str, dict[str, object]]:
    return {
        name: {
            _comparison_metric_name(metric, statistic): _difference(
                records,
                left,
                right,
                metric,
                statistic,
            )
            for metric in METRICS
            for statistic in ("median", "p95")
        }
        for name, left, right in COMPARISONS
    }


def _bootstrap_comparisons(
    records: list[dict[str, object]],
    *,
    resamples: int,
    seed: int,
) -> dict[str, dict[str, object]]:
    rng = random.Random(seed)
    by_condition = {
        condition: _by_condition(records, condition)
        for condition in CONDITIONS
    }
    result: dict[str, dict[str, object]] = {}
    for name, left, right in COMPARISONS:
        item: dict[str, object] = {}
        left_records = by_condition[left]
        right_records = by_condition[right]
        for metric in METRICS:
            for statistic in ("median", "p95"):
                samples = [
                    _sample_difference(
                        rng,
                        left_records,
                        right_records,
                        metric,
                        statistic,
                    )
                    for _ in range(resamples)
                ]
                samples.sort()
                key = _comparison_metric_name(metric, statistic)
                item[key] = {
                    "observed_ms": _difference(
                        records,
                        left,
                        right,
                        metric,
                        statistic,
                    ),
                    "ci95_ms": [_percentile(samples, 2.5), _percentile(samples, 97.5)],
                }
        result[name] = item
    return result


def _sample_difference(
    rng: random.Random,
    left_records: list[dict[str, object]],
    right_records: list[dict[str, object]],
    metric: str,
    statistic: str,
) -> float | None:
    left_sample = [rng.choice(left_records) for _ in left_records]
    right_sample = [rng.choice(right_records) for _ in right_records]
    left_value = _statistic(_values(left_sample, metric), statistic)
    right_value = _statistic(_values(right_sample, metric), statistic)
    if left_value is None or right_value is None:
        return None
    return left_value - right_value


def _comparison_metric_name(metric: str, statistic: str) -> str:
    return f"{metric}_{statistic}_difference_ms"


def _difference(
    records: list[dict[str, object]],
    left: str,
    right: str,
    metric: str,
    statistic: str,
) -> float | None:
    left_value = _statistic(_values(_by_condition(records, left), metric), statistic)
    right_value = _statistic(_values(_by_condition(records, right), metric), statistic)
    if left_value is None or right_value is None:
        return None
    return left_value - right_value


def _by_condition(
    records: list[dict[str, object]],
    condition: str,
) -> list[dict[str, object]]:
    return [record for record in records if record.get("condition") == condition]


def _values(records: list[dict[str, object]], metric: str) -> list[float]:
    return [
        float(record[metric])
        for record in records
        if isinstance(record.get(metric), (int, float))
    ]


def _summary(values: list[float]) -> dict[str, float] | None:
    if not values:
        return None
    values = sorted(values)
    return {
        "min": values[0],
        "median": statistics.median(values),
        "p90": _percentile(values, 90.0),
        "p95": _percentile(values, 95.0),
        "max": values[-1],
    }


def _statistic(values: list[float], statistic: str) -> float | None:
    summary = _summary(values)
    if summary is None:
        return None
    return summary[statistic]


def _percentile(values: list[float], percentile: float) -> float:
    clean_values = [value for value in values if value is not None]
    if not clean_values:
        raise ValueError("percentile requires at least one value")
    clean_values.sort()
    if len(clean_values) == 1:
        return clean_values[0]
    rank = percentile / 100.0 * (len(clean_values) - 1)
    low = int(rank)
    high = min(low + 1, len(clean_values) - 1)
    fraction = rank - low
    return clean_values[low] * (1.0 - fraction) + clean_values[high] * fraction


if __name__ == "__main__":
    raise SystemExit(main())
