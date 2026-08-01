"""Run a provenance-pinned Qwen discovery corpus through one warm engine."""

from __future__ import annotations

import argparse
import errno
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import subprocess
import statistics
import sys
import threading
import time
from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCHEMA_VERSION = 3
_SAMPLE_RATE = 24_000
_PCM_BYTES_PER_SECOND = _SAMPLE_RATE * 2
_PROFILE_KEYS = {
    "model_path",
    "runtime_backend",
    "device",
    "dtype",
    "attn_implementation",
    "emit_every_frames",
    "emit_chunk_schedule",
    "compiled_emit_chunk_schedule",
    "eager_emit_chunk_schedule",
    "decode_window_frames",
    "prefill_backend",
    "prefill_compile_compat_mode",
    "prefill_compile_lengths",
    "prefill_compile_on_miss",
    "prefill_unknown_shape_policy",
    "prefill_compile_policy",
    "prefill_allowlist_warmup_manifest",
    "prefill_allowlist_warmup_repeats",
    "prefill_allowlist_max_entries",
    "prefill_allowlist_max_abs_threshold",
    "prefill_require_precompiled",
    "prefill_first_chunk_warmup",
    "prefill_first_chunk_warmup_length",
    "prefill_generation_prime",
    "collect_generation_trace",
    "profile_prefill",
    "max_seq_len",
    "max_audio_seconds_per_utterance",
}
_ROUTE_FIELDS = {
    "talker_prefill_length",
    "prefill_shape_policy",
    "prefill_backend_used",
    "selected_chunk_schedule",
    "chunk_schedule_decision",
    "prefill_compile_cache_hit",
    "prefill_compile_attempted",
    "prefill_compile_fallback",
    "prefill_shape_allowlist_hit",
    "prefill_shape_call_ordinal",
    "prefill_compile_cache_entries",
    "prefill_compile_cache_entries_delta",
    "prefill_compile_cache_evictions_delta",
    "prefill_compile_on_miss",
    "prefill_require_precompiled",
    "prefill_dynamo_counter_available",
    "prefill_dynamo_unique_graphs_delta",
    "prefill_ms",
    "ar_decode_ms",
    "chunk_steps",
}


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    if args.limit < 0:
        parser.error("--limit must be zero or positive")
    if args.checkpoint_every <= 0:
        parser.error("--checkpoint-every must be positive")
    if not args.speaker.strip():
        parser.error("--speaker must not be empty")
    _require_clean_tracked_tree()
    policy = _load_holdout_policy(args.holdout_policy, args.input, args.profile)
    expected_split = "runtime_measurement_holdout" if policy is not None else "discovery"
    records, input_sha256, corpus_id = _load_discovery_records(
        args.input,
        args.runtime_split_audit,
        args.expected_corpus_id,
        expected_split=expected_split,
    )
    selected = records[: args.limit] if args.limit else records
    if not selected:
        parser.error("--limit selected no discovery records")
    profile = _load_profile(args.profile)
    manifest = _build_manifest(
        args,
        input_sha256,
        corpus_id,
        profile,
        len(selected),
        corpus_split=expected_split,
        holdout_policy=policy,
    )
    completed = _prepare_output(args.output_dir, manifest, resume=args.resume)
    pending = [record for record in selected if record["record_id"] not in completed]
    if not pending:
        _write_summary(args.output_dir, manifest, selected)
        print(json.dumps({"status": "already_completed", "record_count": len(selected)}))
        return 0

    engine = _create_engine(profile, args.speaker, args.seed)
    load_started = time.perf_counter()
    try:
        engine.load()
        manifest["engine_load_ms"] = _milliseconds(load_started)
        _atomic_write_json(args.output_dir / "run-manifest.json", manifest)

        warmup_started = time.perf_counter()
        warmup = engine.warmup()
        manifest["engine_warmup_ms"] = _milliseconds(warmup_started)
        manifest["engine_warmup"] = _json_safe(warmup)
        _atomic_write_json(args.output_dir / "run-manifest.json", manifest)

        request_ids = {
            str(record["record_id"]): ordinal
            for ordinal, record in enumerate(selected, 1)
        }
        for record in pending:
            request_id = request_ids[str(record["record_id"])]
            row = _measure_record(
                engine,
                request_id,
                record,
                args.speaker,
                args.seed,
            )
            _append_jsonl(args.output_dir / "records.jsonl", row)
            completed.add(str(record["record_id"]))
            if len(completed) % args.checkpoint_every == 0 or len(completed) == len(selected):
                _write_checkpoint(args.output_dir, manifest, selected, completed)
                print(
                    json.dumps(
                        {
                            "status": "progress",
                            "completed": len(completed),
                            "total": len(selected),
                            "record_id": record["record_id"],
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
    except Exception as exc:
        manifest["status"] = "failed"
        manifest["failure"] = f"{type(exc).__name__}: {exc}"
        _atomic_write_json(args.output_dir / "run-manifest.json", manifest)
        _write_checkpoint(args.output_dir, manifest, selected, completed)
        raise
    finally:
        engine.close()

    manifest["status"] = "completed"
    manifest["completed_at_utc"] = _utc_now()
    _atomic_write_json(args.output_dir / "run-manifest.json", manifest)
    summary = _write_summary(args.output_dir, manifest, selected)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Frozen discovery JSONL, never holdout.")
    parser.add_argument("--runtime-split-audit", type=Path, required=True)
    parser.add_argument("--expected-corpus-id", required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--speaker", default="ryan")
    parser.add_argument(
        "--seed",
        type=int,
        default=20260731,
        help="Base seed; request IDs make completed rows reproducible.",
    )
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--checkpoint-every", type=int, default=10)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--holdout-policy",
        type=Path,
        help="Frozen policy required to measure the runtime holdout.",
    )
    return parser


def _load_discovery_records(
    input_path: Path,
    audit_path: Path,
    expected_corpus_id: str,
    *,
    expected_split: str = "discovery",
) -> tuple[list[dict[str, object]], str, str]:
    input_sha256 = _sha256(input_path)
    audit = _load_object(audit_path, "runtime split audit")
    if audit.get("corpus_id") != expected_corpus_id:
        raise RuntimeError("runtime split audit does not match --expected-corpus-id")
    sha_key = "holdout_sha256" if expected_split != "discovery" else "discovery_sha256"
    count_key = "holdout_count" if expected_split != "discovery" else "discovery_count"
    if audit.get(sha_key) != input_sha256:
        raise RuntimeError("input SHA does not match the pinned discovery SHA")

    records: list[dict[str, object]] = []
    record_ids: set[str] = set()
    corpus_ids: set[str] = set()
    for line_number, line in enumerate(input_path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            raise RuntimeError(f"line {line_number}: blank lines are not allowed")
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"line {line_number}: malformed JSON") from exc
        if not isinstance(value, dict):
            raise RuntimeError(f"line {line_number}: record must be an object")
        record_id = value.get("record_id")
        text = value.get("text")
        corpus_id = value.get("corpus_id")
        if not isinstance(record_id, str) or not record_id:
            raise RuntimeError(f"line {line_number}: record_id must be a non-empty string")
        if not isinstance(text, str) or not text.strip():
            raise RuntimeError(f"line {line_number}: text must be a non-empty string")
        if not isinstance(corpus_id, str) or not corpus_id:
            raise RuntimeError(f"line {line_number}: corpus_id must be a non-empty string")
        if value.get("corpus_split") != expected_split:
            if expected_split == "discovery":
                raise RuntimeError("input is not a discovery split; holdout is forbidden")
            raise RuntimeError(f"input corpus_split must be {expected_split}")
        if record_id in record_ids:
            raise RuntimeError(f"line {line_number}: duplicate record_id {record_id}")
        record_ids.add(record_id)
        corpus_ids.add(corpus_id)
        records.append(value)
    if not records:
        raise RuntimeError("input contains no discovery records")
    if corpus_ids != {expected_corpus_id}:
        raise RuntimeError("input corpus_id does not match --expected-corpus-id")
    expected_count = audit.get(count_key)
    if not isinstance(expected_count, int) or expected_count != len(records):
        raise RuntimeError("input record count does not match runtime split audit")
    return records, input_sha256, expected_corpus_id


def _load_profile(path: Path) -> dict[str, object]:
    profile = _load_object(path, "profile")
    missing = sorted(_PROFILE_KEYS.difference(profile))
    if missing:
        raise RuntimeError("profile is missing " + ", ".join(missing))
    if profile.get("runtime_backend") != "faster":
        raise RuntimeError("corpus discovery requires runtime_backend=faster")
    if profile.get("collect_generation_trace") is not True:
        raise RuntimeError("profile must enable collect_generation_trace")
    return profile


def _load_holdout_policy(
    path: Path | None,
    input_path: Path,
    profile_path: Path,
) -> dict[str, object] | None:
    if path is None:
        return None
    policy = _load_object(path, "holdout policy")
    if policy.get("status") != "frozen_for_one_measurement_holdout":
        raise RuntimeError("holdout policy is not frozen")
    if policy.get("input_sha256") != _sha256(input_path):
        raise RuntimeError("holdout policy input SHA does not match")
    if policy.get("profile_sha256") != _sha256(profile_path):
        raise RuntimeError("holdout policy profile SHA does not match")
    if policy.get("allow_padded_prefill") is not False:
        raise RuntimeError("holdout policy must reject padded prefill")
    return {
        "path": str(path),
        "sha256": _sha256(path),
        "policy_name": policy.get("policy_name"),
    }


def _build_manifest(
    args: argparse.Namespace,
    input_sha256: str,
    corpus_id: str,
    profile: Mapping[str, object],
    selected_record_count: int,
    *,
    corpus_split: str,
    holdout_policy: dict[str, object] | None,
) -> dict[str, object]:
    return {
        "corpus_discovery_schema_version": _SCHEMA_VERSION,
        "status": "running",
        "started_at_utc": _utc_now(),
        "corpus_id": corpus_id,
        "corpus_split": corpus_split,
        "holdout_policy": holdout_policy,
        "input": _provenance(args.input),
        "input_sha256": input_sha256,
        "runtime_split_audit": _provenance(args.runtime_split_audit),
        "profile": _provenance(args.profile),
        "profile_name": profile.get("name"),
        "speaker": args.speaker,
        "seed": args.seed,
        "seed_mode": "request_id",
        "selected_record_count": selected_record_count,
        "runtime": _runtime_metadata(profile),
    }


def _prepare_output(
    output_dir: Path,
    manifest: Mapping[str, object],
    *,
    resume: bool,
) -> set[str]:
    if not output_dir.exists():
        output_dir.mkdir(parents=True)
        _atomic_write_json(output_dir / "run-manifest.json", dict(manifest))
        return set()
    if not resume:
        raise RuntimeError("output directory exists; pass --resume to continue it")
    saved = _load_object(output_dir / "run-manifest.json", "existing run manifest")
    for key in (
        "corpus_id",
        "corpus_split",
        "input_sha256",
        "speaker",
        "seed",
        "seed_mode",
        "selected_record_count",
    ):
        if saved.get(key) != manifest.get(key):
            raise RuntimeError(f"existing run manifest does not match {key}")
    saved_profile = saved.get("profile")
    current_profile = manifest.get("profile")
    if saved_profile != current_profile:
        raise RuntimeError("existing run manifest does not match profile provenance")
    return _completed_record_ids(output_dir / "records.jsonl")


def _completed_record_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    completed: set[str] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        value = json.loads(line)
        if not isinstance(value, dict) or not _is_terminal_row(value):
            raise RuntimeError(f"records line {line_number}: invalid terminal row")
        record_id = value.get("record_id")
        if not isinstance(record_id, str) or not record_id or record_id in completed:
            raise RuntimeError(f"records line {line_number}: invalid record_id")
        completed.add(record_id)
    return completed


def _create_engine(profile: Mapping[str, object], speaker: str, seed: int) -> Any:
    from qwen_tts_bridge_worker.config import QwenEngineConfig
    from qwen_tts_bridge_worker.engine import QwenTtsEngine

    model_path = Path(str(profile["model_path"]))
    if not model_path.is_absolute():
        model_path = _REPO_ROOT / model_path
    warmup_manifest = Path(str(profile["prefill_allowlist_warmup_manifest"]))
    if not warmup_manifest.is_absolute():
        warmup_manifest = _REPO_ROOT / warmup_manifest
    config = QwenEngineConfig(
        model_path=str(model_path.resolve()),
        runtime_backend="faster",
        device=str(profile["device"]),
        dtype=str(profile["dtype"]),
        attn_implementation=str(profile["attn_implementation"]),
        emit_every_frames=int(profile["emit_every_frames"]),
        emit_chunk_schedule=_as_positive_tuple(profile["emit_chunk_schedule"]),
        compiled_emit_chunk_schedule=_as_positive_tuple(
            profile["compiled_emit_chunk_schedule"]
        ),
        eager_emit_chunk_schedule=_as_positive_tuple(profile["eager_emit_chunk_schedule"]),
        decode_window_frames=int(profile["decode_window_frames"]),
        prefill_backend=str(profile["prefill_backend"]),
        prefill_compile_compat_mode=str(profile["prefill_compile_compat_mode"]),
        prefill_compile_lengths=_as_positive_tuple(profile["prefill_compile_lengths"]),
        prefill_compile_on_miss=bool(profile["prefill_compile_on_miss"]),
        prefill_unknown_shape_policy=str(profile["prefill_unknown_shape_policy"]),
        prefill_compile_policy=str(profile["prefill_compile_policy"]),
        prefill_allowlist_warmup_manifest=str(warmup_manifest.resolve()),
        prefill_allowlist_warmup_repeats=int(profile["prefill_allowlist_warmup_repeats"]),
        prefill_allowlist_max_entries=int(profile["prefill_allowlist_max_entries"]),
        prefill_allowlist_max_abs_threshold=float(
            profile["prefill_allowlist_max_abs_threshold"]
        ),
        prefill_require_precompiled=bool(profile["prefill_require_precompiled"]),
        prefill_first_chunk_warmup_enabled=bool(
            profile["prefill_first_chunk_warmup"]
        ),
        prefill_first_chunk_warmup_length=(
            int(profile["prefill_first_chunk_warmup_length"])
            if profile["prefill_first_chunk_warmup_length"] is not None
            else None
        ),
        prefill_generation_prime_enabled=bool(
            profile.get("prefill_generation_prime", False)
        ),
        collect_generation_trace=True,
        max_seq_len=int(profile.get("max_seq_len", 2048)),
        max_audio_seconds_per_utterance=_optional_positive_float(
            profile.get("max_audio_seconds_per_utterance")
        ),
        seed=seed,
        seed_mode="request_id",
        warmup_speaker=speaker,
    )
    return QwenTtsEngine(config)


def _measure_record(
    engine: Any,
    request_id: int,
    record: Mapping[str, object],
    speaker: str,
    base_seed: int,
) -> dict[str, object]:
    from qwen_tts_bridge_worker.engine import (
        GenerationSafetyLimitError,
        SynthesisRequest,
    )

    started_at = time.perf_counter()
    first_audio_ms: float | None = None
    audio_bytes = 0
    audio_chunks = 0
    first_metrics: dict[str, object] | None = None
    request = SynthesisRequest(
        request_id=request_id,
        text=str(record["text"]),
        language=_language_for_record(str(record.get("language_class", ""))),
        speaker=speaker,
        instruction="",
    )
    engine.validate_request(request)
    cancel_event = threading.Event()
    stream = engine.synthesize_stream(request, cancel_event)
    execution_outcome = "completed"
    generation_outcome: str | None = None
    failure: dict[str, object] | None = None
    try:
        for pcm in stream:
            audio_chunks += 1
            audio_bytes += len(pcm)
            metrics = engine.pop_last_chunk_metrics()
            if first_audio_ms is None:
                first_audio_ms = _milliseconds(started_at)
                first_metrics = dict(metrics) if isinstance(metrics, dict) else {}
    except GenerationSafetyLimitError as exc:
        execution_outcome = "failed"
        generation_outcome = "safety_duration_limit"
        failure = {
            "category": "resource_error",
            "code": "safety_duration_limit",
            "message": str(exc),
            "max_audio_seconds_per_utterance": exc.limit_seconds,
            "emitted_audio_seconds": exc.emitted_seconds,
        }
    finally:
        close = getattr(stream, "close", None)
        if callable(close):
            close()
    completed_ms = _milliseconds(started_at)
    if first_audio_ms is None or audio_chunks == 0:
        raise RuntimeError(f"{record['record_id']}: synthesis completed without PCM")
    audio_seconds = audio_bytes / _PCM_BYTES_PER_SECOND
    generation_trace = _json_safe(engine.pop_last_generation_trace())
    if generation_outcome is None:
        generation_outcome = _generation_outcome(generation_trace)
    return {
        "record_id": record["record_id"],
        "request_id": request_id,
        "derived_request_seed": base_seed + request_id,
        "label": record.get("label"),
        "category": record.get("category"),
        "scene_context": record.get("scene_context"),
        "speech_intent": record.get("speech_intent"),
        "intended_length_class": record.get("intended_length_class"),
        "language_class": record.get("language_class"),
        "text_sha256": hashlib.sha256(str(record["text"]).encode("utf-8")).hexdigest(),
        "text_characters": len(str(record["text"])),
        # request_outcome is retained for v1 readers. New consumers must use the
        # explicit execution and generation outcomes below.
        "request_outcome": execution_outcome,
        "execution_outcome": execution_outcome,
        "generation_outcome": generation_outcome,
        "generation_accepted": generation_outcome == "eos",
        "first_audio_ms": round(first_audio_ms, 3),
        "completed_ms": round(completed_ms, 3),
        "audio_seconds": round(audio_seconds, 6),
        "inverse_rtf": round(audio_seconds / (completed_ms / 1000.0), 6),
        "audio_chunks": audio_chunks,
        "audio_bytes": audio_bytes,
        "first_chunk_route": _route_fields(first_metrics or {}),
        "generation_trace": generation_trace,
        "failure": failure,
    }


def _write_checkpoint(
    output_dir: Path,
    manifest: Mapping[str, object],
    selected: Iterable[Mapping[str, object]],
    completed: set[str],
) -> None:
    selected_ids = [str(record["record_id"]) for record in selected]
    _atomic_write_json(
        output_dir / "checkpoint.json",
        {
            "corpus_discovery_schema_version": _SCHEMA_VERSION,
            "corpus_id": manifest["corpus_id"],
            "corpus_split": manifest["corpus_split"],
            "input_sha256": manifest["input_sha256"],
            "selected_record_count": len(selected_ids),
            "completed_record_count": len(completed),
            "remaining_record_count": len(selected_ids) - len(completed),
            "completed_record_id_set_sha256": _record_id_set_sha256(completed),
            "updated_at_utc": _utc_now(),
        },
    )


def _write_summary(
    output_dir: Path,
    manifest: Mapping[str, object],
    selected: list[Mapping[str, object]],
) -> dict[str, object]:
    rows = _load_terminal_rows(output_dir / "records.jsonl")
    expected_ids = {str(record["record_id"]) for record in selected}
    observed_ids = {str(row["record_id"]) for row in rows}
    if observed_ids != expected_ids:
        raise RuntimeError("completed records do not match the selected corpus set")
    summary = {
        "corpus_discovery_schema_version": _SCHEMA_VERSION,
        "status": "completed",
        "corpus_id": manifest["corpus_id"],
        "corpus_split": manifest["corpus_split"],
        "input_sha256": manifest["input_sha256"],
        "profile_sha256": _nested_sha(manifest, "profile"),
        "runtime": manifest["runtime"],
        "record_count": len(rows),
        "record_id_set_sha256": _record_id_set_sha256(observed_ids),
        "records_sha256": _sha256(output_dir / "records.jsonl"),
        "first_audio_ms": _distribution(rows, "first_audio_ms"),
        "completed_ms": _distribution(rows, "completed_ms"),
        "inverse_rtf": _distribution(rows, "inverse_rtf"),
        "audio_seconds": _distribution(rows, "audio_seconds"),
        "execution_outcomes": _outcome_counts(rows, "execution_outcome"),
        "generation_outcomes": _generation_outcome_counts(rows),
        "generation_acceptance_pass": all(
            _row_generation_outcome(row) == "eos" for row in rows
        ),
        "route_counts": _route_counts(rows),
        "talker_prefill_histogram": _prefill_histogram(rows),
    }
    _atomic_write_json(output_dir / "summary.json", summary)
    _write_checkpoint(output_dir, manifest, selected, observed_ids)
    return summary


def _load_terminal_rows(path: Path) -> list[dict[str, object]]:
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        value = json.loads(line)
        if not isinstance(value, dict) or not _is_terminal_row(value):
            raise RuntimeError(f"records line {line_number}: invalid terminal row")
        rows.append(value)
    if not rows:
        raise RuntimeError("records output contains no terminal rows")
    return rows


def _is_terminal_row(row: Mapping[str, object]) -> bool:
    execution_outcome = row.get("execution_outcome")
    if execution_outcome is not None:
        return execution_outcome in {"completed", "failed", "cancelled"}
    return row.get("request_outcome") == "completed"


def _row_generation_outcome(row: Mapping[str, object]) -> str:
    outcome = row.get("generation_outcome")
    if isinstance(outcome, str):
        return outcome
    return _generation_outcome(row.get("generation_trace"))


def _generation_outcome(trace: object) -> str:
    if not isinstance(trace, Mapping):
        return "unknown"
    if trace.get("hit_eos") is True or trace.get("termination_reason") == "eos":
        return "eos"
    if trace.get("hit_max_new_tokens") is True or trace.get("termination_reason") == "max_new_tokens":
        return "max_new_tokens"
    if trace.get("hit_max_seq_len") is True or trace.get("termination_reason") == "max_seq_len":
        return "max_seq_len"
    return "unknown"


def _outcome_counts(
    rows: Iterable[Mapping[str, object]],
    field: str,
) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in rows:
        value = row.get(field)
        if isinstance(value, str):
            counts[value] += 1
        elif field == "execution_outcome" and row.get("request_outcome") == "completed":
            counts["completed"] += 1
        else:
            counts["unknown"] += 1
    return dict(sorted(counts.items()))


def _generation_outcome_counts(rows: Iterable[Mapping[str, object]]) -> dict[str, int]:
    counts: Counter[str] = Counter(_row_generation_outcome(row) for row in rows)
    return dict(sorted(counts.items()))


def _route_counts(rows: Iterable[Mapping[str, object]]) -> dict[str, dict[str, int]]:
    fields = ("prefill_shape_policy", "prefill_backend_used", "selected_chunk_schedule")
    result: dict[str, dict[str, int]] = {}
    for field in fields:
        counts: Counter[str] = Counter()
        for row in rows:
            route = row.get("first_chunk_route")
            if not isinstance(route, dict):
                counts["missing"] += 1
                continue
            value = route.get(field)
            counts[json.dumps(value, ensure_ascii=False, sort_keys=True)] += 1
        result[field] = dict(sorted(counts.items()))
    return result


def _prefill_histogram(rows: Iterable[Mapping[str, object]]) -> list[dict[str, int]]:
    counts: Counter[int] = Counter()
    for row in rows:
        route = row.get("first_chunk_route")
        if not isinstance(route, dict):
            continue
        value = route.get("talker_prefill_length")
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            counts[value] += 1
    return [
        {"talker_prefill_length": length, "count": count}
        for length, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def _distribution(rows: Iterable[Mapping[str, object]], key: str) -> dict[str, float]:
    values = [float(row[key]) for row in rows if isinstance(row.get(key), (int, float))]
    if not values:
        return {}
    values.sort()
    return {
        "min": round(values[0], 3),
        "p50": round(_percentile(values, 0.50), 3),
        "p90": round(_percentile(values, 0.90), 3),
        "p95": round(_percentile(values, 0.95), 3),
        "p99": round(_percentile(values, 0.99), 3),
        "max": round(values[-1], 3),
        "mean": round(statistics.fmean(values), 3),
    }


def _percentile(values: list[float], fraction: float) -> float:
    if len(values) == 1:
        return values[0]
    index = (len(values) - 1) * fraction
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return values[lower]
    return values[lower] + (values[upper] - values[lower]) * (index - lower)


def _route_fields(metrics: Mapping[str, object]) -> dict[str, object]:
    return {key: _json_safe(metrics[key]) for key in sorted(_ROUTE_FIELDS) if key in metrics}


def _language_for_record(language_class: str) -> str:
    return {"ru": "Russian", "en": "English", "mixed": "Auto"}.get(
        language_class,
        "Auto",
    )


def _as_positive_tuple(value: object) -> tuple[int, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, int) or isinstance(item, bool) or item <= 0 for item in value
    ):
        raise RuntimeError("profile contains an invalid positive integer list")
    return tuple(value)


def _optional_positive_float(value: object) -> float | None:
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        raise RuntimeError("profile contains an invalid positive duration")
    return float(value)


def _load_object(path: Path, name: str) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise RuntimeError(f"cannot read {name}: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{name} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"{name} must contain a JSON object")
    return value


def _runtime_metadata(profile: Mapping[str, object]) -> dict[str, object]:
    import torch

    try:
        faster_version = importlib.metadata.version("faster-qwen3-tts")
    except importlib.metadata.PackageNotFoundError:
        faster_version = "unpackaged"
    faster_source: dict[str, object] | None = None
    try:
        import faster_qwen3_tts

        faster_module_path = Path(faster_qwen3_tts.__file__).resolve()
        faster_module = str(faster_module_path)
        faster_source = _source_provenance(faster_module_path.parent)
    except ImportError:
        faster_module = "unavailable"
    try:
        triton_version = importlib.metadata.version("triton-windows")
    except importlib.metadata.PackageNotFoundError:
        triton_version = None
    flash_attention_available = False
    try:
        import flash_attn  # noqa: F401

        flash_attention_available = True
    except ImportError:
        pass
    return {
        "python": sys.version,
        "platform": platform.platform(),
        "torch_version": torch.__version__,
        "cuda_version": torch.version.cuda,
        "cuda_available": torch.cuda.is_available(),
        "cuda_device_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "faster_qwen3_tts_version": faster_version,
        "faster_qwen3_tts_module": faster_module,
        "faster_qwen3_tts_source": faster_source,
        "triton_windows_version": triton_version,
        "triton_windows_wheel_filename": profile.get("triton_windows_wheel_filename"),
        "triton_windows_wheel_sha256": profile.get("triton_windows_wheel_sha256"),
        "flash_attention_available": flash_attention_available,
        "bridge_commit": _git_output(_REPO_ROOT, "rev-parse", "HEAD"),
        "bridge_git_tree": _git_output(_REPO_ROOT, "rev-parse", "HEAD^{tree}"),
        "bridge_tracked_tree_clean": _tracked_tree_is_clean(_REPO_ROOT),
        "bridge_worker_source_bundle_sha256": _directory_sha256(
            _REPO_ROOT / "worker" / "src" / "qwen_tts_bridge_worker"
        ),
    }


def _provenance(path: Path) -> dict[str, str]:
    return {"path": str(path), "sha256": _sha256(path)}


def _nested_sha(value: Mapping[str, object], key: str) -> str | None:
    nested = value.get(key)
    return nested.get("sha256") if isinstance(nested, dict) else None


def _record_id_set_sha256(record_ids: Iterable[str]) -> str:
    return hashlib.sha256("\n".join(sorted(record_ids)).encode("utf-8")).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _append_jsonl(path: Path, value: Mapping[str, object]) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(_json_safe(value), ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        try:
            os.fsync(handle.fileno())
        except OSError as exc:
            # Some Windows filesystem/filter-driver combinations reject fsync
            # on a text handle after many writes. The append and atomic checkpoint
            # remain process-crash resumable, but are not a power-loss durability
            # guarantee when this fallback is used.
            if exc.errno != errno.EINVAL:
                raise


def _atomic_write_json(path: Path, value: Mapping[str, object]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(_json_safe(value), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _json_safe(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return str(value)


def _milliseconds(started_at: float) -> float:
    return (time.perf_counter() - started_at) * 1000.0


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _require_clean_tracked_tree() -> None:
    if not _tracked_tree_is_clean(_REPO_ROOT):
        raise RuntimeError(
            "discovery requires a clean tracked git tree; commit or stash tracked "
            "changes before running it"
        )


def _tracked_tree_is_clean(path: Path) -> bool:
    return all(
        _git_returncode(path, *arguments) == 0
        for arguments in (
            ("diff", "--quiet", "--ignore-submodules=dirty"),
            ("diff", "--cached", "--quiet", "--ignore-submodules=dirty"),
        )
    )


def _source_provenance(module_directory: Path) -> dict[str, object]:
    repository = _git_output(module_directory, "rev-parse", "--show-toplevel")
    repository_path = Path(repository) if repository is not None else None
    return {
        "module_directory": str(module_directory),
        "module_bundle_sha256": _directory_sha256(module_directory),
        "source_repository": str(repository_path) if repository_path is not None else None,
        "source_commit": (
            _git_output(repository_path, "rev-parse", "HEAD")
            if repository_path is not None
            else None
        ),
        "source_git_tree": (
            _git_output(repository_path, "rev-parse", "HEAD^{tree}")
            if repository_path is not None
            else None
        ),
        "source_tracked_tree_clean": (
            _tracked_tree_is_clean(repository_path)
            if repository_path is not None
            else None
        ),
    }


def _directory_sha256(path: Path) -> str | None:
    if not path.is_dir():
        return None
    digest = hashlib.sha256()
    files = sorted(
        candidate
        for candidate in path.rglob("*")
        if candidate.is_file() and "__pycache__" not in candidate.parts
    )
    for candidate in files:
        digest.update(candidate.relative_to(path).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(candidate.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _git_output(path: Path, *arguments: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "-C", str(path), *arguments],
            capture_output=True,
            check=False,
            text=True,
        )
    except OSError:
        return None
    value = completed.stdout.strip()
    return value if completed.returncode == 0 and value else None


def _git_returncode(path: Path, *arguments: str) -> int | None:
    try:
        completed = subprocess.run(
            ["git", "-C", str(path), *arguments],
            capture_output=True,
            check=False,
            text=True,
        )
    except OSError:
        return None
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
