"""Create and validate fresh-worker exact-allowlist discovery matrices."""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter
from pathlib import Path
from typing import Any

try:
    from semantic_trace_contract import validate_generation_trace
except ModuleNotFoundError:  # Imported as scripts.qwen_fresh_process_matrix in tests.
    from scripts.semantic_trace_contract import validate_generation_trace


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    schedule_parser = subparsers.add_parser("schedule")
    schedule_source = schedule_parser.add_mutually_exclusive_group(required=True)
    schedule_source.add_argument("--manifest", type=Path)
    schedule_source.add_argument("--scenarios-jsonl", type=Path)
    schedule_parser.add_argument("--output", type=Path, required=True)
    schedule_parser.add_argument("--repeats", type=int, default=5)
    schedule_parser.add_argument("--unknown-lengths", default="31,38,45")
    schedule_parser.add_argument("--seed", type=int, default=20260729)

    analyze_parser = subparsers.add_parser("analyze")
    analyze_parser.add_argument("--report", type=Path, required=True)
    analyze_parser.add_argument("--output", type=Path, required=True)
    analyze_parser.add_argument(
        "--compiled-first-ttfa-p95-max-ms",
        "--first-ttfa-p95-max-ms",
        dest="compiled_first_ttfa_p95_max_ms",
        type=float,
        default=300.0,
    )
    analyze_parser.add_argument(
        "--eager-first-ttfa-p95-max-ms", type=float, default=450.0
    )
    analyze_parser.add_argument(
        "--global-first-ttfa-p95-max-ms", type=float, default=300.0
    )
    analyze_parser.add_argument(
        "--first-minus-steady-p95-max-ms", type=float, default=20.0
    )
    analyze_parser.add_argument(
        "--schedule",
        type=Path,
        help="Optional JSONL schedule used to validate exact category counts.",
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
            {
                "acceptance_pass": summary["acceptance_pass"],
                "acceptance": summary["acceptance"],
                "output": str(args.output),
            }
        )
    )
    return 0 if summary["acceptance_pass"] else 1


def _build_schedule(args: argparse.Namespace) -> list[dict[str, object]]:
    if args.repeats <= 0:
        raise ValueError("--repeats must be positive")
    if args.scenarios_jsonl is not None:
        scenarios = _load_jsonl(args.scenarios_jsonl)
        _validate_scenarios(scenarios)
        rows = [dict(row) for row in scenarios for _ in range(args.repeats)]
        random.Random(args.seed).shuffle(rows)
        return rows

    assert args.manifest is not None
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


