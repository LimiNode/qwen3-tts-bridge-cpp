"""Build paired, bootstrap-backed statistics from route-aware A/B reports."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import random
import statistics


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixed8-report", action="append", type=Path, required=True)
    parser.add_argument(
        "--route-aware-report", action="append", type=Path, required=True
    )
    parser.add_argument("--bootstrap-samples", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=20260730)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if len(args.fixed8_report) != len(args.route_aware_report):
        parser.error("fixed8 and route-aware report counts must match")
    if args.bootstrap_samples <= 0:
        parser.error("--bootstrap-samples must be positive")

    blocks = []
    all_pairs: list[dict[str, object]] = []
    for index, (fixed_path, route_path) in enumerate(
        zip(args.fixed8_report, args.route_aware_report, strict=True), 1
    ):
        fixed = _load_report(fixed_path)
        route = _load_report(route_path)
        pairs = _build_pairs(fixed["requests"], route["requests"])
        all_pairs.extend(pairs)
        blocks.append(
            {
                "block": index,
                "fixed8": _provenance(fixed_path),
                "route_aware": _provenance(route_path),
                "pair_count": len(pairs),
                "summary": _summary(pairs),
            }
        )
    report = {
        "artifact_schema_version": 1,
        "bootstrap_samples": args.bootstrap_samples,
        "bootstrap_seed": args.seed,
        "blocks": blocks,
        "pair_count": len(all_pairs),
        "summary": _summary(all_pairs),
        "bootstrap": _bootstrap(all_pairs, args.bootstrap_samples, args.seed),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0


def _load_report(path: Path) -> dict[str, object]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("requests"), list):
        raise RuntimeError(f"{path}: expected benchmark report with requests")
    return raw


def _provenance(path: Path) -> dict[str, str]:
    return {"path": str(path), "sha256": sha256(path.read_bytes()).hexdigest()}


def _build_pairs(
    fixed_requests: list[object],
    route_requests: list[object],
) -> list[dict[str, object]]:
    fixed = _by_label(fixed_requests, "fixed8")
    route = _by_label(route_requests, "route-aware")
    if set(fixed) != set(route):
        raise RuntimeError("A/B reports do not cover the same labels")
    pairs = []
    for label in sorted(fixed):
        fixed_values = fixed[label]
        route_values = route[label]
        if len(fixed_values) != len(route_values):
            raise RuntimeError(f"A/B reports differ in repetitions for {label}")
        for ordinal, (baseline, candidate) in enumerate(
            zip(fixed_values, route_values, strict=True), 1
        ):
            if baseline["contract"] != candidate["contract"]:
                raise RuntimeError(
                    f"A/B reports differ in manifest contract for {label}"
                )
            pairs.append(
                {
                    "label": label,
                    "category": (
                        "compiled" if label.startswith("compiled_") else "eager"
                    ),
                    "ordinal": ordinal,
                    "fixed8": _metrics(baseline),
                    "route_aware": _metrics(candidate),
                }
            )
    return pairs


def _metrics(values: dict[str, object]) -> dict[str, float]:
    return {
        key: float(values[key])
        for key in ("first_audio_ms", "completed_ms", "inverse_rtf")
    }


def _by_label(
    requests: list[object], side: str
) -> dict[str, list[dict[str, object]]]:
    grouped: dict[str, list[dict[str, object]]] = {}
    for request in requests:
        if not isinstance(request, dict):
            raise RuntimeError(f"{side}: invalid request entry")
        if not request.get("success") or request.get("cancelled"):
            raise RuntimeError(f"{side}: A/B request did not complete successfully")
        label = request.get("label")
        if not isinstance(label, str) or not label:
            raise RuntimeError(f"{side}: request lacks label")
        values: dict[str, object] = {"contract": _contract_key(request, side, label)}
        for key in ("first_audio_ms", "completed_ms", "inverse_rtf"):
            value = request.get(key)
            if not isinstance(value, (int, float)):
                raise RuntimeError(f"{side}: {label} lacks {key}")
            values[key] = float(value)
        grouped.setdefault(label, []).append(values)
    if not grouped:
        raise RuntimeError(f"{side}: report contains no completed requests")
    return grouped


def _contract_key(
    request: dict[str, object], side: str, label: str
) -> tuple[object, object, object]:
    contract = request.get("manifest_contract")
    if not isinstance(contract, dict) or contract.get("valid") is not True:
        raise RuntimeError(f"{side}: {label} lacks a valid manifest contract")
    expected = contract.get("expected")
    if not isinstance(expected, dict):
        raise RuntimeError(f"{side}: {label} lacks manifest expectations")
    fields = ("prefill_length", "route", "backend")
    values = tuple(expected.get(field) for field in fields)
    if any(value is None for value in values):
        raise RuntimeError(f"{side}: {label} has incomplete manifest expectations")
    return values


def _summary(pairs: list[dict[str, object]]) -> dict[str, object]:
    return {
        "all": _metric_summary(pairs),
        "compiled": _metric_summary(
            [pair for pair in pairs if pair["category"] == "compiled"]
        ),
        "eager": _metric_summary(
            [pair for pair in pairs if pair["category"] == "eager"]
        ),
        "per_label": {
            label: _metric_summary([pair for pair in pairs if pair["label"] == label])
            for label in sorted({str(pair["label"]) for pair in pairs})
        },
    }


def _metric_summary(pairs: list[dict[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {"pair_count": len(pairs)}
    for key, direction in (
        ("first_audio_ms", "lower"),
        ("completed_ms", "lower"),
        ("inverse_rtf", "higher"),
    ):
        baseline, candidate, improvement = _metric_values(pairs, key, direction)
        result[key] = {
            "fixed8_median": statistics.median(baseline),
            "route_aware_median": statistics.median(candidate),
            "median_improvement_percent": statistics.median(improvement),
            "p95_improvement_percent": _percentile(improvement, 95.0),
        }
    return result


def _bootstrap(
    pairs: list[dict[str, object]],
    samples: int,
    seed: int,
) -> dict[str, object]:
    random_source = random.Random(seed)
    result: dict[str, object] = {}
    for category in ("all", "compiled", "eager"):
        selected = pairs if category == "all" else [
            pair for pair in pairs if pair["category"] == category
        ]
        if not selected:
            result[category] = None
            continue
        category_result = {}
        for key, direction in (("completed_ms", "lower"), ("inverse_rtf", "higher")):
            _, _, observed = _metric_values(selected, key, direction)
            medians = []
            for _ in range(samples):
                bootstrap = [random_source.choice(observed) for _ in observed]
                medians.append(statistics.median(bootstrap))
            category_result[key] = {
                "median_improvement_percent": statistics.median(observed),
                "ci95_low_percent": _percentile(medians, 2.5),
                "ci95_high_percent": _percentile(medians, 97.5),
            }
        result[category] = category_result
    return result


def _metric_values(
    pairs: list[dict[str, object]],
    key: str,
    direction: str,
) -> tuple[list[float], list[float], list[float]]:
    baseline = [float(pair["fixed8"][key]) for pair in pairs]  # type: ignore[index]
    candidate = [float(pair["route_aware"][key]) for pair in pairs]  # type: ignore[index]
    if direction == "lower":
        improvement = [(left - right) * 100.0 / left for left, right in zip(baseline, candidate, strict=True)]
    else:
        improvement = [(right - left) * 100.0 / left for left, right in zip(baseline, candidate, strict=True)]
    return baseline, candidate, improvement


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    rank = percentile / 100.0 * (len(ordered) - 1)
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


if __name__ == "__main__":
    raise SystemExit(main())
