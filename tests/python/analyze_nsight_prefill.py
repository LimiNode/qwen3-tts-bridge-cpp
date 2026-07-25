"""Summarize Nsight Systems CUDA/NVTX prefill traces."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path


LAUNCH_API_PREFIXES = ("cudaLaunchKernel", "cuLaunchKernel")
PHASE_PREFIX = "qtb_prefill_"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--first", type=Path, required=True)
    parser.add_argument("--steady", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    first = _analyze_trace(args.first)
    steady = _analyze_trace(args.steady)
    report = {
        "artifact_schema_version": 1,
        "units": "milliseconds unless stated otherwise",
        "note": (
            "queue_ms is kernel.start - matched launch API end for matching "
            "CUPTI correlation IDs; host_or_unattributed_wall_ms is an outer "
            "range minus GPU active-time sum, not pure queue or gap time"
        ),
        "first_user": first,
        "steady": steady,
        "deltas_first_minus_steady": _deltas(first, steady),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report["deltas_first_minus_steady"], sort_keys=True))
    return 0


def _analyze_trace(path: Path) -> dict[str, object]:
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    try:
        strings = _strings(con)
        api_rows = _api_rows(con, strings)
        kernel_rows = _kernel_rows(con, strings)
        memcpy_rows = _copy_rows(con, "CUPTI_ACTIVITY_KIND_MEMCPY")
        memset_rows = _copy_rows(con, "CUPTI_ACTIVITY_KIND_MEMSET")
        nvtx_ranges = _nvtx_ranges(con, strings)
        launch_rows = [
            row for row in api_rows if _is_launch_api_name(str(row["name"]))
        ]
        launch_by_corr = {
            int(row["correlationId"]): row
            for row in launch_rows
            if row["correlationId"] is not None
        }
        queue_ms = []
        matched_kernel_ms = []
        for row in kernel_rows:
            launch = launch_by_corr.get(int(row["correlationId"]))
            if launch is None:
                continue
            queue_ms.append(_ns_to_ms(row["start"] - launch["end"]))
            matched_kernel_ms.append(row["duration_ms"])

        outer = _outer_range(nvtx_ranges)
        gpu_active_ms = sum(row["duration_ms"] for row in kernel_rows)
        gpu_active_ms += sum(row["duration_ms"] for row in memcpy_rows)
        gpu_active_ms += sum(row["duration_ms"] for row in memset_rows)
        phase_summaries = _phase_summaries(kernel_rows, nvtx_ranges)
        return {
            "source": str(path),
            "outer_range": outer,
            "cuda_api": {
                "all_calls": len(api_rows),
                "all_duration_ms": _summary([row["duration_ms"] for row in api_rows]),
                "launch_calls": len(launch_rows),
                "launch_duration_ms": _summary(
                    [row["duration_ms"] for row in launch_rows]
                ),
                "interval_union_ms": _interval_union_ms(api_rows),
            },
            "cuda_kernel": {
                "count": len(kernel_rows),
                "duration_ms": _summary([row["duration_ms"] for row in kernel_rows]),
                "sum_ms": sum(row["duration_ms"] for row in kernel_rows),
                "matched_launch_count": len(matched_kernel_ms),
            },
            "cuda_queue": {
                "count": len(queue_ms),
                "positive_count": sum(1 for value in queue_ms if value > 0.0),
                "duration_ms": _summary(queue_ms),
            },
            "cuda_memcpy": {
                "count": len(memcpy_rows),
                "sum_ms": sum(row["duration_ms"] for row in memcpy_rows),
            },
            "cuda_memset": {
                "count": len(memset_rows),
                "sum_ms": sum(row["duration_ms"] for row in memset_rows),
            },
            "gpu_active_sum_ms": gpu_active_ms,
            "host_or_unattributed_wall_ms": (
                None
                if outer is None
                else float(outer["duration_ms"]) - gpu_active_ms
            ),
            "kernel_by_nvtx_phase": phase_summaries,
        }
    finally:
        con.close()


def _strings(con: sqlite3.Connection) -> dict[int, str]:
    return {
        int(row["id"]): str(row["value"])
        for row in con.execute("select id, value from StringIds")
    }


def _is_launch_api_name(name: str) -> bool:
    return name.startswith(LAUNCH_API_PREFIXES)


def _api_rows(
    con: sqlite3.Connection,
    strings: dict[int, str],
) -> list[dict[str, object]]:
    rows = []
    for row in con.execute(
        """
        select start, end, globalTid, correlationId, nameId
        from CUPTI_ACTIVITY_KIND_RUNTIME
        """
    ):
        rows.append(
            {
                "start": int(row["start"]),
                "end": int(row["end"]),
                "globalTid": row["globalTid"],
                "correlationId": row["correlationId"],
                "name": strings.get(int(row["nameId"]), str(row["nameId"])),
                "duration_ms": _ns_to_ms(int(row["end"]) - int(row["start"])),
            }
        )
    return rows


def _kernel_rows(
    con: sqlite3.Connection,
    strings: dict[int, str],
) -> list[dict[str, object]]:
    rows = []
    for row in con.execute(
        """
        select start, end, streamId, correlationId, demangledName, shortName
        from CUPTI_ACTIVITY_KIND_KERNEL
        """
    ):
        name_id = row["demangledName"]
        short_id = row["shortName"]
        rows.append(
            {
                "start": int(row["start"]),
                "end": int(row["end"]),
                "streamId": row["streamId"],
                "correlationId": row["correlationId"],
                "name": strings.get(int(name_id), str(name_id))
                if name_id is not None
                else None,
                "short_name": strings.get(int(short_id), str(short_id))
                if short_id is not None
                else None,
                "duration_ms": _ns_to_ms(int(row["end"]) - int(row["start"])),
            }
        )
    return rows


def _copy_rows(
    con: sqlite3.Connection,
    table: str,
) -> list[dict[str, object]]:
    rows = []
    for row in con.execute(f"select start, end from {table}"):
        rows.append(
            {
                "start": int(row["start"]),
                "end": int(row["end"]),
                "duration_ms": _ns_to_ms(int(row["end"]) - int(row["start"])),
            }
        )
    return rows


def _nvtx_ranges(
    con: sqlite3.Connection,
    strings: dict[int, str],
) -> list[dict[str, object]]:
    ranges = []
    for row in con.execute(
        """
        select start, end, text, textId
        from NVTX_EVENTS
        where end is not null
        """
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


def _outer_range(ranges: list[dict[str, object]]) -> dict[str, object] | None:
    candidates = [
        item
        for item in ranges
        if str(item["name"]).startswith("qtb_profile_")
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: float(item["duration_ms"]))


def _phase_summaries(
    kernel_rows: list[dict[str, object]],
    ranges: list[dict[str, object]],
) -> dict[str, object]:
    result = {}
    for phase in ranges:
        name = str(phase["name"])
        if not name.startswith(PHASE_PREFIX):
            continue
        phase_kernels = [
            row
            for row in kernel_rows
            if int(row["start"]) >= int(phase["start"])
            and int(row["end"]) <= int(phase["end"])
        ]
        result[name] = {
            "range_duration_ms": phase["duration_ms"],
            "kernel_count": len(phase_kernels),
            "kernel_sum_ms": sum(row["duration_ms"] for row in phase_kernels),
            "kernel_duration_ms": _summary(
                [row["duration_ms"] for row in phase_kernels]
            ),
        }
    return result


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


def _summary(values: list[float]) -> dict[str, float] | None:
    clean_values = sorted(value for value in values if value is not None)
    if not clean_values:
        return None
    return {
        "min": clean_values[0],
        "p50": _percentile(clean_values, 50.0),
        "p95": _percentile(clean_values, 95.0),
        "max": clean_values[-1],
        "sum": sum(clean_values),
    }


def _percentile(values: list[float], percentile: float) -> float:
    if len(values) == 1:
        return values[0]
    rank = percentile / 100.0 * (len(values) - 1)
    low = int(rank)
    high = min(low + 1, len(values) - 1)
    fraction = rank - low
    return values[low] * (1.0 - fraction) + values[high] * fraction


def _deltas(left: dict[str, object], right: dict[str, object]) -> dict[str, object]:
    return {
        "outer_range_duration_ms": _nested_delta(left, right, ("outer_range", "duration_ms")),
        "cuda_api_interval_union_ms": _nested_delta(
            left,
            right,
            ("cuda_api", "interval_union_ms"),
        ),
        "cuda_api_launch_sum_ms": _nested_delta(
            left,
            right,
            ("cuda_api", "launch_duration_ms", "sum"),
        ),
        "cuda_kernel_sum_ms": _nested_delta(left, right, ("cuda_kernel", "sum_ms")),
        "cuda_queue_p95_ms": _nested_delta(
            left,
            right,
            ("cuda_queue", "duration_ms", "p95"),
        ),
        "host_or_unattributed_wall_ms": _nested_delta(
            left,
            right,
            ("host_or_unattributed_wall_ms",),
        ),
    }


def _nested_delta(
    left: dict[str, object],
    right: dict[str, object],
    path: tuple[str, ...],
) -> float | None:
    left_value = _nested_value(left, path)
    right_value = _nested_value(right, path)
    if isinstance(left_value, (int, float)) and isinstance(right_value, (int, float)):
        return float(left_value) - float(right_value)
    return None


def _nested_value(value: object, path: tuple[str, ...]) -> object:
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _ns_to_ms(value: int | float) -> float:
    return float(value) / 1_000_000.0


if __name__ == "__main__":
    raise SystemExit(main())