def _validate_scenarios(rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError("--scenarios-jsonl must contain at least one scenario")
    for row_number, row in enumerate(rows, 1):
        label = row.get("label")
        text = row.get("text")
        length = row.get("talker_prefill_length")
        if not isinstance(label, str) or not label:
            raise ValueError(f"scenario {row_number} has invalid label")
        if not isinstance(text, str) or not text:
            raise ValueError(f"scenario {row_number} has invalid text")
        if not isinstance(length, int) or length <= 0:
            raise ValueError(f"scenario {row_number} has invalid talker_prefill_length")


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
    terminal_failures: list[str] = []
    routing_failures: list[str] = []
    schedule_failures: list[str] = []
    expected_requests = _expected_requests_per_run(report)
    for run in runs:
        if not isinstance(run, dict):
            schedule_failures.append("invalid run record")
            continue
        shape = run.get("shape")
        category = shape.get("label") if isinstance(shape, dict) else None
        requests = run.get("requests")
        if not isinstance(category, str) or not isinstance(requests, list):
            schedule_failures.append("run lacks shape_label or requests")
            continue
        if len(requests) != expected_requests:
            schedule_failures.append(
                f"{category}: expected {expected_requests} requests, "
                f"got {len(requests)}"
            )
        by_category.setdefault(category, []).append(run)
        expected_length = _expected_talker_prefill_length(category, shape)
        for request in requests:
            if not isinstance(request, dict):
                routing_failures.append(f"{category}: invalid request record")
                continue
            _validate_request(
                category,
                request,
                expected_length,
                terminal_failures,
                routing_failures,
            )

    expected_categories = _schedule_category_counts(args.schedule)
    observed_categories = Counter(
        {
            category: len(category_runs)
            for category, category_runs in by_category.items()
        }
    )
    if expected_categories and observed_categories != expected_categories:
        schedule_failures.append(
            "schedule category counts differ: "
            f"expected {dict(sorted(expected_categories.items()))}, "
            f"got {dict(sorted(observed_categories.items()))}"
        )

    category_summaries = {
        category: _category_summary(category_runs)
        for category, category_runs in sorted(by_category.items())
    }
    compiled_latency_failures = _latency_failures(
        category_summaries,
        lambda category: _allowlist_length(category) is not None,
        args.compiled_first_ttfa_p95_max_ms,
        args.first_minus_steady_p95_max_ms,
        "compiled",
    )
    eager_latency_failures = _latency_failures(
        category_summaries,
        lambda category: _allowlist_length(category) is None,
        args.eager_first_ttfa_p95_max_ms,
        args.first_minus_steady_p95_max_ms,
        "eager",
    )
    all_first = [
        float(run["first_request"]["first_audio_ms"])
        for category_runs in by_category.values()
        for run in category_runs
        if isinstance(run.get("first_request"), dict)
    ]
    all_deltas = [
        float(run["paired_delta_first_audio_ms"])
        for category_runs in by_category.values()
        for run in category_runs
        if isinstance(run.get("paired_delta_first_audio_ms"), (int, float))
    ]
    global_latency_failures = _aggregate_latency_failures(
        all_first,
        all_deltas,
        args.global_first_ttfa_p95_max_ms,
        args.first_minus_steady_p95_max_ms,
        "global",
    )
    acceptance = {
        "terminal_trace_acceptance_pass": not terminal_failures,
        "routing_acceptance_pass": not routing_failures and not schedule_failures,
        "compiled_latency_acceptance_pass": not compiled_latency_failures,
        "eager_latency_acceptance_pass": not eager_latency_failures,
        "global_latency_acceptance_pass": not global_latency_failures,
    }
    failures = (
        terminal_failures
        + routing_failures
        + schedule_failures
        + compiled_latency_failures
        + eager_latency_failures
        + global_latency_failures
    )
    return {
        "artifact_schema_version": 2,
        "acceptance_pass": all(
            acceptance[name]
            for name in (
                "terminal_trace_acceptance_pass",
                "routing_acceptance_pass",
                "compiled_latency_acceptance_pass",
                "eager_latency_acceptance_pass",
            )
        ),
        "acceptance": acceptance,
        "thresholds": {
            "compiled_first_ttfa_p95_max_ms": args.compiled_first_ttfa_p95_max_ms,
            "eager_first_ttfa_p95_max_ms": args.eager_first_ttfa_p95_max_ms,
            "global_first_ttfa_p95_max_ms": args.global_first_ttfa_p95_max_ms,
            "first_minus_steady_p95_max_ms": args.first_minus_steady_p95_max_ms,
        },
        "expected": {
            "requests_per_run": expected_requests,
            "schedule_category_counts": dict(sorted(expected_categories.items())),
        },
        "categories": category_summaries,
        "all_requests": {
            "fresh_processes": len(all_first),
            "first_ttfa_ms": _summary(all_first) if all_first else None,
            "first_minus_steady_ms": _summary(all_deltas) if all_deltas else None,
        },
        "failures": failures,
    }


def _validate_request(
    category: str,
    request: dict[str, Any],
    expected_length: int | None,
    terminal_failures: list[str],
    routing_failures: list[str],
) -> None:
    trace = request.get("generation_trace")
    if not isinstance(trace, dict):
        terminal_failures.append(f"{category}: missing generation trace")
    else:
        try:
            validate_generation_trace(trace)
        except RuntimeError as exc:
            terminal_failures.append(f"{category}: {exc}")

    known_length = _allowlist_length(category)
    if expected_length is not None:
        _expect(
            category,
            request,
            "first_chunk_talker_prefill_length",
            expected_length,
            routing_failures,
        )
    if known_length is None:
        _expect(
            category,
            request,
            "first_chunk_prefill_shape_policy",
            "eager_unknown",
            routing_failures,
        )
        _expect(
            category,
            request,
            "first_chunk_prefill_shape_allowlist_hit",
            False,
            routing_failures,
        )
        _expect(
            category,
            request,
            "first_chunk_prefill_backend_used",
            "eager",
            routing_failures,
        )
        _expect(
            category,
            request,
            "first_chunk_prefill_compile_fallback",
            False,
            routing_failures,
        )
        _expect_no_dynamic_compile(category, request, routing_failures)
        return

    _expect(
        category,
        request,
        "first_chunk_talker_prefill_length",
        known_length,
        routing_failures,
    )
    _expect(
        category,
        request,
        "first_chunk_prefill_shape_policy",
        "compiled_allowlist",
        routing_failures,
    )
    _expect(
        category,
        request,
        "first_chunk_prefill_shape_allowlist_hit",
        True,
        routing_failures,
    )
    _expect(
        category,
        request,
        "first_chunk_prefill_backend_used",
        "compile_reduce_overhead",
        routing_failures,
    )
    _expect(
        category,
        request,
        "first_chunk_prefill_compile_cache_hit",
        True,
        routing_failures,
    )
    _expect(
        category,
        request,
        "first_chunk_prefill_compile_fallback",
        False,
        routing_failures,
    )
    _expect(
        category,
        request,
        "first_chunk_prefill_require_precompiled",
        True,
        routing_failures,
    )
    ordinal = request.get("first_chunk_prefill_shape_call_ordinal")
    if not isinstance(ordinal, (int, float)) or ordinal < 4:
        routing_failures.append(
            f"{category}: expected prefill ordinal >= 4, got {ordinal!r}"
        )
    _expect_no_dynamic_compile(category, request, routing_failures)


def _category_summary(
    runs: list[dict[str, Any]],
) -> dict[str, object]:
    first = [float(run["first_request"]["first_audio_ms"]) for run in runs]
    deltas = [float(run["paired_delta_first_audio_ms"]) for run in runs]
    return {
        "fresh_processes": len(runs),
        "first_ttfa_ms": _summary(first),
        "first_minus_steady_ms": _summary(deltas),
    }


def _expect_no_dynamic_compile(
    category: str,
    request: dict[str, Any],
    failures: list[str],
) -> None:
    for key, expected in (
        ("first_chunk_prefill_compile_attempted", False),
        ("first_chunk_prefill_compile_attempt_count", 0),
        ("first_chunk_prefill_compile_cache_entries_delta", 0),
        ("first_chunk_prefill_compile_cache_evictions_delta", 0),
        ("first_chunk_prefill_dynamo_counter_available", True),
        ("first_chunk_prefill_dynamo_unique_graphs_delta", 0),
    ):
        _expect(category, request, key, expected, failures)


def _latency_failures(
    categories: dict[str, dict[str, object]],
    include_category: Any,
    first_max_ms: float,
    delta_max_ms: float,
    route: str,
) -> list[str]:
    failures: list[str] = []
    included = [
        (category, summary)
        for category, summary in categories.items()
        if include_category(category)
    ]
    if not included:
        return [f"{route}: no categories were measured"]
    for category, summary in included:
        first = summary["first_ttfa_ms"]
        delta = summary["first_minus_steady_ms"]
        assert isinstance(first, dict)
        assert isinstance(delta, dict)
        first_p95 = float(first["p95"])
        delta_p95 = float(delta["p95"])
        if first_p95 >= first_max_ms:
            failures.append(
                f"{route} {category}: first TTFA p95 {first_p95:.3f} ms is not < "
                f"{first_max_ms:.3f} ms"
            )
        if delta_p95 >= delta_max_ms:
            failures.append(
                f"{route} {category}: first-minus-steady p95 {delta_p95:.3f} ms "
                f"is not < {delta_max_ms:.3f} ms"
            )
    return failures


def _aggregate_latency_failures(
    first: list[float],
    deltas: list[float],
    first_max_ms: float,
    delta_max_ms: float,
    route: str,
) -> list[str]:
    if not first or not deltas:
        return [f"{route}: no complete runs were measured"]
    first_p95 = _percentile(first, 95.0)
    delta_p95 = _percentile(deltas, 95.0)
    failures: list[str] = []
    if first_p95 >= first_max_ms:
        failures.append(
            f"{route}: first TTFA p95 {first_p95:.3f} ms is not < {first_max_ms:.3f} ms"
        )
    if delta_p95 >= delta_max_ms:
        failures.append(
            f"{route}: first-minus-steady p95 {delta_p95:.3f} ms is not < "
            f"{delta_max_ms:.3f} ms"
        )
    return failures


def _expected_requests_per_run(report: dict[str, Any]) -> int:
    config = report.get("config")
    value = config.get("requests_per_run") if isinstance(config, dict) else None
    if not isinstance(value, int) or value <= 0:
        raise ValueError("restart report lacks a positive config.requests_per_run")
    return value


def _schedule_category_counts(path: Path | None) -> Counter[str]:
    if path is None:
        return Counter()
    rows = _load_jsonl(path)
    counts = Counter()
    for row in rows:
        label = row.get("label")
        if not isinstance(label, str) or not label:
            raise ValueError("schedule row lacks label")
        counts[label] += 1
    return counts


def _load_jsonl(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        item = json.loads(line)
        if not isinstance(item, dict):
            raise ValueError(f"JSONL row {line_number} must be an object")
        rows.append(item)
    return rows


def _expected_talker_prefill_length(
    category: str,
    shape: dict[str, Any],
) -> int | None:
    configured = shape.get("talker_prefill_length")
    if isinstance(configured, int) and configured > 0:
        return configured
    return _allowlist_length(category)


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
