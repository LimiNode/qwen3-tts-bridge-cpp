"""Export anonymous canary-v2.1 JSONL from worker ``qtb_metric`` diagnostics."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

_METRIC_PREFIX = "qtb_metric "
_SCHEMA_VERSION = 3


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--runtime-profile-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    records = _export_records(
        args.input.read_text(encoding="utf-8").splitlines(),
        args.runtime_profile_id,
    )
    if not records:
        raise RuntimeError("worker diagnostics contain no terminal requests")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )
    print(json.dumps({"record_count": len(records), "output": str(args.output)}))
    return 0


def _export_records(
    lines: list[str],
    runtime_profile_id: str,
) -> list[dict[str, object]]:
    routes: dict[int, dict[str, object]] = {}
    records = []
    for line_number, line in enumerate(lines, 1):
        metric = _parse_metric(line, line_number)
        if metric is None:
            continue
        event = metric.get("event")
        request_id = metric.get("request_id")
        if not isinstance(request_id, int) or isinstance(request_id, bool):
            continue
        if event == "request_first_chunk_engine_phases":
            routes.setdefault(request_id, _route_fields(metric, line_number))
        elif event == "request_finished":
            records.append(
                _terminal_record(
                    metric,
                    routes.pop(request_id, None),
                    runtime_profile_id,
                    line_number,
                )
            )
    return records


def _parse_metric(line: str, line_number: int) -> dict[str, object] | None:
    if not line.startswith(_METRIC_PREFIX):
        return None
    try:
        value = json.loads(line.removeprefix(_METRIC_PREFIX))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"line {line_number}: malformed qtb_metric JSON") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"line {line_number}: qtb_metric must be an object")
    return value


def _route_fields(metric: dict[str, object], line_number: int) -> dict[str, object]:
    required = {
        "talker_prefill_length",
        "prefill_shape_policy",
        "prefill_backend_used",
        "selected_chunk_schedule",
        "prefill_compile_cache_hit",
        "prefill_compile_attempted",
        "prefill_compile_fallback",
    }
    missing = sorted(key for key in required if key not in metric)
    if missing:
        raise RuntimeError(
            f"line {line_number}: first-chunk metric lacks {', '.join(missing)}"
        )
    return {
        "talker_prefill_length": metric["talker_prefill_length"],
        "prefill_shape_policy": metric["prefill_shape_policy"],
        "prefill_backend_used": metric["prefill_backend_used"],
        "selected_chunk_schedule": metric["selected_chunk_schedule"],
        "prefill_cache_hit": metric["prefill_compile_cache_hit"],
        "prefill_compile_attempted": metric["prefill_compile_attempted"],
        "prefill_compile_fallback": metric["prefill_compile_fallback"],
    }


def _terminal_record(
    metric: dict[str, object],
    route: dict[str, object] | None,
    runtime_profile_id: str,
    line_number: int,
) -> dict[str, object]:
    terminal_state = metric.get("terminal_state")
    outcome = _outcome(metric, terminal_state, line_number)
    record: dict[str, object] = {
        "schema_version": _SCHEMA_VERSION,
        "runtime_profile_id": runtime_profile_id,
        "request_outcome": outcome,
        "route_decision_made": route is not None,
    }
    if route is not None:
        record.update(route)
    if outcome == "completed":
        record.update(_completed_latency(metric, line_number))
    return record


def _outcome(
    metric: dict[str, object], terminal_state: object, line_number: int
) -> str:
    if terminal_state == "completed":
        return "completed"
    if terminal_state == "failed":
        return "failed"
    if terminal_state == "cancelled":
        return (
            "cancelled_after_audio"
            if "first_audio_ms" in metric
            else "cancelled_before_audio"
        )
    raise RuntimeError(f"line {line_number}: unknown terminal_state")


def _completed_latency(metric: dict[str, object], line_number: int) -> dict[str, float]:
    values = {}
    for key in ("first_audio_ms", "synthesis_ms", "audio_duration_ms"):
        value = metric.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise RuntimeError(f"line {line_number}: completed metric lacks {key}")
        values[key] = float(value)
    if values["synthesis_ms"] <= 0.0 or values["audio_duration_ms"] <= 0.0:
        raise RuntimeError(f"line {line_number}: completed metric has invalid duration")
    return {
        "first_audio_ms": values["first_audio_ms"],
        "completed_ms": values["synthesis_ms"],
        "inverse_rtf": values["audio_duration_ms"] / values["synthesis_ms"],
    }


if __name__ == "__main__":
    raise SystemExit(main())
