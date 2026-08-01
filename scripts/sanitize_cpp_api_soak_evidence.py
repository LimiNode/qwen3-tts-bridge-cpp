"""Build a privacy-minimized C++ API soak artifact and canonical metric sidecar."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

try:
    from scripts.validate_cpp_api_soak import _worker_metrics
except ModuleNotFoundError:
    from validate_cpp_api_soak import _worker_metrics

_SANITIZATION_SCHEMA_VERSION = 1
_FIRST_CHUNK_FIELDS = {
    "event",
    "request_id",
    "talker_prefill_length",
    "prefill_backend_used",
    "prefill_compile_attempted",
    "prefill_compile_cache_entries",
    "prefill_compile_cache_entries_delta",
    "prefill_compile_cache_hit",
    "prefill_compile_fallback",
    "prefill_dynamo_unique_graphs_delta",
    "prefill_require_precompiled",
    "prefill_shape_allowlist_hit",
    "prefill_shape_policy",
}
_PCM_FIELDS = {
    "event",
    "request_id",
    "chunk_index",
    "chunk_steps",
    "chunk_target_steps",
    "is_final",
}
_FINISHED_FIELDS = {
    "event",
    "request_id",
    "terminal_state",
    "final_pcm_chunk_index",
}
_MEMORY_FIELDS = {
    "event",
    "request_id",
    "terminal_state",
    "cuda_memory_allocated_bytes",
    "cuda_memory_reserved_bytes",
    "cuda_memory_max_reserved_bytes",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--worker-stderr", type=Path, required=True)
    parser.add_argument("--artifact-output", type=Path, required=True)
    parser.add_argument("--metrics-output", type=Path, required=True)
    parser.add_argument("--manifest-output", type=Path, required=True)
    args = parser.parse_args()

    artifact_bytes = args.artifact.read_bytes()
    stderr_bytes = args.worker_stderr.read_bytes()
    artifact = _load_object(artifact_bytes, "artifact")
    metrics = _worker_metrics(stderr_bytes.decode("utf-8", errors="replace"))
    sanitized_artifact, request_id_map = _sanitize_artifact(artifact)
    sanitized_metrics = _sanitize_worker_metrics(metrics, request_id_map)
    artifact_output = _json_bytes(sanitized_artifact)
    metrics_output = _jsonl_bytes(sanitized_metrics)
    _write_bytes(args.artifact_output, artifact_output)
    _write_bytes(args.metrics_output, metrics_output)
    _write_bytes(
        args.manifest_output,
        _json_bytes(
            {
                "cpp_api_soak_sanitization_schema_version": (
                    _SANITIZATION_SCHEMA_VERSION
                ),
                "source_artifact_sha256": _sha256(artifact_bytes),
                "source_worker_stderr_sha256": _sha256(stderr_bytes),
                "sanitized_artifact_sha256": _sha256(artifact_output),
                "sanitized_worker_metrics_sha256": _sha256(metrics_output),
                "request_count": len(request_id_map),
                "metric_count": len(sanitized_metrics),
                "request_id_policy": "deterministic_benchmark_ordinals",
                "worker_pid_policy": "replaced_with_constant_one",
                "excluded_fields": [
                    "request_text",
                    "instructions",
                    "absolute_paths",
                    "native_thread_ids",
                    "python_thread_names",
                    "original_request_ids",
                    "worker_process_id",
                ],
            }
        ),
    )
    return 0


def _sanitize_artifact(
    artifact: dict[str, object],
) -> tuple[dict[str, object], dict[int, int]]:
    source_requests = artifact.get("requests")
    if not isinstance(source_requests, list):
        raise ValueError("artifact lacks requests array")
    request_id_map: dict[int, int] = {}
    requests: list[dict[str, object]] = []
    for ordinal, request in enumerate(source_requests, 1):
        if not isinstance(request, dict):
            raise ValueError("artifact request is not an object")
        original_request_id = request.get("request_id")
        if not isinstance(original_request_id, int):
            raise ValueError("artifact request lacks numeric request_id")
        if original_request_id in request_id_map:
            raise ValueError("artifact request IDs are not unique")
        request_id_map[original_request_id] = ordinal
        requests.append(_sanitize_request(request, ordinal))
    config = artifact.get("config")
    summary = artifact.get("summary")
    if not isinstance(config, dict) or not isinstance(summary, dict):
        raise ValueError("artifact lacks config or summary")
    return (
        {
            "cpp_api_soak_sanitized_artifact_schema_version": (
                _SANITIZATION_SCHEMA_VERSION
            ),
            "config": {
                key: config[key]
                for key in (
                    "language",
                    "sample_rate",
                    "channels",
                    "warmups",
                    "requests",
                    "cancel_every",
                    "seed",
                )
                if key in config
            },
            "startup_ms": artifact.get("startup_ms"),
            "summary": summary,
            "requests": requests,
        },
        request_id_map,
    )


def _sanitize_request(request: dict[str, object], ordinal: int) -> dict[str, object]:
    chunks = request.get("chunks")
    telemetry = request.get("worker_telemetry")
    if not isinstance(chunks, list) or not isinstance(telemetry, dict):
        raise ValueError("artifact request lacks chunks or worker telemetry")
    return {
        key: request[key]
        for key in (
            "index",
            "label",
            "success",
            "cancelled",
            "enqueue_ms",
            "first_audio_ms",
            "completed_ms",
            "audio_bytes",
            "audio_chunks",
            "audio_duration_ms",
            "real_time_factor",
            "local_rtf",
            "inverse_rtf",
            "worker_queue_ms",
            "worker_first_pcm_ready_ms",
            "worker_first_frame_enqueue_ms",
            "worker_pcm_to_enqueue_ms",
            "worker_writer_queue_ms",
            "worker_writer_flush_ms",
            "worker_writer_total_ms",
            "transport_dispatch_residual_ms",
            "manifest_contract",
        )
        if key in request
    } | {
        "request_id": ordinal,
        "chunks": [
            {
                key: chunk[key]
                for key in ("index", "arrival_ms", "audio_bytes", "audio_duration_ms")
                if key in chunk
            }
            for chunk in chunks
            if isinstance(chunk, dict)
        ],
        "worker_telemetry": _sanitize_embedded_telemetry(telemetry, ordinal),
    }


def _sanitize_embedded_telemetry(
    telemetry: dict[str, object],
    request_id: int,
) -> dict[str, object]:
    fields = {
        "first_chunk_phases": _FIRST_CHUNK_FIELDS,
        "pcm_chunks": _PCM_FIELDS,
        "finished": _FINISHED_FIELDS,
        "runtime_memory": _MEMORY_FIELDS,
    }
    result: dict[str, object] = {}
    for name, allowed in fields.items():
        value = telemetry.get(name)
        if isinstance(value, dict):
            result[name] = _sanitize_metric(value, allowed, request_id)
        elif name == "pcm_chunks" and isinstance(value, list):
            result[name] = [
                _sanitize_metric(chunk, allowed, request_id)
                for chunk in value
                if isinstance(chunk, dict)
            ]
    return result


def _sanitize_worker_metrics(
    metrics: list[dict[str, object]],
    request_id_map: dict[int, int],
) -> list[dict[str, object]]:
    event_fields = {
        "request_first_chunk_engine_phases": _FIRST_CHUNK_FIELDS,
        "request_pcm_chunk": _PCM_FIELDS,
        "request_finished": _FINISHED_FIELDS,
        "worker_runtime_memory": _MEMORY_FIELDS,
    }
    result: list[dict[str, object]] = []
    for metric in metrics:
        event = metric.get("event")
        original_request_id = metric.get("request_id")
        allowed = event_fields.get(event) if isinstance(event, str) else None
        if allowed is None or not isinstance(original_request_id, int):
            continue
        request_id = request_id_map.get(original_request_id)
        if request_id is None:
            continue
        result.append(_sanitize_metric(metric, allowed, request_id))
    return result


def _sanitize_metric(
    metric: dict[str, object],
    allowed_fields: set[str],
    request_id: int,
) -> dict[str, object]:
    result = {
        key: metric[key]
        for key in allowed_fields
        if key in metric and key != "request_id"
    }
    result["request_id"] = request_id
    if result.get("event") == "worker_runtime_memory":
        result["worker_pid"] = 1
    return result


def _load_object(value: bytes, name: str) -> dict[str, object]:
    parsed = json.loads(value.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError(f"{name} is not an object")
    return parsed


def _json_bytes(value: dict[str, object]) -> bytes:
    text = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    return text.encode("utf-8")


def _jsonl_bytes(values: list[dict[str, object]]) -> bytes:
    return "".join(
        json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n" for value in values
    ).encode("utf-8")


def _write_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
