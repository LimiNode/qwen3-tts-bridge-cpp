"""Export anonymous, provenance-pinned canary JSONL from worker diagnostics."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Mapping

_METRIC_PREFIX = "qtb_metric "
_SCHEMA_VERSION = 3
_EXPORT_SCHEMA_VERSION = 1
_EVIDENCE_SOURCES = {"synthetic_proxy", "internal_real_traffic"}
_REQUEST_EVENTS = {
    "request_received",
    "request_first_chunk_engine_phases",
    "request_finished",
}
_PROVENANCE_FIELDS = {
    "runtime_profile_id",
    "bridge_commit",
    "faster_wheel_sha256",
    "compiled_allowlist_manifest_sha256",
}


@dataclass(frozen=True, slots=True)
class ExportResult:
    """Anonymous records and the local accounting required to trust them."""

    records: list[dict[str, object]]
    summary: dict[str, object]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--runtime-profile-manifest", type=Path, required=True)
    parser.add_argument("--compiled-allowlist-manifest", type=Path, required=True)
    parser.add_argument("--runtime-profile-id")
    parser.add_argument(
        "--evidence-source",
        choices=sorted(_EVIDENCE_SOURCES),
        required=True,
    )
    parser.add_argument("--allow-open-requests", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary-output", type=Path)
    args = parser.parse_args()

    expected = _expected_provenance(
        args.runtime_profile_manifest,
        args.compiled_allowlist_manifest,
    )
    if args.runtime_profile_id is not None and args.runtime_profile_id != expected[
        "runtime_profile_id"
    ]:
        parser.error("--runtime-profile-id does not match the runtime profile manifest")
    result = _export(
        args.input.read_text(encoding="utf-8", errors="replace").splitlines(),
        expected,
        args.evidence_source,
        allow_open_requests=args.allow_open_requests,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in result.records),
        encoding="utf-8",
    )
    summary_output = args.summary_output or args.output.with_suffix(
        ".export-summary.json"
    )
    summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary_output.write_text(
        json.dumps(result.summary, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps({**result.summary, "output": str(args.output)}, sort_keys=True))
    return 0 if result.summary["integrity_valid"] else 1


def _export(
    lines: list[str],
    expected_provenance: Mapping[str, str],
    evidence_source: str,
    *,
    allow_open_requests: bool,
) -> ExportResult:
    accepted: set[int] = set()
    terminals: set[int] = set()
    routes: dict[int, dict[str, object]] = {}
    records: list[dict[str, object]] = []
    orphan_request_ids: set[int] = set()
    counters: Counter[str] = Counter()
    worker_provenance: dict[str, str] | None = None

    for line_number, line in enumerate(lines, 1):
        metric = _parse_metric(line, line_number)
        if metric is None:
            continue
        event = metric.get("event")
        if event == "canary_runtime_provenance":
            provenance = _provenance_fields(metric)
            if provenance is None:
                counters["ignored_metric_count"] += 1
            elif worker_provenance is not None:
                counters["duplicate_provenance_count"] += 1
            else:
                worker_provenance = provenance
            continue
        if event not in _REQUEST_EVENTS:
            continue
        request_id = _request_id(metric)
        if request_id is None:
            counters["ignored_metric_count"] += 1
            continue
        if event == "request_received":
            if request_id in accepted:
                counters["duplicate_accepted_request_count"] += 1
            else:
                accepted.add(request_id)
            continue
        if request_id not in accepted:
            orphan_request_ids.add(request_id)
            continue
        if event == "request_first_chunk_engine_phases":
            if request_id in routes:
                counters["duplicate_route_count"] += 1
                continue
            try:
                routes[request_id] = _route_fields(metric, line_number)
            except RuntimeError:
                counters["ignored_metric_count"] += 1
            continue
        if request_id in terminals:
            counters["duplicate_terminal_count"] += 1
            continue
        try:
            record = _terminal_record(
                metric,
                routes.get(request_id),
                expected_provenance["runtime_profile_id"],
                evidence_source,
                line_number,
            )
        except RuntimeError:
            counters["ignored_metric_count"] += 1
            continue
        terminals.add(request_id)
        records.append(record)

    open_request_count = len(accepted - terminals)
    provenance_matches = worker_provenance == dict(expected_provenance)
    integrity_valid = (
        worker_provenance is not None
        and provenance_matches
        and counters["duplicate_provenance_count"] == 0
        and counters["duplicate_accepted_request_count"] == 0
        and counters["duplicate_route_count"] == 0
        and counters["duplicate_terminal_count"] == 0
        and counters["ignored_metric_count"] == 0
        and not orphan_request_ids
        and (allow_open_requests or open_request_count == 0)
        and len(accepted) == len(terminals) + open_request_count
    )
    summary = {
        "export_schema_version": _EXPORT_SCHEMA_VERSION,
        "evidence_source": evidence_source,
        "record_count": len(records),
        "accepted_request_count": len(accepted),
        "terminal_request_count": len(terminals),
        "open_request_count": open_request_count,
        "allow_open_requests": allow_open_requests,
        "orphan_request_count": len(orphan_request_ids),
        "duplicate_route_count": counters["duplicate_route_count"],
        "duplicate_terminal_count": counters["duplicate_terminal_count"],
        "duplicate_accepted_request_count": counters[
            "duplicate_accepted_request_count"
        ],
        "duplicate_provenance_count": counters["duplicate_provenance_count"],
        "ignored_metric_count": counters["ignored_metric_count"],
        "worker_provenance_present": worker_provenance is not None,
        "worker_provenance_matches_manifest": provenance_matches,
        "integrity_valid": integrity_valid,
    }
    return ExportResult(records=records, summary=summary)


def _expected_provenance(
    runtime_profile_path: Path,
    allowlist_path: Path,
) -> dict[str, str]:
    runtime_profile = _load_object(runtime_profile_path, "runtime profile manifest")
    allowlist_sha256 = sha256(allowlist_path.read_bytes()).hexdigest()
    missing = sorted(_PROVENANCE_FIELDS.difference(runtime_profile))
    if missing:
        raise RuntimeError("runtime profile manifest is missing " + ", ".join(missing))
    if runtime_profile["compiled_allowlist_manifest_sha256"] != allowlist_sha256:
        raise RuntimeError("runtime profile manifest does not pin the allowlist SHA")
    values = {key: runtime_profile[key] for key in _PROVENANCE_FIELDS}
    if not all(isinstance(value, str) and value for value in values.values()):
        raise RuntimeError("runtime profile manifest has invalid provenance")
    return {key: str(value) for key, value in values.items()}


def _load_object(path: Path, name: str) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise RuntimeError(f"cannot read {name}: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{name} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"{name} must contain an object")
    return value


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


def _request_id(metric: Mapping[str, object]) -> int | None:
    value = metric.get("request_id")
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        return None
    return value


def _provenance_fields(metric: Mapping[str, object]) -> dict[str, str] | None:
    values = {key: metric.get(key) for key in _PROVENANCE_FIELDS}
    if not all(isinstance(value, str) and value for value in values.values()):
        return None
    return {key: str(value) for key, value in values.items()}


def _route_fields(metric: Mapping[str, object], line_number: int) -> dict[str, object]:
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
    metric: Mapping[str, object],
    route: Mapping[str, object] | None,
    runtime_profile_id: str,
    evidence_source: str,
    line_number: int,
) -> dict[str, object]:
    outcome = _outcome(metric, metric.get("terminal_state"), line_number)
    record: dict[str, object] = {
        "schema_version": _SCHEMA_VERSION,
        "runtime_profile_id": runtime_profile_id,
        "evidence_source": evidence_source,
        "request_outcome": outcome,
        "route_decision_made": route is not None,
    }
    if route is not None:
        record.update(route)
    if outcome == "completed":
        record.update(_completed_latency(metric, line_number))
    return record


def _outcome(
    metric: Mapping[str, object], terminal_state: object, line_number: int
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


def _completed_latency(
    metric: Mapping[str, object], line_number: int
) -> dict[str, float]:
    values: dict[str, float] = {}
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
