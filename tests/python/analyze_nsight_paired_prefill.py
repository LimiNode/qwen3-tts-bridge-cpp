"""Summarize same-process paired Nsight prefill captures."""

# pyright: reportArgumentType=false

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

PREFILL_RANGE_NAMES = (
    "qtb_profile_first_user_prefill",
    "qtb_profile_steady_prefill",
)
PAIR_RANGE_NAME = "qtb_profile_first_steady_pair"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    traces = [
        _analyze_trace(path)
        for path in sorted(args.input_dir.glob("paired-prefill-*.sqlite"))
    ]
    report = {
        "artifact_schema_version": 1,
        "units": "milliseconds unless stated otherwise",
        "trace_count": len(traces),
        "traces": traces,
        "tail_trace_count_gt20ms": sum(
            1
            for trace in traces
            if _number(trace.get("first_minus_steady_prefill_range_ms")) > 20.0
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "trace_count": report["trace_count"],
                "tail_trace_count_gt20ms": report["tail_trace_count_gt20ms"],
                "deltas": [
                    trace["first_minus_steady_prefill_range_ms"]
                    for trace in traces
                ],
            },
            sort_keys=True,
        )
    )
    return 0


def _analyze_trace(path: Path) -> dict[str, object]:
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    try:
        strings = _strings(con)
        ranges = _nvtx_ranges(con, strings)
        api_rows = _api_rows(con, strings)
        kernel_rows = _kernel_rows(con)
        pair = _range_by_name(ranges, PAIR_RANGE_NAME)
        prefill = {
            name: _range_summary(
                _range_by_name(ranges, name),
                api_rows,
                kernel_rows,
            )
            for name in PREFILL_RANGE_NAMES
        }
        first = prefill["qtb_profile_first_user_prefill"]
        steady = prefill["qtb_profile_steady_prefill"]
        return {
            "source": str(path),
            "pair_range_ms": None if pair is None else pair["duration_ms"],
            "prefill_ranges": prefill,
            "first_minus_steady_prefill_range_ms": _delta(
                first,
                steady,
                "range_ms",
            ),
            "first_minus_steady_launch_api_sum_ms": _delta(
                first,
                steady,
                "launch_api_sum_ms",
            ),
            "first_minus_steady_kernel_sum_ms": _delta(
                first,
                steady,
                "kernel_sum_ms",
            ),
        }
    finally:
        con.close()


def _range_summary(
    range_row: dict[str, object] | None,
    api_rows: list[dict[str, object]],
    kernel_rows: list[dict[str, object]],
) -> dict[str, object]:
    if range_row is None:
        return {
            "range_ms": None,
            "launch_api_count": 0,
            "launch_api_sum_ms": 0.0,
            "kernel_count": 0,
            "kernel_sum_ms": 0.0,
        }
    start = int(range_row["start"])
    end = int(range_row["end"])
    api = [
        row
        for row in api_rows
        if start <= int(row["start"]) and int(row["end"]) <= end
    ]
    launches = [
        row
        for row in api
        if str(row["name"]).startswith(("cudaLaunchKernel", "cuLaunchKernel"))
    ]
    kernels = [
        row
        for row in kernel_rows
        if start <= int(row["start"]) and int(row["end"]) <= end
    ]
    return {
        "range_ms": range_row["duration_ms"],
        "cuda_api_count": len(api),
        "cuda_api_union_ms": _interval_union_ms(api),
        "launch_api_count": len(launches),
        "launch_api_sum_ms": sum(float(row["duration_ms"]) for row in launches),
        "kernel_count": len(kernels),
        "kernel_sum_ms": sum(float(row["duration_ms"]) for row in kernels),
    }


def _strings(con: sqlite3.Connection) -> dict[int, str]:
    return {
        int(row["id"]): str(row["value"])
        for row in con.execute("select id, value from StringIds")
    }


def _nvtx_ranges(
    con: sqlite3.Connection,
    strings: dict[int, str],
) -> list[dict[str, object]]:
    ranges = []
    for row in con.execute(
        "select start, end, text, textId from NVTX_EVENTS where end is not null"
    ):
        name = row["text"]
        if name is None and row["textId"] is not None:
            name = strings.get(int(row["textId"]))
        if not isinstance(name, str):
            continue
        ranges.append(
            {
                "name": name,
                "start": int(row["start"]),
                "end": int(row["end"]),
                "duration_ms": _ns_to_ms(int(row["end"]) - int(row["start"])),
            }
        )
    return ranges


def _api_rows(
    con: sqlite3.Connection,
    strings: dict[int, str],
) -> list[dict[str, object]]:
    rows = []
    for row in con.execute(
        """
        select start, end, nameId
        from CUPTI_ACTIVITY_KIND_RUNTIME
        """
    ):
        rows.append(
            {
                "start": int(row["start"]),
                "end": int(row["end"]),
                "name": strings.get(int(row["nameId"]), str(row["nameId"])),
                "duration_ms": _ns_to_ms(int(row["end"]) - int(row["start"])),
            }
        )
    return rows


def _kernel_rows(con: sqlite3.Connection) -> list[dict[str, object]]:
    rows = []
    for row in con.execute("select start, end from CUPTI_ACTIVITY_KIND_KERNEL"):
        rows.append(
            {
                "start": int(row["start"]),
                "end": int(row["end"]),
                "duration_ms": _ns_to_ms(int(row["end"]) - int(row["start"])),
            }
        )
    return rows


def _range_by_name(
    ranges: list[dict[str, object]],
    name: str,
) -> dict[str, object] | None:
    matches = [item for item in ranges if item["name"] == name]
    if not matches:
        return None
    return max(matches, key=lambda item: float(item["duration_ms"]))


def _interval_union_ms(rows: list[dict[str, object]]) -> float:
    intervals = sorted((int(row["start"]), int(row["end"])) for row in rows)
    if not intervals:
        return 0.0
    total = 0
    cur_start, cur_end = intervals[0]
    for start, end in intervals[1:]:
        if start <= cur_end:
            cur_end = max(cur_end, end)
            continue
        total += cur_end - cur_start
        cur_start, cur_end = start, end
    total += cur_end - cur_start
    return _ns_to_ms(total)


def _delta(
    first: dict[str, object],
    steady: dict[str, object],
    key: str,
) -> float | None:
    first_value = first.get(key)
    steady_value = steady.get(key)
    if isinstance(first_value, (int, float)) and isinstance(steady_value, (int, float)):
        return float(first_value) - float(steady_value)
    return None


def _number(value: object) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


def _ns_to_ms(value: int | float) -> float:
    return float(value) / 1_000_000.0


if __name__ == "__main__":
    raise SystemExit(main())
