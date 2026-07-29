"""Create and validate fresh-worker exact-allowlist discovery matrices."""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Any

from semantic_trace_contract import validate_generation_trace


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    schedule_parser = subparsers.add_parser("schedule")
    schedule_parser.add_argument("--manifest", type=Path, required=True)
    schedule_parser.add_argument("--output", type=Path, required=True)
    schedule_parser.add_argument("--repeats", type=int, default=5)
    schedule_parser.add_argument("--unknown-lengths", default="31,38,45")
    schedule_parser.add_argument("--seed", type=int, default=20260729)

    analyze_parser = subparsers.add_parser("analyze")
    analyze_parser.add_argument("--report", type=Path, required=True)
    analyze_parser.add_argument("--output", type=Path, required=True)
    analyze_parser.add_argument("--first-ttfa-p95-max-ms", type=float, default=300.0)
    analyze_parser.add_argument(
        "--first-minus-steady-p95-max-ms", type=float, default=20.0
    )

    args = parser.parse_args()
    if args.command == "schedule":
        rows = _build_schedule(args)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
            encoding="utf-8",
        )
        print(json.dumps({"rows": len(rows), "output": str(args.output)}))
        return 0

    report = json.loads(args.report.read_text(encoding="utf-8"))
    summary = _analyze_report(report, args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(
        json.dumps(
            {"acceptance_pass": summary["acceptance_pass"], "output": str(args.output)}
        )
    )
    return 0 if summary["acceptance_pass"] else 1


def _build_schedule(args: argparse.Namespace) -> list[dict[str, object]]:
    if args.repeats <= 0:
        raise ValueError("--repeats must be positive")
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    selected = manifest.get("selected_exact_lengths")
    source_rows = manifest.get("rows")
    if not isinstance(selected, list) or not isinstance(source_rows, list):
        raise ValueError("manifest lacks selected_exact_lengths or rows")
    known_lengths = [int(value) for value in selected]
    unknown_lengths = _parse_lengths(args.unknown_lengths)
    if set(known_lengths) & set(unknown_lengths):
        raise ValueError("unknown lengths overlap selected exact allowlist lengths")

    categories = [
        _select_manifest_row(source_rows, length, f"allowlist_{length}")
        for length in known_lengths
    ]
    unknown_labels = ("unknown_short", "unknown_medium", "unknown_long")
    if len(unknown_lengths) != len(unknown_labels):
        raise ValueError("--unknown-lengths must contain short,medium,long lengths")
    categories.extend(
        _select_manifest_row(source_rows, length, label)
        for label, length in zip(unknown_labels, unknown_lengths, strict=True)
    )

    rows = [dict(row) for row in categories for _ in range(args.repeats)]
    random.Random(args.seed).shuffle(rows)
    return rows


def _select_manifest_row(
    rows: list[object],
    length: int,
    category: str,
) -> dict[str, object]:
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("talker_prefill_length") != length or row.get("instruction"):
            continue
        text = row.get("text")
        language = row.get("language")
        if isinstance(text, str) and text and isinstance(language, str) and language:
            return {
                "label": category,
                "text": text,
                "language": language,
                "speaker": "ryan",
                "instruction": "",
                "talker_prefill_length": length,
            }
    raise ValueError(f"manifest has no instruction-free row for length {length}")


def _analyze_report(report: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    runs = report.get("runs")
    if not isinstance(runs, list):
        raise ValueError("restart report lacks runs")
    by_category: dict[str, list[dict[str, Any]]] = {}
    failures: list[str] = []
    for run in runs:
        if not isinstance(run, dict):
            failures.append("invalid run record")
            continue
        shape = run.get("shape")
        category = shape.get("label") if isinstance(shape, dict) else None
        requests = run.get("requests")
        if not isinstance(category, str) or not isinstance(requests, list):
            failures.append("run lacks shape_label or requests")
            continue
        by_category.setdefault(category, []).append(run)
        for request in requests:
            if not isinstance(request, dict):
                failures.append(f"{category}: invalid request record")
                continue
            _validate_request(category, request, failures)

    category_summaries = {
        category: _category_summary(
            category,
            category_runs,
            args.first_ttfa_p95_max_ms,
            args.first_minus_steady_p95_max_ms,
            failures,
        )
        for category, category_runs in sorted(by_category.items())
    }
    return {
        "artifact_schema_version": 1,
        "acceptance_pass": not failures,
        "thresholds": {
            "first_ttfa_p95_max_ms": args.first_ttfa_p95_max_ms,
            "first_minus_steady_p95_max_ms": args.first_minus_steady_p95_max_ms,
        },
        "categories": category_summaries,
        "failures": failures,
    }


def _validate_request(
    category: str,
    request: dict[str, Any],
    failures: list[str],
) -> None:
    trace = request.get("generation_trace")
    if not isinstance(trace, dict):
        failures.append(f"{category}: missing generation trace")
    else:
        try:
            validate_generation_trace(trace)
        except RuntimeError as exc:
            failures.append(f"{category}: {exc}")

    known_length = _allowlist_length(category)
    if known_length is None:
        _expect(
            category,
            request,
            "first_chunk_prefill_shape_policy",
            "eager_unknown",
            failures,
        )
        _expect(
            category,
            request,
            "first_chunk_prefill_shape_allowlist_hit",
            False,
            failures,
        )
        _expect(
            category, request, "first_chunk_prefill_backend_used", "eager", failures
        )
        _expect(
            category, request, "first_chunk_prefill_compile_fallback", False, failures
        )
        return

    _expect(
        category, request, "first_chunk_talker_prefill_length", known_length, failures
    )
    _expect(
        category,
        request,
        "first_chunk_prefill_shape_policy",
        "compiled_allowlist",
        failures,
    )
    _expect(
        category, request, "first_chunk_prefill_shape_allowlist_hit", True, failures
    )
    _expect(category, request, "first_chunk_prefill_compile_cache_hit", True, failures)
    _expect(category, request, "first_chunk_prefill_compile_fallback", False, failures)
    _expect(
        category, request, "first_chunk_prefill_require_precompiled", True, failures
    )
    ordinal = request.get("first_chunk_prefill_shape_call_ordinal")
    if not isinstance(ordinal, (int, float)) or ordinal < 4:
        failures.append(f"{category}: expected prefill ordinal >= 4, got {ordinal!r}")


def _category_summary(
    category: str,
    runs: list[dict[str, Any]],
    first_max_ms: float,
    delta_max_ms: float,
    failures: list[str],
) -> dict[str, object]:
    first = [float(run["first_request"]["first_audio_ms"]) for run in runs]
    deltas = [float(run["paired_delta_first_audio_ms"]) for run in runs]
    first_p95 = _percentile(first, 95.0)
    delta_p95 = _percentile(deltas, 95.0)
    if first_p95 >= first_max_ms:
        failures.append(
            f"{category}: first TTFA p95 {first_p95:.3f} ms is not < "
            f"{first_max_ms:.3f} ms"
        )
    if delta_p95 >= delta_max_ms:
        failures.append(
            f"{category}: first-minus-steady p95 {delta_p95:.3f} ms is not < "
            f"{delta_max_ms:.3f} ms"
        )
    return {
        "fresh_processes": len(runs),
        "first_ttfa_ms": _summary(first),
        "first_minus_steady_ms": _summary(deltas),
    }


def _expect(
    category: str,
    request: dict[str, Any],
    key: str,
    expected: object,
    failures: list[str],
) -> None:
    if request.get(key) != expected:
        failures.append(
            f"{category}: expected {key}={expected!r}, got {request.get(key)!r}"
        )


def _allowlist_length(category: str) -> int | None:
    if not category.startswith("allowlist_"):
        return None
    return int(category.removeprefix("allowlist_"))


def _parse_lengths(value: str) -> list[int]:
    return [int(part) for part in value.split(",") if part.strip()]


def _summary(values: list[float]) -> dict[str, float]:
    return {
        "min": min(values),
        "median": _percentile(values, 50.0),
        "p95": _percentile(values, 95.0),
        "max": max(values),
    }


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = percentile / 100.0 * (len(ordered) - 1)
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


if __name__ == "__main__":
    raise SystemExit(main())
