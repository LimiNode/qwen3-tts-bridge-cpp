"""Validate a public-C++-API soak artifact against worker stderr metrics."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--worker-metrics", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--expected-requests", type=int, required=True)
    parser.add_argument("--expected-cancelled", type=int, required=True)
    parser.add_argument("--expected-cache-entries", type=int, default=6)
    parser.add_argument("--expected-first-chunk-steps", type=int)
    parser.add_argument(
        "--expected-chunk-schedule",
        type=_parse_chunk_schedule,
        default=(),
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    artifact = json.loads(args.artifact.read_text(encoding="utf-8"))
    worker_metrics_text = (
        _read_worker_metrics_text(args.worker_metrics) if args.worker_metrics else ""
    )
    expected_contracts = _manifest_contracts(args.manifest) if args.manifest else None
    report = validate_cpp_api_soak(
        artifact,
        _worker_metrics(worker_metrics_text),
        expected_requests=args.expected_requests,
        expected_cancelled=args.expected_cancelled,
        expected_cache_entries=args.expected_cache_entries,
        expected_first_chunk_steps=args.expected_first_chunk_steps,
        expected_chunk_schedule=args.expected_chunk_schedule,
        expected_contracts=expected_contracts,
    )
    report["artifact"] = str(args.artifact)
    report["worker_metrics"] = str(args.worker_metrics) if args.worker_metrics else None
    report["worker_metrics_sha256"] = hashlib.sha256(
        worker_metrics_text.encode("utf-8")
    ).hexdigest()
    report["acceptance_pass"] = not report["failures"]
    if args.output:
        args.output.write_text(json.dumps(report, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0 if report["acceptance_pass"] else 1


def _read_worker_metrics_text(path: Path) -> str:
    """Decode mixed worker stderr without losing ASCII metric lines."""

    return path.read_bytes().decode("utf-8", errors="replace")


def validate_cpp_api_soak(
    artifact: dict[str, object],
    worker_metrics: list[dict[str, object]],
    *,
    expected_requests: int,
    expected_cancelled: int,
    expected_cache_entries: int,
    expected_first_chunk_steps: int | None = None,
    expected_chunk_schedule: tuple[int, ...] = (),
    expected_contracts: dict[str, dict[str, object]] | None = None,
) -> dict[str, object]:
    failures: list[str] = []
    requests = artifact.get("requests")
    if not isinstance(requests, list):
        return {"failures": ["artifact lacks requests array"]}
    if len(requests) != expected_requests:
        failures.append(f"expected {expected_requests} requests, got {len(requests)}")

    completed = 0
    cancelled = 0
    request_ids: set[int] = set()
    requests_by_id: dict[int, dict[str, object]] = {}
    for request in requests:
        if not isinstance(request, dict):
            failures.append("request entry is not an object")
            continue
        request_id = request.get("request_id")
        if not isinstance(request_id, int):
            failures.append("request lacks numeric request_id")
            continue
        request_ids.add(request_id)
        requests_by_id[request_id] = request
        if request.get("success") is True:
            completed += 1
            if request.get("cancelled") is not False:
                failures.append(f"request {request_id}: completed request is cancelled")
            audio_chunks = request.get("audio_chunks")
            if not isinstance(audio_chunks, int) or audio_chunks < 2:
                failures.append(f"request {request_id}: completion lacks streaming PCM")
        elif request.get("cancelled") is True:
            cancelled += 1
            if request.get("audio_chunks") != 1:
                failures.append(
                    f"request {request_id}: cancellation was not after first PCM"
                )
        else:
            failures.append(f"request {request_id}: unexpected failed terminal state")

    if cancelled != expected_cancelled:
        failures.append(f"expected {expected_cancelled} cancellations, got {cancelled}")
    if completed + cancelled != len(requests):
        failures.append("terminal accounting does not cover all requests")

    embedded_metrics = _embedded_metrics(requests_by_id)
    metrics_by_request = _metrics_by_request(worker_metrics)
    for request_id, metrics in embedded_metrics.items():
        metrics_by_request.setdefault(request_id, metrics)
    chunks_by_request = _chunk_metrics_by_request(worker_metrics)
    for request_id in embedded_metrics:
        if request_id not in chunks_by_request:
            chunks_by_request[request_id] = _embedded_chunks(requests_by_id[request_id])
    worker_pids: set[int] = set()
    cache_entries: set[int] = set()
    for request_id in sorted(request_ids):
        metrics = metrics_by_request.get(request_id, {})
        request = requests_by_id[request_id]
        expected_contract = None
        if expected_contracts is not None:
            label = request.get("label")
            if not isinstance(label, str) or label not in expected_contracts:
                failures.append(f"request {request_id}: missing expected manifest category")
            else:
                expected_contract = expected_contracts[label]
                _validate_embedded_contract(request_id, request, failures)
        phases = metrics.get("request_first_chunk_engine_phases")
        if not isinstance(phases, dict):
            failures.append(f"request {request_id}: missing first-chunk metrics")
        else:
            _validate_route(
                request_id,
                phases,
                expected_cache_entries,
                expected_first_chunk_steps,
                cache_entries,
                failures,
                expected_contract,
            )
        _validate_chunk_schedule(
            request_id,
            request,
            chunks_by_request.get(request_id, []),
            metrics.get("request_finished"),
            _contract_chunk_schedule(expected_contract, expected_chunk_schedule),
            failures,
        )
        memory = metrics.get("worker_runtime_memory")
        if not isinstance(memory, dict):
            failures.append(f"request {request_id}: missing worker memory metric")
            continue
        worker_pid = memory.get("worker_pid")
        if isinstance(worker_pid, int):
            worker_pids.add(worker_pid)
        else:
            failures.append(f"request {request_id}: missing worker PID")
        for field in (
            "cuda_memory_allocated_bytes",
            "cuda_memory_reserved_bytes",
            "cuda_memory_max_reserved_bytes",
        ):
            if not isinstance(memory.get(field), int):
                failures.append(f"request {request_id}: missing {field}")

    if cache_entries != {expected_cache_entries}:
        failures.append(
            f"cache entries {sorted(cache_entries)} != {expected_cache_entries}"
        )
    if len(worker_pids) != 1:
        failures.append(f"expected one worker PID, got {sorted(worker_pids)}")
    return {
        "failures": failures,
        "completed_requests": completed,
        "cancelled_requests": cancelled,
        "cache_entries_observed": sorted(cache_entries),
        "worker_pids": sorted(worker_pids),
    }


def _manifest_contracts(path: Path) -> dict[str, dict[str, object]]:
    contracts: dict[str, dict[str, object]] = {}
    required = {
        "expected_prefill_length",
        "expected_route",
        "expected_backend",
        "expected_chunk_schedule",
    }
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"manifest line {line_number} is not an object")
        label = value.get("label")
        if not isinstance(label, str) or not label:
            raise ValueError(f"manifest line {line_number} lacks label")
        missing = required.difference(value)
        if missing:
            raise ValueError(f"manifest line {line_number} lacks {sorted(missing)}")
        contracts[label] = {
            "prefill_length": value["expected_prefill_length"],
            "route": value["expected_route"],
            "backend": value["expected_backend"],
            "chunk_schedule": value["expected_chunk_schedule"],
        }
    if not contracts:
        raise ValueError("manifest contains no contracts")
    return contracts


def _worker_metrics(stderr_text: str) -> list[dict[str, object]]:
    metrics: list[dict[str, object]] = []
    marker = "qtb_metric "
    search_start = 0
    while True:
        marker_at = stderr_text.find(marker, search_start)
        if marker_at < 0:
            return metrics
        object_start = stderr_text.find("{", marker_at + len(marker))
        if object_start < 0:
            return metrics
        object_end = _json_object_end(stderr_text, object_start)
        if object_end is None:
            search_start = object_start + 1
            continue
        try:
            payload = json.loads(
                stderr_text[object_start:object_end]
                .replace("\r", "")
                .replace("\n", "")
            )
        except json.JSONDecodeError:
            search_start = object_start + 1
            continue
        if isinstance(payload, dict):
            metrics.append(payload)
        search_start = object_end


def _json_object_end(text: str, start: int) -> int | None:
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        character = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return index + 1
    return None


def _parse_chunk_schedule(value: str) -> tuple[int, ...]:
    try:
        schedule = tuple(int(item.strip()) for item in value.split(","))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "--expected-chunk-schedule must contain integers"
        ) from exc
    if not schedule or any(item <= 0 for item in schedule):
        raise argparse.ArgumentTypeError(
            "--expected-chunk-schedule must contain positive integers"
        )
    return schedule


def _metrics_by_request(
    worker_metrics: list[dict[str, object]],
) -> dict[int, dict[str, dict[str, object]]]:
    grouped: dict[int, dict[str, dict[str, object]]] = {}
    for metric in worker_metrics:
        request_id = metric.get("request_id")
        event = metric.get("event")
        if not isinstance(request_id, int) or not isinstance(event, str):
            continue
        grouped.setdefault(request_id, {}).setdefault(event, metric)
    return grouped


def _chunk_metrics_by_request(
    worker_metrics: list[dict[str, object]],
) -> dict[int, list[dict[str, object]]]:
    grouped: dict[int, list[dict[str, object]]] = {}
    for metric in worker_metrics:
        if metric.get("event") != "request_pcm_chunk":
            continue
        request_id = metric.get("request_id")
        chunk_index = metric.get("chunk_index")
        if not isinstance(request_id, int) or not isinstance(chunk_index, int):
            continue
        grouped.setdefault(request_id, []).append(metric)
    for metrics in grouped.values():
        metrics.sort(key=lambda metric: int(metric["chunk_index"]))
    return grouped


def _embedded_metrics(
    requests_by_id: dict[int, dict[str, object]],
) -> dict[int, dict[str, dict[str, object]]]:
    grouped: dict[int, dict[str, dict[str, object]]] = {}
    for request_id, request in requests_by_id.items():
        telemetry = request.get("worker_telemetry")
        if not isinstance(telemetry, dict):
            continue
        events: dict[str, dict[str, object]] = {}
        mappings = {
            "first_chunk_phases": "request_first_chunk_engine_phases",
            "generation_trace": "request_generation_trace",
            "finished": "request_finished",
            "runtime_memory": "worker_runtime_memory",
        }
        for key, event in mappings.items():
            value = telemetry.get(key)
            if isinstance(value, dict):
                events[event] = value
        if events:
            grouped[request_id] = events
    return grouped


def _embedded_chunks(request: dict[str, object]) -> list[dict[str, object]]:
    telemetry = request.get("worker_telemetry")
    if not isinstance(telemetry, dict):
        return []
    telemetry_chunks = telemetry.get("pcm_chunks")
    if isinstance(telemetry_chunks, list):
        return [chunk for chunk in telemetry_chunks if isinstance(chunk, dict)]
    return []


def _validate_embedded_contract(
    request_id: int,
    request: dict[str, object],
    failures: list[str],
) -> None:
    contract = request.get("manifest_contract")
    if not isinstance(contract, dict) or contract.get("checked") is not True:
        failures.append(f"request {request_id}: C++ manifest contract was not checked")
        return
    if contract.get("valid") is not True:
        failures.append(f"request {request_id}: C++ manifest contract is invalid")


def _contract_chunk_schedule(
    contract: dict[str, object] | None,
    fallback: tuple[int, ...],
) -> tuple[int, ...]:
    if contract is None:
        return fallback
    schedule = contract.get("chunk_schedule")
    if not isinstance(schedule, list) or not all(
        isinstance(value, int) and value > 0 for value in schedule
    ):
        return ()
    return tuple(schedule)


def _validate_chunk_schedule(
    request_id: int,
    request: dict[str, object],
    worker_chunks: list[dict[str, object]],
    terminal_metric: object,
    expected_schedule: tuple[int, ...],
    failures: list[str],
) -> None:
    if not expected_schedule:
        return
    client_chunks = request.get("chunks")
    audio_chunks = request.get("audio_chunks")
    if not isinstance(client_chunks, list) or not isinstance(audio_chunks, int):
        failures.append(f"request {request_id}: missing C++ chunk observations")
        return
    if len(client_chunks) != audio_chunks:
        failures.append(f"request {request_id}: C++ chunk count does not match audio")
    if len(worker_chunks) != audio_chunks:
        failures.append(
            f"request {request_id}: worker chunk count does not match audio"
        )
        return
    if request.get("success") is True and audio_chunks < len(expected_schedule):
        failures.append(f"request {request_id}: completion lacks scheduled prefix")

    for index, chunk in enumerate(worker_chunks):
        target = expected_schedule[min(index, len(expected_schedule) - 1)]
        actual = chunk.get("chunk_steps")
        reported_target = chunk.get("chunk_target_steps")
        is_final = chunk.get("is_final")
        if reported_target != target:
            failures.append(f"request {request_id}: chunk {index} target != {target}")
        if not isinstance(actual, int) or actual <= 0 or actual > target:
            failures.append(f"request {request_id}: chunk {index} has invalid steps")
            continue
        is_terminal_audio = request.get("success") is True and index + 1 == audio_chunks
        if is_terminal_audio:
            terminal_index = (
                terminal_metric.get("final_pcm_chunk_index")
                if isinstance(terminal_metric, dict)
                else None
            )
            if is_final is not True and terminal_index != index:
                failures.append(
                    f"request {request_id}: final chunk lacks terminal accounting"
                )
        elif actual != target:
            failures.append(
                f"request {request_id}: chunk {index} is short before terminal"
            )
        client_chunk = client_chunks[index] if index < len(client_chunks) else None
        if not isinstance(client_chunk, dict):
            continue
        for key in ("arrival_ms", "audio_duration_ms"):
            value = client_chunk.get(key)
            if not isinstance(value, (int, float)) or value <= 0:
                failures.append(f"request {request_id}: chunk {index} lacks {key}")


def _validate_route(
    request_id: int,
    phases: dict[str, object],
    expected_cache_entries: int,
    expected_first_chunk_steps: int | None,
    cache_entries: set[int],
    failures: list[str],
    expected_contract: dict[str, object] | None = None,
) -> None:
    expected = {
        "prefill_compile_attempted": False,
        "prefill_compile_fallback": False,
        "prefill_require_precompiled": True,
        "prefill_dynamo_unique_graphs_delta": 0,
        "prefill_compile_cache_entries_delta": 0,
    }
    route = "compiled_allowlist"
    backend = "compile_reduce_overhead"
    if expected_contract is not None:
        expected_length = expected_contract.get("prefill_length")
        if not isinstance(expected_length, int):
            failures.append(f"request {request_id}: manifest prefill length is invalid")
        elif phases.get("talker_prefill_length") != expected_length:
            failures.append(
                f"request {request_id}: expected talker_prefill_length={expected_length!r}"
            )
        route_value = expected_contract.get("route")
        backend_value = expected_contract.get("backend")
        if isinstance(route_value, str):
            route = route_value
        if isinstance(backend_value, str):
            backend = backend_value
    expected["prefill_shape_policy"] = route
    expected["prefill_backend_used"] = backend
    expected["prefill_compile_cache_hit"] = route == "compiled_allowlist"
    expected["prefill_shape_allowlist_hit"] = route == "compiled_allowlist"
    for key, value in expected.items():
        if phases.get(key) != value:
            failures.append(f"request {request_id}: expected {key}={value!r}")
    entries = phases.get("prefill_compile_cache_entries")
    if isinstance(entries, int):
        cache_entries.add(entries)
    else:
        failures.append(f"request {request_id}: missing cache entry count")
    if expected_first_chunk_steps is not None and expected_contract is None:
        for key in ("chunk_steps", "chunk_target_steps"):
            if phases.get(key) != expected_first_chunk_steps:
                failures.append(
                    f"request {request_id}: expected {key}="
                    f"{expected_first_chunk_steps!r}"
                )


if __name__ == "__main__":
    raise SystemExit(main())
